"""持久化方案生成任务及 LangGraph 节点事件。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import DesignTask, GenerationRun, GenerationRunEvent

ACTIVE_STATUSES = ("queued", "running")
NODE_PROGRESS = {
    "prepare_context": 20,
    "generate_plans": 60,
    "calculate_quote": 85,
    "validate_quality": 100,
}


def create_run(db: Session, *, task: DesignTask) -> GenerationRun:
    """创建新尝试；同一任务已有活动运行时直接复用，避免重复付费调用。"""
    active = db.scalars(
        select(GenerationRun)
        .where(
            GenerationRun.task_id == task.id,
            GenerationRun.status.in_(ACTIVE_STATUSES),
        )
        .order_by(GenerationRun.attempt.desc())
    ).first()
    if active is not None:
        return active

    latest_attempt = db.scalar(
        select(func.max(GenerationRun.attempt)).where(
            GenerationRun.task_id == task.id
        )
    )
    run = GenerationRun(
        task_id=task.id,
        attempt=(latest_attempt or 0) + 1,
        status="queued",
        progress=0,
        current_node="queued",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def mark_running(db: Session, *, run: GenerationRun) -> None:
    run.status = "running"
    run.current_node = "prepare_context"
    run.started_at = datetime.now(timezone.utc)
    run.error_message = None
    db.commit()


def record_step(
    db: Session,
    *,
    run: GenerationRun,
    step: dict[str, Any],
) -> GenerationRunEvent:
    node = str(step["node"])
    progress = NODE_PROGRESS.get(node, run.progress)
    known_fields = {
        "node",
        "status",
        "duration_ms",
        "source",
    }
    details = {
        key: value
        for key, value in step.items()
        if key not in known_fields
    }
    event = GenerationRunEvent(
        run_id=run.id,
        node=node,
        status=str(step.get("status") or "completed"),
        progress=progress,
        source=step.get("source"),
        duration_ms=step.get("duration_ms"),
        detail_json=details or None,
    )
    run.current_node = node
    run.progress = progress
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def mark_completed(
    db: Session,
    *,
    run: GenerationRun,
    generator: str,
) -> None:
    run.status = "completed"
    run.progress = 100
    run.current_node = "completed"
    run.generator = generator
    run.completed_at = datetime.now(timezone.utc)
    db.commit()


def mark_failed(
    db: Session,
    *,
    run: GenerationRun,
    error_message: str,
) -> None:
    run.status = "failed"
    run.current_node = "failed"
    run.error_message = error_message[:2000]
    run.completed_at = datetime.now(timezone.utc)
    db.commit()


def get_latest_run(
    db: Session,
    *,
    task_id: int,
) -> GenerationRun | None:
    return db.scalars(
        select(GenerationRun)
        .options(selectinload(GenerationRun.events))
        .where(GenerationRun.task_id == task_id)
        .order_by(GenerationRun.attempt.desc())
    ).first()
