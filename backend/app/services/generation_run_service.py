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
    EvaluationRunBinding,
    LayoutRun,
)
from app.services import (
    evaluation_binding_service,
    generation_output_service,
    task_timeline_service,
)
from app.services.evaluation_binding_service import EvaluationBindingSpec

ACTIVE_STATUSES = ("queued", "running")
NODE_PROGRESS = {
    "prepare_context": 20,
    "generate_plans": 60,
    "calculate_quote": 85,
    "validate_quality": 100,
    "budget_replan": 100,
    "budget_guard": 100,
}
_GENERATION_STATIC_META_FIELDS = (
    "model",
    "prompt_snapshot",
    "prompt_digest",
    "rules_digest",
    "data_digest",
    "provenance_schema_version",
)
_GENERATION_INITIAL_INPUT_FIELDS = ("input_snapshot", "input_digest")


class GenerationRunOwnershipError(RuntimeError):
    """Worker 已失去租约或任务被取消，当前执行不得继续提交。"""


class GenerationIdempotencyConflict(RuntimeError):
    """同一幂等键被用于不同的生成输入。"""


class GenerationBudgetReplanExhausted(RuntimeError):
    """确定性报价连续超预算，已耗尽同一运行内的重规划次数。"""

    reason_code = "budget_replan_exhausted"

    def __init__(
        self,
        *,
        budget_max: int | float,
        plan_totals: list[int],
        retry_count: int,
        max_retries: int,
    ) -> None:
        super().__init__(
            f"确定性报价连续超出已确认预算 {budget_max} 元，需人工处理"
        )
        self.budget_max = budget_max
        self.plan_totals = plan_totals
        self.retry_count = retry_count
        self.max_retries = max_retries

    @property
    def details(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "hard_error_code": "budget_exceeded",
            "budget_max": self.budget_max,
            "plan_totals": self.plan_totals,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }


