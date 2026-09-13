from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import (
    SessionIdHeader,
    require_admin,
    require_active_session,
    require_owned_design_task,
)
from app.db.database import get_db
from app.db.models import User
from app.schemas.design_agent import (
    AgentCheckpointResponse,
    AgentEventFeedResponse,
    AgentTurnRequest,
    AgentTurnResponse,
    CustomFurnitureDraftRequest,
    CustomFurnitureDraftResponse,
)
from app.schemas.agent_approval import (
    AgentApprovalDecisionRequest,
    AgentApprovalListResponse,
    AgentApprovalResponse,
)
from app.services import (
    agent_approval_service,
    aggregate_lock_service,
    design_agent_service,
)
from app.services.open_geometry_rate_limit import open_geometry_rate_limiter


router = APIRouter()


def _approval_response(approval) -> AgentApprovalResponse:
    resolution = (approval.request_context_json or {}).get("resolution", {})
    if not isinstance(resolution, dict):
        resolution = {}
    return AgentApprovalResponse(
        id=approval.id,
        task_id=approval.task_id,
        turn_id=approval.turn_id,
        approval_type=approval.approval_type,
        status=approval.status,
        request_reason=approval.request_reason,
        reason_code=approval.reason_code,
        request_context=approval.request_context_json or {},
        requested_at=approval.requested_at,
        client_decision_id=approval.client_decision_id,
        decision=approval.decision,
        conclusion=approval.conclusion,
        decided_by_type=approval.decided_by_type,
        decided_by_id=approval.decided_by_id,
        decided_at=approval.decided_at,
        resolution_code=resolution.get("resolution_code"),
        agent_status=resolution.get("agent_status"),
        task_status=resolution.get("task_status"),
        exit_reason=resolution.get("exit_reason"),
        next_action=resolution.get("next_action"),
    )


@router.get("/{task_id}/agent-events", response_model=AgentEventFeedResponse)
def list_agent_events(
    task_id: int,
    x_session_id: SessionIdHeader,
    limit: int = Query(default=50, ge=1, le=100),
    before_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    return design_agent_service.list_public_events(
        db,
        task_id=task.id,
        limit=limit,
        before_id=before_id,
    )


@router.get(
    "/{task_id}/agent-approvals",
    response_model=AgentApprovalListResponse,
)
def list_agent_approvals(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    return AgentApprovalListResponse(
        approvals=[
            _approval_response(approval)
            for approval in agent_approval_service.list_task_approvals(
                db,
                task_id=task.id,
            )
        ]
    )


@router.post(
    "/{task_id}/agent-approvals/{approval_id}/decision",
    response_model=AgentApprovalResponse,
)
def decide_agent_approval(
    task_id: int,
    approval_id: int,
    payload: AgentApprovalDecisionRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    approvals = agent_approval_service.list_task_approvals(
        db,
        task_id=task.id,
    )
    approval = next(
        (item for item in approvals if item.id == approval_id),
        None,
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="审批请求不存在")
    if approval.approval_type == "construction_risk" and payload.decision == "approve":
        raise HTTPException(
            status_code=403,
            detail="高风险施工事项只能由管理员受控复核；其结论不代表施工资质或施工许可",
        )
    try:
        approval = agent_approval_service.decide_approval(
            db,
            task_id=task.id,
            approval_id=approval_id,
            decision=payload.decision,
            conclusion=payload.conclusion.strip(),
            client_decision_id=payload.client_decision_id,
            decided_by_type="session",
            decided_by_id=x_session_id,
        )
        db.commit()
        db.refresh(approval)
        return _approval_response(approval)
    except agent_approval_service.ApprovalNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except agent_approval_service.ApprovalDecisionConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "approval_decision_conflict", "message": str(exc)},
        ) from exc


@router.post(
    "/{task_id}/agent-approvals/{approval_id}/controlled-review",
    response_model=AgentApprovalResponse,
)
def controlled_review_agent_approval(
    task_id: int,
    approval_id: int,
    payload: AgentApprovalDecisionRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    approval = next(
        (
            item
            for item in agent_approval_service.list_task_approvals(
                db,
                task_id=task_id,
            )
            if item.id == approval_id
        ),
        None,
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="审批请求不存在")
    if approval.approval_type != "construction_risk":
        raise HTTPException(
            status_code=409,
            detail="该审批不需要高风险施工受控复核",
        )
    conclusion = (
        f"{payload.conclusion}；该决定仅代表平台受控人工复核，"
        "不代表施工资质、施工许可，也不会恢复自动施工执行。"
    )
    try:
        decided = agent_approval_service.decide_approval(
            db,
            task_id=task_id,
            approval_id=approval_id,
            decision=payload.decision,
            conclusion=conclusion,
            client_decision_id=payload.client_decision_id,
            decided_by_type="admin_controlled_review",
            decided_by_id=f"user:{user.id}",
        )
        db.commit()
        db.refresh(decided)
        return _approval_response(decided)
    except agent_approval_service.ApprovalDecisionConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "approval_decision_conflict", "message": str(exc)},
        ) from exc


@router.put(
    "/{task_id}/custom-furniture-draft",
    response_model=CustomFurnitureDraftResponse,
)
def save_custom_furniture_draft(
    task_id: int,
    payload: CustomFurnitureDraftRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    try:
        require_active_session(db, x_session_id)
        task = aggregate_lock_service.lock_owned_task(
            db,
            session_id=x_session_id,
            task_id=task_id,
        )
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="设计任务不存在或不属于当前会话",
            )
        response = design_agent_service.save_custom_furniture_draft(
            db,
            task=task,
            payload=payload,
        )
        db.commit()
        return response
    except design_agent_service.AgentIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "message": str(exc)},
        ) from exc
    except design_agent_service.AgentTurnInProgress as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except design_agent_service.AgentStateVersionConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "agent_state_conflict",
                "message": str(exc),
                "state_version": exc.state_version,
                "custom_furniture_draft": exc.custom_furniture_draft,
                "scene_ref": exc.scene_ref,
            },
        ) from exc
    except aggregate_lock_service.AggregateLockBusy as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "aggregate_busy", "message": str(exc)},
        ) from exc


@router.post("/{task_id}/agent-turns", response_model=AgentTurnResponse)
def run_agent_turn(
    task_id: int,
    payload: AgentTurnRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    try:
        if design_agent_service.is_open_geometry_turn(payload):
            replay = design_agent_service.replay_turn(
                db,
                task_id=task.id,
                payload=payload,
            )
            if replay is not None:
                return replay
            retry_after = open_geometry_rate_limiter.retry_after(
                db,
                session_id=x_session_id,
                task_id=task.id,
            )
            if retry_after is not None:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "rate_limited",
                        "message": "开放几何 AI 请求过于频繁，请稍后重试",
                    },
                    headers={"Retry-After": str(retry_after)},
                )
        return design_agent_service.run_turn(db, task=task, payload=payload)
    except design_agent_service.AgentSceneNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except design_agent_service.AgentSceneVersionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except design_agent_service.AgentIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "message": str(exc)},
        ) from exc
    except design_agent_service.AgentTurnInProgress as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except design_agent_service.AgentStateVersionConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "agent_state_conflict",
                "message": str(exc),
                "state_version": exc.state_version,
            },
        ) from exc


@router.get("/{task_id}/agent-state", response_model=AgentCheckpointResponse)
def get_agent_state(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    return design_agent_service.get_checkpoint(db, task)
