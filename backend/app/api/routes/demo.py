"""公开的 demo 3D 场景 AI 操作端点（访客即玩，无需登录/会话）。

复用 Scene Agent 的 LLM 规划 + 确定性白名单执行，但不写入数据库，
只对传入的场景文档做本地修改并返回，供 /demo 页多轮对话使用。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.scene_agent import SceneAgentSafetyError, SceneAgentWorkflow
from app.core.config import settings
from app.db.database import get_db
from app.schemas.scene_agent import SceneOperation
from app.schemas.scenes import SceneDocument
from app.services import llm_service, scene_service, scene_tools
from app.services.llm_service import LLMUnavailable
from app.services.scene_agent_rate_limit import SceneAgentRateLimiter

router = APIRouter()
demo_session_rate_limiter = SceneAgentRateLimiter(
    max_requests=settings.demo_agent_requests_per_minute,
    window_seconds=60,
)
demo_ip_rate_limiter = SceneAgentRateLimiter(
    max_requests=settings.demo_agent_ip_requests_per_minute,
    window_seconds=60,
)

OptionalSessionIdHeader = Annotated[
    str | None,
    Header(alias="X-Session-ID", min_length=36, max_length=36),
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


@router.post("/demo/agent-command")
def demo_agent_command(
    payload: DemoAgentCommandRequest,
    request: Request,
    x_session_id: OptionalSessionIdHeader = None,
    db: Session = Depends(get_db),
):
    """把自然语言指令转成白名单操作，返回给前端在 demo 场景本地执行。

    只做 LLM 指令理解，不写库、不执行操作（demo 场景是前端本地状态）。
    """
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
    history = [
        turn.model_dump(mode="json", by_alias=True)
        for turn in payload.history[-8:]
    ]
    try:
        batch = llm_service.plan_scene_operations(
            instruction=payload.instruction,
            context=context,
            history=history,
        )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail="AI 服务暂时不可用，请稍后再试") from exc

    workflow = SceneAgentWorkflow(
        plan_operations=lambda **_: batch,
        execute_operations=lambda document, operations: (
            scene_tools.apply_scene_operations(db, document, operations)
        ),
        validate_scene=lambda document: scene_service.validate_scene(db, document),
    )
    try:
        result = workflow.run(
            instruction=payload.instruction,
            context=context,
            source_scene=payload.scene,
        )
        proposed_scene = result["proposed_scene"]
        if proposed_scene is None:
            raise RuntimeError("Scene Agent 未生成候选场景")
    except scene_tools.SceneToolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SceneAgentSafetyError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "validation": exc.report.model_dump(mode="json"),
            },
        ) from exc

    return {
        "message": batch.message,
        "operations": [
            operation.model_dump(mode="json", by_alias=True)
            for operation in batch.operations
        ],
        "scene": proposed_scene.model_dump(mode="json", by_alias=True),
    }