class GenerationMetadataDriftError(
    generation_output_service.GenerationOutputValidationError
):
    """同一生成运行的重规划轮次发生静态制品版本漂移。"""


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
    request_digest: str | None = None,
    request_contract: dict[str, Any] | None = None,
    evaluation_binding: EvaluationBindingSpec | None = None,
    commit: bool = True,
) -> GenerationRun:
    """创建持久化运行；同一幂等键在终态后也返回原记录。"""
    normalized_key = (idempotency_key or "").strip() or None
    is_evaluation = evaluation_binding_service.is_evaluation_idempotency_key(
        normalized_key
    )
    if is_evaluation != (evaluation_binding is not None):
        raise evaluation_binding_service.EvaluationBindingError(
            "评测运行必须在创建事务内提供持久化案例绑定"
        )
    if evaluation_binding is not None:
        expected_key = evaluation_binding_service.evaluation_idempotency_key(
            evaluation_binding
        )
        if normalized_key != expected_key:
            raise evaluation_binding_service.EvaluationBindingError(
                "评测案例绑定与幂等键不一致"
            )
        evaluation_binding_service.validate_spec_for_task(
            db,
            task=task,
            spec=evaluation_binding,
        )
    if normalized_key:
        existing = db.scalar(
            select(GenerationRun).where(
                GenerationRun.task_id == task.id,
                GenerationRun.idempotency_key == normalized_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise GenerationIdempotencyConflict(
                    "Idempotency-Key 已用于不同的任务输入或版本"
                )
            if evaluation_binding is not None:
                evaluation_binding_service.validate_persisted_binding(
                    db,
                    run=existing,
                )
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
        if evaluation_binding is not None:
            raise evaluation_binding_service.EvaluationBindingError(
                "任务已有其他活动运行，不能创建评测绑定"
            )
        if normalized_key and active.request_digest != request_digest:
            raise GenerationIdempotencyConflict(
                "任务已有不同输入的生成操作正在执行"
            )
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
        request_digest=request_digest,
        request_id=request_id,
        max_attempts=max(1, max_attempts),
        generator=("llm" if evaluation_binding is not None else None),
        model=(evaluation_binding.model if evaluation_binding is not None else None),
        prompt_snapshot=(
            evaluation_binding.prompt_snapshot
            if evaluation_binding is not None
            else None
        ),
        prompt_digest=(
            evaluation_binding.prompt_digest if evaluation_binding is not None else None
        ),
        rules_digest=(
            evaluation_binding.rules_digest if evaluation_binding is not None else None
        ),
        data_digest=(
            evaluation_binding.data_digest if evaluation_binding is not None else None
        ),
        input_snapshot=(
            evaluation_binding.input_snapshot if evaluation_binding is not None else None
        ),
        input_digest=(
            evaluation_binding.input_digest if evaluation_binding is not None else None
        ),
        provenance_schema_version=(
            evaluation_binding.provenance_schema_version
            if evaluation_binding is not None
            else None
        ),
    )
    db.add(run)
    try:
        db.flush()
        if request_contract is not None:
            from app.services import generation_request_service

            frozen_digest = generation_request_service.digest_request_contract(
                request_contract
            )
            if request_digest != frozen_digest:
                raise ValueError("生成请求契约与请求摘要不一致")
            db.add(
                GenerationRunEvent(
                    run_id=run.id,
                    node="request_contract",
                    status="completed",
                    progress=0,
                    source="deterministic",
                    detail_json={
                        "schema_version": request_contract.get("schema_version"),
                        "request_digest": frozen_digest,
                        "catalog_fingerprint": request_contract.get(
                            "catalog_fingerprint"
                        ),
                    },
                )
            )
        task_timeline_service.record_lifecycle_event(
            db,
            task_id=task.id,
            source_type="generation",
            source_id=run.id,
            state="queued",
            attempt=0,
        )
        if evaluation_binding is not None:
            db.add(
                EvaluationRunBinding(
                    generation_run_id=run.id,
                    task_id=task.id,
                    case_fingerprint=evaluation_binding.case_fingerprint,
                    asset_digest=evaluation_binding.asset_digest,
                    task_input_digest=evaluation_binding.task_input_digest,
                    dataset_split=evaluation_binding.dataset_split,
                    model=evaluation_binding.model,
                    prompt_digest=evaluation_binding.prompt_digest,
                    rules_digest=evaluation_binding.rules_digest,
                    data_digest=evaluation_binding.data_digest,
                    input_digest=evaluation_binding.input_digest,
                    provenance_schema_version=(
                        evaluation_binding.provenance_schema_version
                    ),
                    requirement_parse_result_id=(
                        evaluation_binding.requirement_parse_result_id
                    ),
                    uploaded_image_id=evaluation_binding.uploaded_image_id,
                    prediction_snapshot_json=evaluation_binding.prediction_snapshot,
                    prediction_digest=evaluation_binding.prediction_digest,
                )
            )
            db.flush()
        if commit:
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
                if existing.request_digest != request_digest:
                    raise GenerationIdempotencyConflict(
                        "Idempotency-Key 已用于不同的任务输入或版本"
                    )
                if evaluation_binding is not None:
                    evaluation_binding_service.validate_persisted_binding(
                        db,
                        run=existing,
                    )
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
            if evaluation_binding is not None:
                raise evaluation_binding_service.EvaluationBindingError(
                    "任务已有其他活动运行，不能返回未绑定的评测运行"
                )
            if normalized_key and active.request_digest != request_digest:
                raise GenerationIdempotencyConflict(
                    "任务已有不同输入的生成操作正在执行"
                )
            return active
        raise


def mark_running(db: Session, *, run: GenerationRun) -> None:
    current = datetime.now(timezone.utc)
    run.status = "running"
    run.current_node = "prepare_context"
    run.started_at = current
    run.error_message = None
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=run.task_id,
        source_type="generation",
        source_id=run.id,
        state="claimed",
        attempt=run.attempt_count,
        occurred_at=current,
    )
    db.commit()


def _clear_worker(run: GenerationRun) -> None:
    run.worker_id = None
    run.lease_expires_at = None
    run.heartbeat_at = None


def _clear_output(run: GenerationRun) -> None:
    run.result_revision_id = None
    run.output_digest = None
    run.output_snapshot = None
    run.scene_evidence.clear()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def agent_execution_control(run: GenerationRun | None) -> dict[str, Any]:
    """将生成运行投影为可持久化、可公开的 Agent 执行控制状态。"""
    if run is None:
        return {
            "cost_cny": None,
            "cost_reserved_cny": 0.0,
            "cost_limit_cny": None,
            "execution_deadline_at": None,
            "cancel_requested_at": None,
        }

    def timestamp(value: datetime | None) -> str | None:
        if value is None:
            return None
        return _as_utc(value).isoformat().replace("+00:00", "Z")

    return {
        "cost_cny": float(run.cost_cny) if run.cost_cny is not None else None,
        "cost_reserved_cny": float(run.cost_reserved_cny or 0.0),
        "cost_limit_cny": (
            float(run.cost_limit_cny) if run.cost_limit_cny is not None else None
        ),
        "execution_deadline_at": timestamp(run.execution_deadline_at),
        "cancel_requested_at": timestamp(run.cancel_requested_at),
    }


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
    _sync_agent_checkpoint(task=task, run=run)


