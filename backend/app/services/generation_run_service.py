"""持久化方案生成任务及 LangGraph 节点事件。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    DesignPlanVersion,
    DesignRevision,
    DesignTask,
    GenerationRun,
    GenerationRunEvent,
    LayoutRun,
)

ACTIVE_STATUSES = ("queued", "running")
NODE_PROGRESS = {
    "prepare_context": 20,
    "generate_plans": 60,
    "calculate_quote": 85,
    "validate_quality": 100,
}


class GenerationRunOwnershipError(RuntimeError):
    """Worker 已失去租约或任务被取消，当前执行不得继续提交。"""


class GenerationCostGuardError(GenerationRunOwnershipError):
    """模型调用被任务成本策略中止。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        estimated_cost_cny: float | None,
        reserved_cost_cny: float,
        cost_limit_cny: float,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.estimated_cost_cny = estimated_cost_cny
        self.reserved_cost_cny = reserved_cost_cny
        self.cost_limit_cny = cost_limit_cny

    @property
    def details(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "estimated_cost_cny": self.estimated_cost_cny,
            "reserved_cost_cny": self.reserved_cost_cny,
            "cost_limit_cny": self.cost_limit_cny,
        }


class GenerationCostConfigurationError(GenerationCostGuardError):
    """缺少可验证的模型成本配置。"""

    def __init__(
        self,
        *,
        reserved_cost_cny: float,
        cost_limit_cny: float,
    ) -> None:
        super().__init__(
            "模型 token 单价未完整配置，已阻止付费调用",
            code="model_cost_unavailable",
            estimated_cost_cny=None,
            reserved_cost_cny=reserved_cost_cny,
            cost_limit_cny=cost_limit_cny,
        )


class GenerationCostLimitExceeded(GenerationCostGuardError):
    """模型调用会超出任务成本上限。"""

    def __init__(
        self,
        *,
        estimated_cost_cny: float,
        reserved_cost_cny: float,
        cost_limit_cny: float,
    ) -> None:
        super().__init__(
            "模型调用将超过单任务成本上限，需人工确认",
            code="task_cost_limit_exceeded",
            estimated_cost_cny=estimated_cost_cny,
            reserved_cost_cny=reserved_cost_cny,
            cost_limit_cny=cost_limit_cny,
        )


