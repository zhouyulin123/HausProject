"""Agent 人工审批请求的分类、幂等创建与原子决定。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AgentApproval, DesignAgentTurn, DesignTask


class ApprovalNotFound(ValueError):
    pass


class ApprovalDecisionConflict(ValueError):
    pass


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
            return existing
        raise ApprovalDecisionConflict("审批已经作出决定，禁止覆盖")

    status = "approved" if decision == "approve" else "rejected"
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
                    decided_at=decided_at or datetime.now(timezone.utc),
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
    return approval