def _sync_agent_checkpoint(*, task: DesignTask, run: GenerationRun) -> bool:
    checkpoint = task.agent_state_json
    if not isinstance(checkpoint, dict) or checkpoint.get("run_id") != run.id:
        return False
    updated = dict(checkpoint)
    updated.update(agent_execution_control(run))
    result = dict(updated.get("result") or {})
    result.update({"run_id": run.id, "generation_status": run.status})
    budget_events = [
        event
        for event in run.events
        if event.node in {"budget_replan", "budget_guard"}
        and isinstance(event.detail_json, dict)
    ]
    budget_retry_count = max(
        (
            int(event.detail_json.get("retry_count") or 0)
            for event in budget_events
        ),
        default=0,
    )
    updated["retry_count"] = max(
        int(updated.get("retry_count") or 0),
        budget_retry_count,
    )
    if run.status == "completed":
        result.update(
            {
                "result_revision_id": run.result_revision_id,
                "output_digest": run.output_digest,
            }
        )
    if run.status in ACTIVE_STATUSES:
        updated.update(
            {
                "status": "running",
                "current_node": "generation_queued",
                "exit_reason": "generation_queued",
                "approval_required": False,
                "result": result,
            }
        )
    elif run.status == "completed":
        updated.update(
            {
                "status": "completed",
                "current_node": "generation_completed",
                "exit_reason": "goal_completed",
                "approval_required": False,
                "result": result,
            }
        )
    elif run.status == "cancelled":
        updated.update(
            {
                "status": "cancelled",
                "current_node": "generation_cancelled",
                "exit_reason": "cancelled",
                "approval_required": False,
                "result": result,
            }
        )
    elif run.current_node == "budget_guard":
        result["reason_code"] = GenerationBudgetReplanExhausted.reason_code
        updated.update(
            {
                "status": "needs_human",
                "current_node": "budget_guard",
                "exit_reason": GenerationBudgetReplanExhausted.reason_code,
                "approval_required": True,
                "hard_errors": list(
                    dict.fromkeys(
                        [
                            *(updated.get("hard_errors") or []),
                            "budget_exceeded",
                        ]
                    )
                ),
                "result": result,
            }
        )
    else:
        updated.update(
            {
                "status": "needs_human",
                "current_node": "generation_failed",
                "exit_reason": "generation_failed",
                "approval_required": True,
                "hard_errors": list(
                    dict.fromkeys(
                        [
                            *(updated.get("hard_errors") or []),
                            f"generation_{run.status}",
                        ]
                    )
                ),
                "result": result,
            }
        )
    if updated == checkpoint:
        return False
    task.agent_state_json = updated
    task.agent_state_version = (task.agent_state_version or 0) + 1
    return True


def synchronize_agent_checkpoint(db: Session, *, task: DesignTask) -> bool:
    """刷新读取时以绑定的 GenerationRun 终态修复 Agent checkpoint。"""
    checkpoint = task.agent_state_json
    run_id = checkpoint.get("run_id") if isinstance(checkpoint, dict) else None
    if not isinstance(run_id, int):
        return False
    run = db.get(GenerationRun, run_id)
    if run is None or run.task_id != task.id:
        return False
    changed = _sync_agent_checkpoint(task=task, run=run)
    if changed:
        db.commit()
    return changed


def _mark_dead_letter(
    db: Session,
    *,
    run: GenerationRun,
    now: datetime,
    error_message: str,
) -> None:
    _clear_worker(run)
    _clear_output(run)
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
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=run.task_id,
        source_type="generation",
        source_id=run.id,
        state="dead_letter",
        attempt=run.attempt_count,
        generation_cost_cny=run.cost_cny,
        occurred_at=now,
    )


