"""公开的 demo 3D 场景 AI 操作端点（访客即玩，无需登录/会话）。

复用 Scene Agent 的 LLM 规划 + 确定性白名单执行，持久化幂等、计费元数据和
首次白名单执行结果，不保存原始指令，供 /demo 页多轮对话使用。
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.scene_agent import SceneAgentSafetyError, SceneAgentWorkflow
from app.api.dependencies import SessionIdHeader, require_active_session
from app.core.config import settings
from app.core.request_context import current_request_id, normalize_request_id
from app.db.database import get_db
from app.db.models import DemoAgentInvocation
from app.schemas.scene_agent import SceneOperation, SceneOperationBatch
from app.schemas.scenes import SceneDocument
from app.services import (
    llm_service,
    model_call_governance_service,
    scene_service,
    scene_tools,
    task_timeline_service,
)
from app.services.llm_service import LLMUnavailable
from app.services.scene_agent_rate_limit import SceneAgentRateLimiter

router = APIRouter()
logger = logging.getLogger(__name__)
demo_session_rate_limiter = SceneAgentRateLimiter(
    max_requests=settings.demo_agent_requests_per_minute,
    window_seconds=60,
)
demo_ip_rate_limiter = SceneAgentRateLimiter(
    max_requests=settings.demo_agent_ip_requests_per_minute,
    window_seconds=60,
)

IdempotencyKeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


class DemoConversationTurn(BaseModel):
    instruction: str = Field(min_length=2, max_length=1000)
    message: str = Field(min_length=1, max_length=500)
    operations: list[SceneOperation] = Field(max_length=12)
    affected_instance_ids: list[str] = Field(
        default_factory=list,
        max_length=12,
        alias="affectedInstanceIds",
    )


class DemoAgentCommandRequest(BaseModel):
    instruction: str = Field(min_length=2, max_length=1000)
    scene: SceneDocument
    history: list[DemoConversationTurn] = Field(default_factory=list, max_length=8)


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _operation_key(session_id: str, idempotency_key: str) -> str:
    raw = f"{session_id}:{idempotency_key}".encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _find_invocation(
    db: Session,
    *,
    session_id: str,
    operation_key: str,
) -> DemoAgentInvocation | None:
    return db.scalar(
        select(DemoAgentInvocation).where(
            DemoAgentInvocation.session_id == session_id,
            DemoAgentInvocation.operation_key == operation_key,
        )
    )


def _raise_replayed_error(invocation: DemoAgentInvocation) -> None:
    stored = invocation.result_json if isinstance(invocation.result_json, dict) else {}
    raise HTTPException(
        status_code=invocation.response_status or 503,
        detail=stored.get("detail", "AI 服务暂时不可用，请稍后再试"),
    )


def _execute_operations(
    db: Session,
    *,
    payload: DemoAgentCommandRequest,
    context: dict,
    batch: SceneOperationBatch,
) -> dict:
    workflow = SceneAgentWorkflow(
        plan_operations=lambda **_: batch,
        execute_operations=lambda document, operations: (
            scene_tools.apply_scene_operations(db, document, operations)
        ),
        validate_scene=lambda document: scene_service.validate_scene(db, document),
    )
    result = workflow.run(
        instruction=payload.instruction,
        context=context,
        source_scene=payload.scene,
    )
    proposed_scene = result["proposed_scene"]
    if proposed_scene is None:
        raise RuntimeError("Scene Agent 未生成候选场景")
    return {
        "message": batch.message,
        "operations": [
            operation.model_dump(mode="json", by_alias=True)
            for operation in batch.operations
        ],
        "scene": proposed_scene.model_dump(mode="json", by_alias=True),
    }


def _record_billing(invocation: DemoAgentInvocation, capture) -> None:
    billing_status, cost_cny = task_timeline_service.billing_for_model_call(
        attempted=capture.attempted,
        usage=capture.usage,
        input_price_per_mtok=settings.llm_input_price_per_mtok,
        output_price_per_mtok=settings.llm_output_price_per_mtok,
    )
    invocation.attempt_count = capture.attempt_count
    invocation.usage_json = capture.usage
    invocation.billing_status = billing_status
    invocation.cost_cny = cost_cny


def _record_failure(
    db: Session,
    *,
    invocation: DemoAgentInvocation,
    capture,
    status_code: int,
    error_code: str,
    detail: object,
) -> None:
    _record_billing(invocation, capture)
    invocation.status = "failed"
    invocation.response_status = status_code
    invocation.error_code = error_code
    invocation.result_json = {"detail": detail}
    invocation.completed_at = datetime.now(timezone.utc)
    db.commit()


@router.post("/demo/agent-command")
def demo_agent_command(
    payload: DemoAgentCommandRequest,
    request: Request,
    x_session_id: SessionIdHeader,
    idempotency_key: IdempotencyKeyHeader,
    db: Session = Depends(get_db),
):
    """把自然语言指令转成白名单操作，返回给前端在 demo 场景本地执行。

    Demo 场景仍是前端本地状态；数据库只记录调用状态、用量、成本与白名单操作。
    """
    require_active_session(db, x_session_id)
    request_digest = _sha256_json(payload.model_dump(mode="json", by_alias=True))
    operation_key = _operation_key(x_session_id, idempotency_key)
    existing = _find_invocation(
        db,
        session_id=x_session_id,
        operation_key=operation_key,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key 已用于不同的 Demo Agent 输入",
            )
        if existing.status == "failed":
            _raise_replayed_error(existing)
        if existing.status == "running":
            raise HTTPException(
                status_code=409,
                detail="同一 Demo Agent 请求仍在处理中",
                headers={"Retry-After": "1"},
            )
        return existing.result_json or {}

    ip_key = request.client.host if request.client else "unknown"
    retry_after = None
    if x_session_id:
        retry_after = demo_session_rate_limiter.retry_after(
            f"session:{x_session_id}"
        )
    if retry_after is None:
        retry_after = demo_ip_rate_limiter.retry_after(f"ip:{ip_key}")
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="AI 布局请求过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )

    context = scene_tools.build_scene_agent_context(db, payload.scene)
    invocation = DemoAgentInvocation(
        session_id=x_session_id,
        operation_key=operation_key,
        request_digest=request_digest,
        status="running",
        request_id=(
            current_request_id()
            or normalize_request_id(request.headers.get("X-Request-ID"))
        ),
    )
    db.add(invocation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = _find_invocation(
            db,
            session_id=x_session_id,
            operation_key=operation_key,
        )
        if concurrent is None or concurrent.request_digest != request_digest:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key 已用于不同的 Demo Agent 输入",
            )
        if concurrent.status == "failed":
            _raise_replayed_error(concurrent)
        if concurrent.status == "completed":
            return concurrent.result_json or {}
        raise HTTPException(
            status_code=409,
            detail="同一 Demo Agent 请求仍在处理中",
            headers={"Retry-After": "1"},
        )

    history = [
        turn.model_dump(mode="json", by_alias=True)
        for turn in payload.history[-8:]
    ]
    with (
        model_call_governance_service.govern_session_model_calls(
            db,
            session_id=x_session_id,
            operation_key=f"demo:{operation_key}",
        ),
        llm_service.capture_model_call() as capture,
    ):
        try:
            batch = llm_service.plan_scene_operations(
                instruction=payload.instruction,
                context=context,
                history=history,
            )
        except LLMUnavailable as exc:
            detail = "AI 服务暂时不可用，请稍后再试"
            _record_failure(
                db,
                invocation=invocation,
                capture=capture,
                status_code=503,
                error_code="llm_unavailable",
                detail=detail,
            )
            raise HTTPException(status_code=503, detail=detail) from exc
        except Exception as exc:
            detail = "AI 服务暂时不可用，请稍后再试"
            logger.exception("Demo Agent 模型调用失败")
            _record_failure(
                db,
                invocation=invocation,
                capture=capture,
                status_code=503,
                error_code="provider_error",
                detail=detail,
            )
            raise HTTPException(status_code=503, detail=detail) from exc

    try:
        response = _execute_operations(db, payload=payload, context=context, batch=batch)
    except scene_tools.SceneToolError as exc:
        _record_failure(
            db,
            invocation=invocation,
            capture=capture,
            status_code=422,
            error_code="scene_tool_error",
            detail=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SceneAgentSafetyError as exc:
        detail = {
            "message": str(exc),
            "validation": exc.report.model_dump(mode="json"),
        }
        _record_failure(
            db,
            invocation=invocation,
            capture=capture,
            status_code=422,
            error_code="scene_safety_error",
            detail=detail,
        )
        raise HTTPException(status_code=422, detail=detail) from exc
    except Exception as exc:
        detail = "场景操作执行失败，请稍后重试"
        logger.exception("Demo Agent 场景操作失败")
        _record_failure(
            db,
            invocation=invocation,
            capture=capture,
            status_code=503,
            error_code="scene_execution_error",
            detail=detail,
        )
        raise HTTPException(status_code=503, detail=detail) from exc

    _record_billing(invocation, capture)
    invocation.status = "completed"
    invocation.response_status = 200
    invocation.result_json = response
    invocation.completed_at = datetime.now(timezone.utc)
    db.commit()
    return response
