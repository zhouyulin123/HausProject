"""统一任务执行时间线：只保存稳定码，不复制敏感业务输入。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.request_context import current_request_id
from app.db.models import (
    ModelCallCostAccount,
    ModelCallLedger,
    TaskExecutionEvent,
)


TimelineSource = Literal[
    "agent",
    "requirement",
    "vision",
    "profile",
    "generation",
    "effect",
    "blender",
]
BillingStatus = Literal["metered", "not_billable", "unknown"]

EVENT_SUMMARIES = {
    "agent.home_design.completed": "整屋设计建议已检查，尚未应用",
    "agent.home_design.failed": "整屋设计建议未能完成",
    "agent.turn.completed": "智能体本轮已完成",
    "agent.turn.failed": "智能体本轮失败",
    "agent.turn.waiting_user": "智能体等待用户确认",
    "agent.approval.decided": "人工审批已作出决定",
    "agent.turn.recovered": "智能体执行已恢复",
    "agent.turn.conflict": "智能体状态提交冲突",
    "agent.open_geometry.completed": "开放几何家具修改已完成",
    "agent.open_geometry.failed": "开放几何家具修改失败",
    "requirement.completed": "AI 需求解析已完成",
    "requirement.fallback": "需求解析已降级为确定性规则",
    "vision.completed": "AI 空间识别已完成",
    "vision.fallback": "空间识别已降级为占位结果",
    "profile.completed": "用户长期画像已更新",
    "profile.failed": "用户长期画像更新失败",
    "profile.skipped": "用户长期画像更新已跳过",
    "generation.queued": "方案生成已排队",
    "generation.claimed": "方案生成已由 Worker 接管",
    "generation.retry_scheduled": "方案生成已安排重试",
    "generation.completed": "方案生成已完成",
    "generation.failed": "方案生成失败",
    "generation.cancelled": "方案生成已取消",
    "generation.dead_letter": "方案生成已进入死信",
    "effect.queued": "效果图生成已排队",
    "effect.claimed": "效果图生成已由 Worker 接管",
    "effect.retry_scheduled": "效果图生成已安排重试",
    "effect.completed": "效果图生成已完成",
    "effect.failed": "效果图生成失败",
    "effect.provider_unavailable": "效果图供应商暂不可用",
    "effect.cancelled": "效果图生成已取消",
    "effect.dead_letter": "效果图生成已进入死信",
    "blender.queued": "3D 渲染已排队",
    "blender.claimed": "3D 渲染已由 Worker 接管",
    "blender.retry_scheduled": "3D 渲染已安排重试",
    "blender.completed": "3D 渲染已完成",
    "blender.failed": "3D 渲染失败",
    "blender.cancelled": "3D 渲染已取消",
    "blender.dead_letter": "3D 渲染已进入死信",
}


@dataclass(frozen=True)
class TaskCostSummary:
    known_cost_cny: float | None
    has_unknown_cost: bool
    unknown_cost_event_count: int
    model_cost_limit_cny: float | None = None
    model_cost_allocated_cny: float | None = None
    model_actual_cost_cny: float | None = None
    model_unknown_cost_call_count: int = 0
    model_call_count: int = 0


def append_event(
    db: Session,
    *,
    task_id: int,
    source_type: TimelineSource,
    source_id: int,
    attempt: int | None,
    event_code: str,
    billing_status: BillingStatus,
    cost_cny: float | None,
    event_key: str,
    occurred_at: datetime | None = None,
) -> TaskExecutionEvent:
    if event_code not in EVENT_SUMMARIES or not event_code.startswith(
        f"{source_type}."
    ):
        raise ValueError("任务时间线事件码不受支持")
    if billing_status == "metered":
        if cost_cny is None or cost_cny < 0:
            raise ValueError("metered 事件必须提供非负成本")
    elif cost_cny is not None:
        raise ValueError("非 metered 事件不得伪造成本")
    existing = db.scalar(
        select(TaskExecutionEvent).where(TaskExecutionEvent.event_key == event_key)
    )
    if existing is not None:
        expected = (
            task_id,
            source_type,
            source_id,
            attempt,
            event_code,
            billing_status,
            cost_cny,
        )
        actual = (
            existing.task_id,
            existing.source_type,
            existing.source_id,
            existing.attempt,
            existing.event_code,
            existing.billing_status,
            existing.cost_cny,
        )
        if actual != expected:
            raise ValueError("任务时间线 event_key 已绑定不同事件")
        return existing
    event = TaskExecutionEvent(
        request_id=current_request_id(),
        task_id=task_id,
        source_type=source_type,
        source_id=source_id,
        attempt=attempt,
        event_code=event_code,
        billing_status=billing_status,
        cost_cny=cost_cny,
        event_key=event_key,
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )
    db.add(event)
    db.flush()
    return event


def get_event_by_key(db: Session, *, event_key: str) -> TaskExecutionEvent | None:
    return db.scalar(
        select(TaskExecutionEvent).where(TaskExecutionEvent.event_key == event_key)
    )


def billing_for_model_call(
    *,
    attempted: bool,
    usage: dict[str, int] | None,
    input_price_per_mtok: float | None,
    output_price_per_mtok: float | None,
) -> tuple[BillingStatus, float | None]:
    if not attempted:
        return "not_billable", None
    from app.services.llm_service import estimate_cost_cny

    cost = estimate_cost_cny(
        usage,
        input_price_per_mtok,
        output_price_per_mtok,
    )
    if cost is None:
        return "unknown", None
    return "metered", cost


def project_visual_analysis(
    db: Session,
    *,
    task_id: int,
    image: object,
) -> TaskExecutionEvent:
    source = getattr(image, "original_prediction_source", None)
    event_code = "vision.completed" if source == "vl" else "vision.fallback"
    return append_event(
        db,
        task_id=task_id,
        source_type="vision",
        source_id=int(getattr(image, "id")),
        attempt=1 if getattr(image, "analysis_model_call_attempted", False) else None,
        event_code=event_code,
        billing_status=getattr(image, "analysis_billing_status", "not_billable"),
        cost_cny=getattr(image, "analysis_cost_cny", None),
        event_key=f"vision:{int(getattr(image, 'id'))}:analysis",
        occurred_at=getattr(image, "created_at", None),
    )


def record_lifecycle_event(
    db: Session,
    *,
    task_id: int,
    source_type: TimelineSource,
    source_id: int,
    state: str,
    attempt: int | None = None,
    generation_cost_cny: float | None = None,
    model_cost_cny: float | None = None,
    occurred_at: datetime | None = None,
) -> TaskExecutionEvent:
    """Append a normalized lifecycle event inside the caller's transaction."""
    event_code = (
        f"agent.turn.{state}"
        if source_type == "agent"
        else f"{source_type}.{state}"
    )
    billing_status: BillingStatus = "not_billable"
    cost_cny: float | None = None

    is_terminal = state in {"completed", "failed", "cancelled", "dead_letter"}
    if source_type == "agent" and (attempt or 0) > 0:
        if model_cost_cny is not None:
            billing_status = "metered"
            cost_cny = model_cost_cny
        else:
            billing_status = "unknown"
    elif source_type == "generation" and is_terminal:
        if generation_cost_cny is not None:
            billing_status = "metered"
            cost_cny = generation_cost_cny
        elif (attempt or 0) > 0:
            billing_status = "unknown"
    elif source_type in {"effect", "blender"} and (
        state
        in {
            "retry_scheduled",
            "completed",
            "failed",
            "provider_unavailable",
            "dead_letter",
        }
        or (state == "cancelled" and (attempt or 0) > 0)
    ):
        billing_status = "unknown"

    normalized_attempt = attempt or 0
    return append_event(
        db,
        task_id=task_id,
        source_type=source_type,
        source_id=source_id,
        attempt=attempt,
        event_code=event_code,
        billing_status=billing_status,
        cost_cny=cost_cny,
        event_key=f"{source_type}:{source_id}:a{normalized_attempt}:{state}",
        occurred_at=occurred_at,
    )