def _has_model_call_reservation(run: GenerationRun) -> bool:
    # cost_limit_cny 初始为 NULL，仅在 reserve_model_cost 成功预留时原子写入。
    # 不能只判断预留金额：零单价也可能已发送请求。供应商响应丢失时保守停止，
    # 不以新的 attempt 幂等键重发；明确的业务重规划仍在同一个活跃 attempt 内执行。
    return (
        run.cost_limit_cny is not None
        or float(run.cost_reserved_cny or 0) > 0
        or float(run.cost_cny or 0) > 0
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
            _clear_output(run)
            run.status = "cancelled"
            run.current_node = "cancelled"
            run.completed_at = current
            run.next_retry_at = None
            _set_task_state(db, run=run, status="cancelled", progress=0)
            task_timeline_service.record_lifecycle_event(
                db,
                task_id=run.task_id,
                source_type="generation",
                source_id=run.id,
                state="cancelled",
                attempt=run.attempt_count,
                generation_cost_cny=run.cost_cny,
                occurred_at=current,
            )
            continue
        if _deadline_reached(run, now=current):
            _mark_dead_letter(
                db,
                run=run,
                now=current,
                error_message="方案生成超过硬执行截止时间",
            )
            continue

        if _has_model_call_reservation(run):
            _mark_dead_letter(
                db, run=run, now=current,
                error_message="Worker 中断前已预留模型调用，结果可能已计费；停止自动重试，请检查后手动重试",
            )
            continue

        retry_at = current + timedelta(seconds=retry_delay_seconds)
        retry_before_deadline = (
            run.execution_deadline_at is None
            or retry_at < _as_utc(run.execution_deadline_at)
        )
        if run.attempt_count < run.max_attempts and retry_before_deadline:
            _clear_worker(run)
            _clear_output(run)
            run.status = "queued"
            run.progress = 0
            run.current_node = "queued"
            run.next_retry_at = retry_at
            run.error_message = "上次 Worker 租约过期，等待重试"
            _set_task_state(db, run=run, status="queued", progress=50)
            task_timeline_service.record_lifecycle_event(
                db,
                task_id=run.task_id,
                source_type="generation",
                source_id=run.id,
                state="retry_scheduled",
                attempt=run.attempt_count,
                occurred_at=current,
            )
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
    if _has_model_call_reservation(run):
        _mark_dead_letter(
            db, run=run, now=current,
            error_message="排队任务已有模型调用预留；停止自动重试，请检查后手动重试",
        )
        db.commit()
        return None
    if evaluation_binding_service.is_evaluation_idempotency_key(
        run.idempotency_key
    ):
        try:
            evaluation_binding_service.validate_persisted_binding(
                db,
                run=run,
                validate_current_generation=True,
            )
        except evaluation_binding_service.EvaluationBindingError as exc:
            _clear_worker(run)
            run.status = "dead_letter"
            run.progress = 100
            run.current_node = "evaluation_binding_invalid"
            run.next_retry_at = None
            run.completed_at = current
            run.dead_lettered_at = current
            run.error_message = str(exc)[:2000]
            _set_task_state(
                db,
                run=run,
                status="failed",
                progress=0,
                error_message="评测执行绑定校验失败",
            )
            task_timeline_service.record_lifecycle_event(
                db,
                task_id=run.task_id,
                source_type="generation",
                source_id=run.id,
                state="dead_letter",
                attempt=run.attempt_count,
                generation_cost_cny=run.cost_cny,
                occurred_at=current,
            )
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
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=run.task_id,
        source_type="generation",
        source_id=run.id,
        state="claimed",
        attempt=run.attempt_count,
        occurred_at=current,
    )
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
    result_revision_id: int | None = None,
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
    if result_revision_id is None:
        raise generation_output_service.GenerationOutputValidationError(
            "成功运行必须绑定不可变输出 revision"
        )
    generation_output_service.bind_run_output(
        db,
        run=run,
        revision_id=result_revision_id,
        generator=generator,
    )
    run.status = "completed"
    run.progress = 100
    run.current_node = "completed"
    run.generator = generator
    run.completed_at = current
    run.next_retry_at = None
    _clear_worker(run)
    _set_task_state(db, run=run, status="completed", progress=100)
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=run.task_id,
        source_type="generation",
        source_id=run.id,
        state="completed",
        attempt=run.attempt_count,
        generation_cost_cny=run.cost_cny,
        occurred_at=current,
    )
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
    first_meta = run.output_snapshot is None
    fields_to_validate = (
        *_GENERATION_STATIC_META_FIELDS,
        *(_GENERATION_INITIAL_INPUT_FIELDS if first_meta else ()),
    )
    drifted_fields = [
        field
        for field in fields_to_validate
        if getattr(run, field) is not None
        and meta.get(field) != getattr(run, field)
    ]
    if drifted_fields:
        raise GenerationMetadataDriftError(
            "生成重规划静态版本与首次冻结值不一致："
            + ", ".join(drifted_fields)
        )

    if first_meta:
        for field in (
            *_GENERATION_STATIC_META_FIELDS,
            *_GENERATION_INITIAL_INPUT_FIELDS,
        ):
            if getattr(run, field) is None:
                setattr(run, field, meta.get(field))
    run.output_snapshot = output_snapshot
    previous_usage = run.usage_json if isinstance(run.usage_json, dict) else {}
    current_usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    usage_keys = set(previous_usage) | set(current_usage)
    run.usage_json = {
        key: (
            previous_usage.get(key, 0) + current_usage.get(key, 0)
            if isinstance(previous_usage.get(key, 0), (int, float))
            and not isinstance(previous_usage.get(key, 0), bool)
            and isinstance(current_usage.get(key, 0), (int, float))
            and not isinstance(current_usage.get(key, 0), bool)
            else current_usage.get(key, previous_usage.get(key))
        )
        for key in usage_keys
    } or None
    current_cost = meta.get("cost_cny")
    if isinstance(current_cost, (int, float)) and not isinstance(current_cost, bool):
        run.cost_cny = float(run.cost_cny or 0.0) + float(current_cost)
    if commit:
        db.commit()
    else:
        db.flush()
    return True


