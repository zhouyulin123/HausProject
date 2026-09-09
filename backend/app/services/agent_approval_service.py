"""Agent 人工审批请求的分类、幂等创建与原子决定。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AgentApproval, DesignAgentTurn, DesignTask
from app.services import task_timeline_service


class ApprovalNotFound(ValueError):
    pass


class ApprovalDecisionConflict(ValueError):
    pass


def _resolution_contract(
    *,
    approval_type: str,
    decision: str,
) -> dict[str, Any]:
    """Return the terminal outcome for a human decision without resuming the agent."""
    if approval_type == "construction_risk":
        return {
            "agent_status": "waiting_user",
            "task_status": "waiting_input",
            "resolution_code": "safety_user_revision_required",
            "exit_reason": "safety_user_revision_required",
            "next_action": "revise_user_request",
            "pending_questions": [
                {
                    "field": "construction_risk_revision",
                    "prompt": "请修改或移除高风险施工请求后重新提交。",
                    "reason": "safety_review_requires_user_revision",
                }
            ],
        }

    if decision == "approve":
        return {
            "agent_status": "waiting_user",
            "task_status": "waiting_input",
            "resolution_code": "approval_recorded",
            "exit_reason": "approval_recorded",
            "next_action": "new_agent_turn",
            "pending_questions": [],
        }

    if approval_type == "quote_review":
        resolution_code = "quote_revision_required"
        prompt = "请补充可复算的报价依据后重新提交。"
        reason = "quote_review_rejected"
    else:
        resolution_code = "quality_revision_required"
        prompt = "请修改房间布局或约束后重新提交。"
        reason = "quality_gate_rejected"
    return {
        "agent_status": "waiting_user",
        "task_status": "waiting_input",
        "resolution_code": resolution_code,
        "exit_reason": resolution_code,
        "next_action": "revise_user_request",
        "pending_questions": [
            {
                "field": (
                    "quote_review_revision"
                    if approval_type == "quote_review"
                    else "quality_gate_revision"
                ),
                "prompt": prompt,
                "reason": reason,
            }
        ],
    }


def _apply_decision_resolution(
    db: Session,
    *,
    approval: AgentApproval,
) -> None:
    """Atomically converge the task aggregate after the approval row is decided."""
    task = db.scalar(
        select(DesignTask)
        .where(DesignTask.id == approval.task_id)
        .with_for_update()
    )
    turn = db.scalar(
        select(DesignAgentTurn)
        .where(
            DesignAgentTurn.id == approval.turn_id,
            DesignAgentTurn.task_id == approval.task_id,
        )
    )
    if task is None or turn is None:
        raise ApprovalNotFound("审批关联的 Agent 任务不存在")

    resolution = _resolution_contract(
        approval_type=approval.approval_type,
        decision=str(approval.decision or ""),
    )
    decided_at = approval.decided_at or datetime.now(timezone.utc)
    checkpoint = deepcopy(task.agent_state_json or {})
    checkpoint.update(
        {
            "status": resolution["agent_status"],
            "current_node": "approval_decision",
            "approval_required": False,
            "exit_reason": resolution["exit_reason"],
            "pending_questions": deepcopy(resolution["pending_questions"]),
            "step_count": 0,
            "retry_count": 0,
            "hard_errors": [],
            "approval_resolution": {
                "approval_id": approval.id,
                "approval_type": approval.approval_type,
                "decision": approval.decision,
                "resolution_code": resolution["resolution_code"],
                "next_action": resolution["next_action"],
                "decided_at": decided_at.isoformat(),
            },
        }
    )
    next_state_version = int(task.agent_state_version or 0) + 1
    checkpoint["state_version"] = next_state_version
    task.agent_state_json = checkpoint
    task.agent_state_version = next_state_version
    task.status = resolution["task_status"]

    context = deepcopy(approval.request_context_json or {})
    context["resolution"] = {
        **resolution,
        "approval_id": approval.id,
        "approval_type": approval.approval_type,
        "decision": approval.decision,
        "decided_at": decided_at.isoformat(),
    }
    context["resolution"].pop("pending_questions", None)
    approval.request_context_json = context
    task_timeline_service.append_event(
        db,
        task_id=task.id,
        source_type="agent",
        source_id=turn.id,
        attempt=None,
        event_code="agent.approval.decided",
        billing_status="not_billable",
        cost_cny=None,
        event_key=f"agent-approval:{approval.id}:decided",
        occurred_at=decided_at,
    )
    db.flush()


def _handoff_contract(state: dict[str, Any]) -> tuple[str, str, str]:
    exit_reason = str(state.get("exit_reason") or "quality_gate_failed")
    errors = [
        str(code).strip()
        for code in (state.get("hard_errors") or [])
        if str(code).strip()
    ]
    result = state.get("result")
    quote_preview = result.get("quote_preview") if isinstance(result, dict) else None
    quote_reason = (
        quote_preview.get("reason_code")
        if isinstance(quote_preview, dict)
        else None
    )
    reason_code = errors[0] if errors else str(quote_reason or exit_reason)
    if exit_reason == "safety_blocked":
        return (
            "construction_risk",
            reason_code,
            "高风险施工事项需要具备资质的专业人员审核",
        )
    if exit_reason == "approval_required" or "quote_rule_missing" in errors:
        return (
            "quote_review",
            reason_code,
            "当前没有唯一可复算报价，需要人工确认价格依据",
        )
    return (
        "quality_gate",
        reason_code,
        "本轮未通过确定性质量门禁，需要人工复核",
    )


def ensure_for_agent_handoff(
    db: Session,
    *,
    task: DesignTask,
    turn: DesignAgentTurn,
    state: dict[str, Any],
) -> AgentApproval | None:
    if state.get("status") != "needs_human":
        return None
    approval_type, reason_code, request_reason = _handoff_contract(state)
    existing = db.scalar(
        select(AgentApproval).where(
            AgentApproval.turn_id == turn.id,
            AgentApproval.approval_type == approval_type,
        )
    )
    if existing is not None:
        return existing
    approval = AgentApproval(
        task_id=task.id,
        turn_id=turn.id,
        approval_type=approval_type,
        status="pending",
        request_reason=request_reason,
        reason_code=reason_code,
        request_context_json={
            "exit_reason": state.get("exit_reason"),
            "current_node": state.get("current_node"),
            "hard_errors": list(state.get("hard_errors") or []),
        },
    )
    db.add(approval)
    db.flush()
    return approval


def list_task_approvals(db: Session, *, task_id: int) -> list[AgentApproval]:
    return list(
        db.scalars(
            select(AgentApproval)
            .where(AgentApproval.task_id == task_id)
            .order_by(AgentApproval.requested_at.desc(), AgentApproval.id.desc())
        ).all()
    )


def _same_decision(
    approval: AgentApproval,
    *,
    client_decision_id: str,
    decision: str,
    conclusion: str,
) -> bool:
    return (
        approval.client_decision_id == client_decision_id
        and approval.decision == decision
        and (approval.conclusion or "") == conclusion
    )


def decide_approval(
    db: Session,
    *,
    task_id: int,
    approval_id: int,
    decision: str,
    conclusion: str,
    client_decision_id: str,
    decided_by_type: str,
    decided_by_id: str,
    decided_at: datetime | None = None,
) -> AgentApproval:
    existing = db.scalar(
        select(AgentApproval).where(
            AgentApproval.id == approval_id,
            AgentApproval.task_id == task_id,
        )
    )
    if existing is None:
        raise ApprovalNotFound("审批请求不存在")
    reused_key = db.scalar(
        select(AgentApproval).where(
            AgentApproval.task_id == task_id,
            AgentApproval.client_decision_id == client_decision_id,
        )
    )
    if reused_key is not None and reused_key.id != approval_id:
        raise ApprovalDecisionConflict("审批决定幂等键已用于其他审批")
    if existing.status != "pending":
        if _same_decision(
            existing,
            client_decision_id=client_decision_id,
            decision=decision,
            conclusion=conclusion,
        ):
            if not isinstance(existing.request_context_json, dict) or not isinstance(
                existing.request_context_json.get("resolution"), dict
            ):
                _apply_decision_resolution(db, approval=existing)
            return existing
        raise ApprovalDecisionConflict("审批已经作出决定，禁止覆盖")

    status = "approved" if decision == "approve" else "rejected"
    effective_decided_at = decided_at or datetime.now(timezone.utc)
    try:
        with db.begin_nested():
            result = db.execute(
                update(AgentApproval)
                .where(
                    AgentApproval.id == approval_id,
                    AgentApproval.task_id == task_id,
                    AgentApproval.status == "pending",
                )
                .values(
                    status=status,
                    client_decision_id=client_decision_id,
                    decision=decision,
                    conclusion=conclusion,
                    decided_by_type=decided_by_type,
                    decided_by_id=decided_by_id,
                    decided_at=effective_decided_at,
                )
                .execution_options(synchronize_session=False)
            )
    except IntegrityError as exc:
        raise ApprovalDecisionConflict(
            "审批决定幂等键已由另一请求占用"
        ) from exc
    if result.rowcount != 1:
        db.expire_all()
        winner = db.scalar(
            select(AgentApproval).where(
                AgentApproval.id == approval_id,
                AgentApproval.task_id == task_id,
            )
        )
        if winner is not None and _same_decision(
            winner,
            client_decision_id=client_decision_id,
            decision=decision,
            conclusion=conclusion,
        ):
            if not isinstance(winner.request_context_json, dict) or not isinstance(
                winner.request_context_json.get("resolution"), dict
            ):
                _apply_decision_resolution(db, approval=winner)
            return winner
        raise ApprovalDecisionConflict("审批已由另一请求决定")
    db.flush()
    db.expire_all()
    approval = db.scalar(
        select(AgentApproval).where(
            AgentApproval.id == approval_id,
            AgentApproval.task_id == task_id,
        )
    )
    if approval is None:
        raise ApprovalNotFound("审批请求不存在")
    _apply_decision_resolution(db, approval=approval)
    db.expire_all()
    approval = db.scalar(
        select(AgentApproval).where(
            AgentApproval.id == approval_id,
            AgentApproval.task_id == task_id,
        )
    )
    if approval is None:
        raise ApprovalNotFound("审批请求不存在")
    return approval