def list_events(
    db: Session,
    *,
    task_id: int,
    after_id: int | None,
    limit: int,
    before_id: int | None = None,
) -> tuple[list[TaskExecutionEvent], int | None]:
    statement = select(TaskExecutionEvent).where(
        TaskExecutionEvent.task_id == task_id
    )
    if after_id is not None:
        statement = statement.where(TaskExecutionEvent.id > after_id)
    elif before_id is not None:
        statement = statement.where(TaskExecutionEvent.id < before_id)
    forward = after_id is not None
    rows = list(
        db.scalars(
            statement.order_by(
                TaskExecutionEvent.id
                if forward
                else TaskExecutionEvent.id.desc()
            ).limit(limit + 1)
        )
    )
    has_more = len(rows) > limit
    events = rows[:limit]
    if not forward:
        events.reverse()
    if not has_more or not events:
        return events, None
    return events, events[-1].id if forward else events[0].id


def cost_summary(db: Session, *, task_id: int) -> TaskCostSummary:
    account = db.scalar(
        select(ModelCallCostAccount).where(
            ModelCallCostAccount.scope_kind == "task",
            ModelCallCostAccount.scope_id == str(task_id),
        )
    )
    model_call_count = 0
    model_metered_count = 0
    if account is not None:
        model_call_count = int(
            db.scalar(
                select(func.count(ModelCallLedger.id)).where(
                    ModelCallLedger.account_id == account.id,
                )
            )
            or 0
        )
        model_metered_count = int(
            db.scalar(
                select(func.count(ModelCallLedger.id)).where(
                    ModelCallLedger.account_id == account.id,
                    ModelCallLedger.billing_status == "metered",
                )
            )
            or 0
        )
    known_cost = db.scalar(
        select(func.sum(TaskExecutionEvent.cost_cny)).where(
            TaskExecutionEvent.task_id == task_id,
            TaskExecutionEvent.billing_status == "metered",
        )
    )
    unknown_count = int(
        db.scalar(
            select(func.count(TaskExecutionEvent.id)).where(
                TaskExecutionEvent.task_id == task_id,
                TaskExecutionEvent.billing_status == "unknown",
            )
        )
        or 0
    )
    return TaskCostSummary(
        known_cost_cny=float(known_cost) if known_cost is not None else None,
        has_unknown_cost=unknown_count > 0,
        unknown_cost_event_count=unknown_count,
        model_cost_limit_cny=(
            float(account.cost_limit_cny) if account is not None else None
        ),
        model_cost_allocated_cny=(
            float(account.allocated_cost_cny or 0.0)
            if account is not None
            else None
        ),
        model_actual_cost_cny=(
            float(account.actual_cost_cny or 0.0)
            if account is not None and model_metered_count > 0
            else None
        ),
        model_unknown_cost_call_count=(
            int(account.unknown_cost_call_count or 0)
            if account is not None
            else 0
        ),
        model_call_count=model_call_count,
    )


def safe_summary(event_code: str) -> str:
    return EVENT_SUMMARIES[event_code]