def mark_budget_replan_exhausted(
    db: Session,
    *,
    run_id: int,
    worker_id: str,
    worker_attempt: int,
    error: GenerationBudgetReplanExhausted,
    now: datetime | None = None,
) -> bool:
    """把预算重规划耗尽收敛为明确、不可伪成功的人工接管终态。"""
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
    _clear_output(run)
    run.status = "failed"
    run.progress = 100
    run.current_node = "budget_guard"
    run.error_message = str(error)[:2000]
    run.next_retry_at = None
    run.completed_at = current
    last_event = run.events[-1] if run.events else None
    if last_event is None or last_event.node != "budget_guard":
        run.events.append(
            GenerationRunEvent(
                node="budget_guard",
                status="failed",
                progress=100,
                source="deterministic",
                detail_json=error.details,
            )
        )
        db.flush()
    _set_task_state(
        db,
        run=run,
        status="needs_human",
        progress=0,
        error_message=run.error_message,
    )
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=run.task_id,
        source_type="generation",
        source_id=run.id,
        state="failed",
        attempt=run.attempt_count,
        generation_cost_cny=run.cost_cny,
        occurred_at=current,
    )
    db.commit()
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
    _clear_output(run)
    retry_at = current + timedelta(seconds=retry_delay_seconds)
    retry_before_deadline = (
        run.execution_deadline_at is None
        or retry_at < _as_utc(run.execution_deadline_at)
    )
    if retryable and _has_model_call_reservation(run):
        _mark_dead_letter(
            db, run=run, now=current,
            error_message="模型调用可能已计费；停止自动重试，请检查后手动重试。" + run.error_message,
        )
    elif (
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
        task_timeline_service.record_lifecycle_event(
            db,
            task_id=run.task_id,
            source_type="generation",
            source_id=run.id,
            state="retry_scheduled",
            attempt=run.attempt_count,
            occurred_at=current,
        )
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
        task_timeline_service.record_lifecycle_event(
            db,
            task_id=run.task_id,
            source_type="generation",
            source_id=run.id,
            state="failed",
            attempt=run.attempt_count,
            generation_cost_cny=run.cost_cny,
            occurred_at=current,
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
    _clear_output(run)
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
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=run.task_id,
        source_type="generation",
        source_id=run.id,
        state="failed",
        attempt=run.attempt_count,
        generation_cost_cny=run.cost_cny,
        occurred_at=current,
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
    _clear_output(run)
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
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=run.task_id,
        source_type="generation",
        source_id=run.id,
        state="failed",
        attempt=run.attempt_count,
        generation_cost_cny=run.cost_cny,
        occurred_at=current,
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
        _clear_output(run)
        _set_task_state(db, run=run, status="cancelled", progress=0)
        task_timeline_service.record_lifecycle_event(
            db,
            task_id=run.task_id,
            source_type="generation",
            source_id=run.id,
            state="cancelled",
            attempt=run.attempt_count,
            generation_cost_cny=run.cost_cny,
            occurred_at=current,
        )
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
    _clear_output(run)
    _set_task_state(db, run=run, status="cancelled", progress=0)
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=run.task_id,
        source_type="generation",
        source_id=run.id,
        state="cancelled",
        attempt=run.attempt_count,
        generation_cost_cny=run.cost_cny,
        occurred_at=current,
    )
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