class GenerationProviderGuardError(GenerationRunOwnershipError):
    """供应商调用被持久化熔断策略中止。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        provider_key: str,
        circuit_state: str,
        consecutive_failures: int,
        retry_at: datetime | None,
        failure_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider_key = provider_key
        self.circuit_state = circuit_state
        self.consecutive_failures = consecutive_failures
        self.retry_at = retry_at
        self.failure_code = failure_code

    @property
    def details(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "provider_key": self.provider_key,
            "circuit_state": self.circuit_state,
            "consecutive_failures": self.consecutive_failures,
            "retry_at": self.retry_at.isoformat() if self.retry_at else None,
            "failure_code": self.failure_code,
        }


def create_run(
    db: Session,
    *,
    task: DesignTask,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
    request_id: str | None = None,
) -> GenerationRun:
    """创建持久化运行；同一幂等键在终态后也返回原记录。"""
    normalized_key = (idempotency_key or "").strip() or None
    if normalized_key:
        existing = db.scalar(
            select(GenerationRun).where(
                GenerationRun.task_id == task.id,
                GenerationRun.idempotency_key == normalized_key,
            )
        )
        if existing is not None:
            return existing

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
        idempotency_key=normalized_key,
        request_id=request_id,
        max_attempts=max(1, max_attempts),
    )
    db.add(run)
    try:
        db.commit()
        db.refresh(run)
        return run
    except IntegrityError:
        db.rollback()
        if normalized_key:
            existing = db.scalar(
                select(GenerationRun).where(
                    GenerationRun.task_id == task.id,
                    GenerationRun.idempotency_key == normalized_key,
                )
            )
            if existing is not None:
                return existing
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
        raise


def mark_running(db: Session, *, run: GenerationRun) -> None:
    run.status = "running"
    run.current_node = "prepare_context"
    run.started_at = datetime.now(timezone.utc)
    run.error_message = None
    db.commit()


def _clear_worker(run: GenerationRun) -> None:
    run.worker_id = None
    run.lease_expires_at = None
    run.heartbeat_at = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _deadline_reached(run: GenerationRun, *, now: datetime) -> bool:
    return (
        run.execution_deadline_at is not None
        and _as_utc(run.execution_deadline_at) <= _as_utc(now)
    )


def _set_task_state(
    db: Session,
    *,
    run: GenerationRun,
    status: str,
    progress: int,
    error_message: str | None = None,
) -> None:
    task = db.get(DesignTask, run.task_id)
    if task is None:
        return
    task.status = status
    task.progress = progress
    task.error_message = error_message


def _mark_dead_letter(
    db: Session,
    *,
    run: GenerationRun,
    now: datetime,
    error_message: str,
) -> None:
    _clear_worker(run)
    run.status = "dead_letter"
    run.progress = 100
    run.current_node = "dead_letter"
    run.next_retry_at = None
    run.completed_at = now
    run.dead_lettered_at = now
    run.error_message = error_message[:2000]
    _set_task_state(
        db,
        run=run,
        status="failed",
        progress=0,
        error_message=run.error_message,
    )


def recover_expired_runs(
    db: Session,
    *,
    now: datetime | None = None,
    retry_delay_seconds: int = 5,
) -> int:
    """回收租约或硬截止时间过期的运行；取消始终优先。"""
    current = _as_utc(now or datetime.now(timezone.utc))
    expired = db.scalars(
        select(GenerationRun)
        .where(
            GenerationRun.status.in_(("queued", "running")),
            or_(
                and_(
                    GenerationRun.status == "queued",
                    GenerationRun.attempt_count >= GenerationRun.max_attempts,
                ),
                and_(
                    GenerationRun.execution_deadline_at.is_not(None),
                    GenerationRun.execution_deadline_at <= current,
                ),
                and_(
                    GenerationRun.status == "running",
                    GenerationRun.lease_expires_at.is_not(None),
                    GenerationRun.lease_expires_at < current,
                ),
            ),
        )
        .with_for_update(skip_locked=True)
    ).all()
    for run in expired:
        if run.cancel_requested_at is not None:
            _clear_worker(run)
            run.status = "cancelled"
            run.current_node = "cancelled"
            run.completed_at = current
            run.next_retry_at = None
            _set_task_state(db, run=run, status="cancelled", progress=0)
            continue
        if _deadline_reached(run, now=current):
            _mark_dead_letter(
                db,
                run=run,
                now=current,
                error_message="方案生成超过硬执行截止时间",
            )
            continue

        retry_at = current + timedelta(seconds=retry_delay_seconds)
        retry_before_deadline = (
            run.execution_deadline_at is None
            or retry_at < _as_utc(run.execution_deadline_at)
        )
        if run.attempt_count < run.max_attempts and retry_before_deadline:
            _clear_worker(run)
            run.status = "queued"
            run.progress = 0
            run.current_node = "queued"
            run.next_retry_at = retry_at
            run.error_message = "上次 Worker 租约过期，等待重试"
            _set_task_state(db, run=run, status="queued", progress=50)
        else:
            message = (
                "方案生成多次超时"
                if run.attempt_count >= run.max_attempts
                else "方案生成无法在执行截止时间前重试"
            )
            _mark_dead_letter(
                db,
                run=run,
                now=current,
                error_message=message,
            )
    db.commit()
    return len(expired)


def _claim_query(now: datetime, *, run_id: int | None = None):
    query = select(GenerationRun).where(
        GenerationRun.status == "queued",
        GenerationRun.cancel_requested_at.is_(None),
        GenerationRun.attempt_count < GenerationRun.max_attempts,
        (
            GenerationRun.execution_deadline_at.is_(None)
            | (GenerationRun.execution_deadline_at > now)
        ),
        (
            GenerationRun.next_retry_at.is_(None)
            | (GenerationRun.next_retry_at <= now)
        ),
    )
    if run_id is not None:
        query = query.where(GenerationRun.id == run_id)
    return (
        query.order_by(GenerationRun.created_at, GenerationRun.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def claim_next_run(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    execution_timeout_seconds: int = 900,
    now: datetime | None = None,
    run_id: int | None = None,
    retry_delay_seconds: int = 5,
) -> GenerationRun | None:
    """原子认领一个可执行任务，`run_id` 仅供显式开发回退使用。"""
    if execution_timeout_seconds <= 0:
        raise ValueError("方案生成执行超时必须为正数")
    current = _as_utc(now or datetime.now(timezone.utc))
    recover_expired_runs(
        db,
        now=current,
        retry_delay_seconds=retry_delay_seconds,
    )
    run = db.scalars(_claim_query(current, run_id=run_id)).first()
    if run is None:
        db.commit()
        return None
    run.status = "running"
    run.progress = 10
    run.current_node = "prepare_context"
    run.worker_id = worker_id
    run.heartbeat_at = current
    if run.execution_deadline_at is None:
        run.execution_deadline_at = current + timedelta(
            seconds=execution_timeout_seconds
        )
    lease_target = current + timedelta(seconds=lease_seconds)
    if _as_utc(run.execution_deadline_at) < lease_target:
        lease_target = run.execution_deadline_at
    run.lease_expires_at = lease_target
    run.next_retry_at = None
    run.attempt_count += 1
    run.started_at = current
    run.completed_at = None
    run.error_message = None
    _set_task_state(db, run=run, status="generating", progress=60)
    db.commit()
    return run


def _owned_run(
    db: Session,
    *,
    run_id: int,
    worker_id: str,
    worker_attempt: int | None = None,
    now: datetime | None = None,
    lock: bool = False,
) -> GenerationRun | None:
    current = _as_utc(now or datetime.now(timezone.utc))
    query = select(GenerationRun).where(
        GenerationRun.id == run_id,
        GenerationRun.status == "running",
        GenerationRun.worker_id == worker_id,
        GenerationRun.cancel_requested_at.is_(None),
        GenerationRun.lease_expires_at.is_not(None),
        GenerationRun.lease_expires_at >= current,
        (
            GenerationRun.execution_deadline_at.is_(None)
            | (GenerationRun.execution_deadline_at > current)
        ),
    )
    if worker_attempt is not None:
        query = query.where(GenerationRun.attempt_count == worker_attempt)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def assert_worker_ownership(
    db: Session,
    *,
    run_id: int,
    worker_id: str,
    worker_attempt: int,
    now: datetime | None = None,
    lock: bool = True,
) -> GenerationRun | None:
    """返回仍持有有效租约的运行；可锁行以围住最终结果提交。"""
    return _owned_run(
        db,
        run_id=run_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=now,
        lock=lock,
    )


def reserve_model_cost(
    db: Session,
    *,
    run_id: int,
    worker_id: str,
    worker_attempt: int,
    estimated_cost_cny: float | None,
    cost_limit_cny: float,
    now: datetime | None = None,
) -> float:
    """在调用供应商前原子预留任务成本，返回任务累计预留值。"""
    run_task_id = db.scalar(
        select(GenerationRun.task_id).where(GenerationRun.id == run_id)
    )
    if run_task_id is None:
        db.rollback()
        raise GenerationRunOwnershipError("方案生成任务不存在")

    # 同一 DesignTask 是成本账本的并发串行化锁。
    task = db.scalar(
        select(DesignTask)
        .where(DesignTask.id == run_task_id)
        .with_for_update()
    )
    run = _owned_run(
        db,
        run_id=run_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=now,
        lock=True,
    )
    if task is None or run is None:
        db.rollback()
        raise GenerationRunOwnershipError("方案生成任务已失去租约或被取消")

    persisted_limit = db.scalar(
        select(func.min(GenerationRun.cost_limit_cny)).where(
            GenerationRun.task_id == task.id,
            GenerationRun.cost_limit_cny.is_not(None),
        )
    )
    effective_limit = float(
        persisted_limit if persisted_limit is not None else cost_limit_cny
    )
    reserved = float(
        db.scalar(
            select(func.coalesce(func.sum(GenerationRun.cost_reserved_cny), 0.0))
            .where(GenerationRun.task_id == task.id)
        )
        or 0.0
    )
    if (
        not math.isfinite(effective_limit)
        or effective_limit <= 0
        or estimated_cost_cny is None
    ):
        error = GenerationCostConfigurationError(
            reserved_cost_cny=reserved,
            cost_limit_cny=max(0.0, effective_limit),
        )
        db.rollback()
        raise error

    estimated = float(estimated_cost_cny)
    if not math.isfinite(estimated) or estimated < 0:
        error = GenerationCostConfigurationError(
            reserved_cost_cny=reserved,
            cost_limit_cny=effective_limit,
        )
        db.rollback()
        raise error
    if reserved + estimated > effective_limit + 1e-9:
        error = GenerationCostLimitExceeded(
            estimated_cost_cny=estimated,
            reserved_cost_cny=reserved,
            cost_limit_cny=effective_limit,
        )
        db.rollback()
        raise error

    run.cost_limit_cny = effective_limit
    run.cost_reserved_cny = float(run.cost_reserved_cny or 0.0) + estimated
    db.commit()
    return reserved + estimated


def renew_lease(
    db: Session,
    *,
    run_id: int,
    worker_id: str,
    lease_seconds: int,
    worker_attempt: int | None = None,
    now: datetime | None = None,
) -> bool:
    current = _as_utc(now or datetime.now(timezone.utc))
    run = _owned_run(
        db,
        run_id=run_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=current,
    )
    if run is None:
        db.rollback()
        return False
    run.heartbeat_at = current
    lease_target = current + timedelta(seconds=lease_seconds)
    if (
        run.execution_deadline_at is not None
        and _as_utc(run.execution_deadline_at) < lease_target
    ):
        lease_target = run.execution_deadline_at
    run.lease_expires_at = lease_target
    db.commit()
    return True


def record_step(
    db: Session,
    *,
    run: GenerationRun,
    step: dict[str, Any],
    worker_id: str | None = None,
    worker_attempt: int | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> GenerationRunEvent | None:
    if worker_id is not None and _owned_run(
        db,
        run_id=run.id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=now,
    ) is None:
        db.rollback()
        return None
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
    if commit:
        db.commit()
        db.refresh(event)
    else:
        db.flush()
    return event


def mark_completed(
    db: Session,
    *,
    run: GenerationRun | None = None,
    run_id: int | None = None,
    worker_id: str | None = None,
    worker_attempt: int | None = None,
    generator: str,
    now: datetime | None = None,
    commit: bool = True,
) -> bool:
    current = _as_utc(now or datetime.now(timezone.utc))
    if worker_id is not None:
        target_id = run_id or (run.id if run is not None else None)
        if target_id is None:
            return False
        run = _owned_run(
            db,
            run_id=target_id,
            worker_id=worker_id,
            worker_attempt=worker_attempt,
            now=current,
            lock=True,
        )
        if run is None:
            db.rollback()
            return False
    if run is None:
        return False
    run.status = "completed"
    run.progress = 100
    run.current_node = "completed"
    run.generator = generator
    run.completed_at = current
    run.next_retry_at = None
    _clear_worker(run)
    if commit:
        db.commit()
    else:
        db.flush()
    return True


def record_generation_meta(
    db: Session,
    *,
    run: GenerationRun,
    meta: dict[str, Any],
    output_snapshot: dict[str, Any],
    worker_id: str | None = None,
    worker_attempt: int | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> bool:
    """把方案生成的模型 / Prompt / 输入 / 输出 / 用量 / 成本写入 generation_run。"""
    if worker_id is not None and _owned_run(
        db,
        run_id=run.id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=now,
    ) is None:
        db.rollback()
        return False
    run.model = meta.get("model")
    run.prompt_snapshot = meta.get("prompt_snapshot")
    run.prompt_digest = meta.get("prompt_digest")
    run.rules_digest = meta.get("rules_digest")
    run.data_digest = meta.get("data_digest")
    run.input_snapshot = meta.get("input_snapshot")
    run.output_snapshot = output_snapshot
    run.usage_json = meta.get("usage")
    run.cost_cny = meta.get("cost_cny")
    if commit:
        db.commit()
    else:
        db.flush()
    return True


def mark_failed(
    db: Session,
    *,
    run: GenerationRun,
    error_message: str,
    worker_id: str | None = None,
    worker_attempt: int | None = None,
    retryable: bool = False,
    retry_delay_seconds: int = 5,
    now: datetime | None = None,
) -> str:
    current = _as_utc(now or datetime.now(timezone.utc))
    if worker_id is not None:
        owned = _owned_run(
            db,
            run_id=run.id,
            worker_id=worker_id,
            worker_attempt=worker_attempt,
            now=current,
            lock=True,
        )
        if owned is None:
            db.rollback()
            return run.status
        run = owned
    run.error_message = error_message[:2000]
    retry_at = current + timedelta(seconds=retry_delay_seconds)
    retry_before_deadline = (
        run.execution_deadline_at is None
        or retry_at < _as_utc(run.execution_deadline_at)
    )
    if (
        retryable
        and run.attempt_count < run.max_attempts
        and retry_before_deadline
    ):
        _clear_worker(run)
        run.status = "queued"
        run.progress = 0
        run.current_node = "queued"
        run.next_retry_at = retry_at
        run.completed_at = None
        _set_task_state(db, run=run, status="queued", progress=50)
    elif retryable:
        _mark_dead_letter(
            db,
            run=run,
            now=current,
            error_message=run.error_message,
        )
    else:
        _clear_worker(run)
        run.status = "failed"
        run.progress = 100
        run.current_node = "failed"
        run.next_retry_at = None
        run.completed_at = current
        _set_task_state(
            db,
            run=run,
            status="failed",
            progress=0,
            error_message=run.error_message,
        )
    db.commit()
    return run.status


def mark_cost_guard_blocked(
    db: Session,
    *,
    run_id: int,
    worker_id: str,
    worker_attempt: int,
    error: GenerationCostGuardError,
    now: datetime | None = None,
) -> bool:
    """把成本策略拒绝收敛为可查询、不重试的人工接管终态。"""
    current = _as_utc(now or datetime.now(timezone.utc))
    run = _owned_run(
        db,
        run_id=run_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=current,
        lock=True,
    )
    if run is None:
        db.rollback()
        return False

    _clear_worker(run)
    run.status = "cost_limit_exceeded"
    run.progress = 100
    run.current_node = "cost_guard"
    run.error_message = str(error)[:2000]
    run.cost_limit_cny = error.cost_limit_cny
    run.next_retry_at = None
    run.completed_at = current
    db.add(
        GenerationRunEvent(
            run_id=run.id,
            node="cost_guard",
            status="failed",
            progress=100,
            source="deterministic",
            detail_json=error.details,
        )
    )
    _set_task_state(
        db,
        run=run,
        status="needs_human",
        progress=0,
        error_message=run.error_message,
    )
    db.commit()
    return True


def mark_provider_guard_blocked(
    db: Session,
    *,
    run_id: int,
    worker_id: str,
    worker_attempt: int,
    error: GenerationProviderGuardError,
    now: datetime | None = None,
) -> bool:
    """把供应商故障收敛为显式、不重试的人工接管终态。"""
    current = _as_utc(now or datetime.now(timezone.utc))
    run = _owned_run(
        db,
        run_id=run_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=current,
        lock=True,
    )
    if run is None:
        db.rollback()
        return False

    _clear_worker(run)
    run.status = "provider_unavailable"
    run.progress = 100
    run.current_node = "provider_circuit"
    run.error_message = str(error)[:2000]
    run.next_retry_at = None
    run.completed_at = current
    db.add(
        GenerationRunEvent(
            run_id=run.id,
            node="provider_circuit",
            status="failed",
            progress=100,
            source="deterministic",
            detail_json=error.details,
        )
    )
    _set_task_state(
        db,
        run=run,
        status="needs_human",
        progress=0,
        error_message=run.error_message,
    )
    db.commit()
    return True


def request_cancel(
    db: Session,
    *,
    run: GenerationRun,
    now: datetime | None = None,
) -> str:
    current = _as_utc(now or datetime.now(timezone.utc))
    locked_run = db.scalar(
        select(GenerationRun)
        .where(GenerationRun.id == run.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked_run is None:
        db.rollback()
        return "failed"
    run = locked_run
    if run.status in {
        "completed",
        "failed",
        "dead_letter",
        "cancelled",
        "cost_limit_exceeded",
        "provider_unavailable",
    }:
        db.commit()
        return run.status
    run.cancel_requested_at = run.cancel_requested_at or current
    if run.status == "queued":
        run.status = "cancelled"
        run.current_node = "cancelled"
        run.completed_at = current
        run.next_retry_at = None
        _clear_worker(run)
        _set_task_state(db, run=run, status="cancelled", progress=0)
    db.commit()
    return run.status


def mark_cancelled_by_worker(
    db: Session,
    *,
    run_id: int,
    worker_id: str,
    worker_attempt: int,
    now: datetime | None = None,
) -> bool:
    current = _as_utc(now or datetime.now(timezone.utc))
    run = db.scalar(
        select(GenerationRun)
        .where(
            GenerationRun.id == run_id,
            GenerationRun.status == "running",
            GenerationRun.worker_id == worker_id,
            GenerationRun.attempt_count == worker_attempt,
            GenerationRun.cancel_requested_at.is_not(None),
        )
        .with_for_update()
    )
    if run is None:
        db.rollback()
        return False
    run.status = "cancelled"
    run.progress = 100
    run.current_node = "cancelled"
    run.completed_at = current
    run.next_retry_at = None
    _clear_worker(run)
    _set_task_state(db, run=run, status="cancelled", progress=0)
    db.commit()
    return True


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


def layout_scores_for_task(db: Session, *, task_id: int) -> dict[str, Any]:
    """聚合某任务所有 layout_runs 的评分，供「布局评分」量化与失败反推。"""
    rows = db.scalars(
        select(LayoutRun)
        .join(DesignPlanVersion, LayoutRun.plan_version_id == DesignPlanVersion.id)
        .join(DesignRevision, DesignPlanVersion.revision_id == DesignRevision.id)
        .where(DesignRevision.task_id == task_id)
    ).all()
    if not rows:
        return {"count": 0, "avg_score": None, "pass_rate": None, "issues": {}}

    scores = [run.best_score for run in rows]
    valid_count = sum(1 for run in rows if run.best_valid)
    issues: dict[str, int] = {}
    for run in rows:
        for code in run.issue_codes or []:
            issues[str(code)] = issues.get(str(code), 0) + 1
    return {
        "count": len(rows),
        "avg_score": round(sum(scores) / len(scores), 2),
        "pass_rate": round(valid_count / len(rows), 4),
        "issues": issues,
    }
