"""跨产品入口的模型成本账户、逐次账本和持久化供应商熔断。"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import math
from typing import Any, Iterator, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.request_context import current_request_id
from app.db.database import SessionLocal
from app.db.models import (
    ModelCallCostAccount,
    ModelCallLedger,
    TaskExecutionEvent,
)
from app.services import provider_circuit_service
from app.services.llm_service import LLMUnavailable


ScopeKind = Literal["task", "session"]
Modality = Literal["text", "vision"]

_RESERVATION_TRANSACTION_MAX_ATTEMPTS = 3
_MYSQL_RETRYABLE_TRANSACTION_ERROR_CODES = {1062, 1205, 1213}


class ModelCallGovernanceError(LLMUnavailable):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class ModelCallCostConfigurationError(ModelCallGovernanceError):
    pass


class ModelCallCostLimitExceeded(ModelCallGovernanceError):
    pass


class ModelCallIdempotencyConflict(ModelCallGovernanceError):
    pass


class ModelProviderUnavailable(ModelCallGovernanceError):
    pass


@dataclass(frozen=True)
class ModelCallPermit:
    ledger_id: int
    estimated_cost_cny: float


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_cost(value: float | None) -> float | None:
    if value is None:
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        return None
    return normalized


def _cost_account_lock_statement(*, scope_kind: ScopeKind, scope_id: str):
    return (
        select(ModelCallCostAccount)
        .where(
            ModelCallCostAccount.scope_kind == scope_kind,
            ModelCallCostAccount.scope_id == scope_id,
        )
        .with_for_update()
    )


def _is_retryable_reservation_conflict(exc: DBAPIError) -> bool:
    error_args = getattr(exc.orig, "args", ())
    return bool(
        error_args
        and isinstance(error_args[0], int)
        and error_args[0] in _MYSQL_RETRYABLE_TRANSACTION_ERROR_CODES
    )


class PersistentModelCallHooks:
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        scope_kind: ScopeKind,
        scope_id: str,
        task_id: int | None,
        operation_key: str,
        cost_limit_cny: float,
    ) -> None:
        if scope_kind not in {"task", "session"}:
            raise ValueError("模型成本账户作用域不受支持")
        if not scope_id or len(scope_id) > 100:
            raise ValueError("模型成本账户作用域标识无效")
        if not operation_key or len(operation_key) > 150:
            raise ValueError("模型调用操作键无效")
        normalized_limit = _validate_cost(cost_limit_cny)
        if normalized_limit is None or normalized_limit <= 0:
            raise ValueError("模型调用成本上限必须为正数")
        if scope_kind == "task" and task_id is None:
            raise ValueError("任务成本账户必须绑定 task_id")
        self._session_factory = session_factory
        self._scope_kind = scope_kind
        self._scope_id = scope_id
        self._task_id = task_id
        self._operation_key = (
            "sha256:" + sha256(operation_key.encode("utf-8")).hexdigest()
        )
        self._cost_limit_cny = normalized_limit
        self._call_index = 0

    def _locked_account(self, db: Session) -> ModelCallCostAccount:
        account = db.scalar(
            _cost_account_lock_statement(
                scope_kind=self._scope_kind,
                scope_id=self._scope_id,
            )
        )
        if account is None:
            historical_cost = 0.0
            historical_unknown_count = 0
            if self._scope_kind == "task" and self._task_id is not None:
                historical_cost = float(
                    db.scalar(
                        select(
                            func.coalesce(func.sum(TaskExecutionEvent.cost_cny), 0.0)
                        ).where(
                            TaskExecutionEvent.task_id == self._task_id,
                            TaskExecutionEvent.billing_status == "metered",
                        )
                    )
                    or 0.0
                )
                historical_unknown_count = int(
                    db.scalar(
                        select(func.count(TaskExecutionEvent.id)).where(
                            TaskExecutionEvent.task_id == self._task_id,
                            TaskExecutionEvent.billing_status == "unknown",
                        )
                    )
                    or 0
                )
            account = ModelCallCostAccount(
                scope_kind=self._scope_kind,
                scope_id=self._scope_id,
                task_id=self._task_id,
                cost_limit_cny=self._cost_limit_cny,
                allocated_cost_cny=(
                    self._cost_limit_cny
                    if historical_unknown_count
                    else historical_cost
                ),
                actual_cost_cny=historical_cost,
                unknown_cost_call_count=historical_unknown_count,
            )
            db.add(account)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                raise
        if account is None:
            raise RuntimeError("无法初始化模型成本账户")
        if not math.isclose(
            float(account.cost_limit_cny),
            self._cost_limit_cny,
            rel_tol=0,
            abs_tol=1e-9,
        ):
            # 上限首次创建即冻结，后续配置变化不能放宽既有任务预算。
            self._cost_limit_cny = float(account.cost_limit_cny)
        return account

    def _blocked_row(
        self,
        db: Session,
        *,
        account: ModelCallCostAccount,
        provider_key: str,
        model: str,
        modality: Modality,
        estimated_cost_cny: float | None,
        failure_code: str,
    ) -> None:
        db.add(
            ModelCallLedger(
                account_id=account.id,
                task_id=self._task_id,
                request_id=current_request_id(),
                operation_key=self._operation_key,
                call_index=self._call_index,
                provider_key=provider_key,
                model=model,
                modality=modality,
                status="blocked",
                estimated_cost_cny=estimated_cost_cny,
                billing_status="not_billable",
                usage_json={},
                failure_code=failure_code,
                completed_at=_utc_now(),
            )
        )
        db.commit()

    def before_call(
        self,
        *,
        provider_key: str,
        model: str,
        modality: Modality,
        estimated_cost_cny: float | None,
    ) -> ModelCallPermit:
        self._call_index += 1
        estimated = _validate_cost(estimated_cost_cny)
        for attempt in range(_RESERVATION_TRANSACTION_MAX_ATTEMPTS):
            try:
                return self._reserve_call(
                    provider_key=provider_key,
                    model=model,
                    modality=modality,
                    estimated=estimated,
                )
            except (IntegrityError, OperationalError) as exc:
                if (
                    not _is_retryable_reservation_conflict(exc)
                    or attempt + 1 >= _RESERVATION_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
        raise RuntimeError("模型调用成本预留事务未能完成")

    def _reserve_call(
        self,
        *,
        provider_key: str,
        model: str,
        modality: Modality,
        estimated: float | None,
    ) -> ModelCallPermit:
        with self._session_factory() as db:
            account = self._locked_account(db)
            existing = db.scalar(
                select(ModelCallLedger).where(
                    ModelCallLedger.account_id == account.id,
                    ModelCallLedger.operation_key == self._operation_key,
                    ModelCallLedger.call_index == self._call_index,
                )
            )
            if existing is not None:
                db.rollback()
                raise ModelCallIdempotencyConflict(
                    "该业务操作的同序号模型调用已存在，禁止重复计费",
                    code="model_call_already_recorded",
                )
            if estimated is None:
                self._blocked_row(
                    db,
                    account=account,
                    provider_key=provider_key,
                    model=model,
                    modality=modality,
                    estimated_cost_cny=None,
                    failure_code="model_price_not_configured",
                )
                raise ModelCallCostConfigurationError(
                    "模型单价未配置，无法执行成本硬门禁",
                    code="model_price_not_configured",
                )
            projected = float(account.allocated_cost_cny or 0.0) + estimated
            if projected > float(account.cost_limit_cny) + 1e-9:
                code = f"{self._scope_kind}_model_cost_limit_exceeded"
                self._blocked_row(
                    db,
                    account=account,
                    provider_key=provider_key,
                    model=model,
                    modality=modality,
                    estimated_cost_cny=estimated,
                    failure_code=code,
                )
                raise ModelCallCostLimitExceeded(
                    "模型调用累计成本将超过冻结上限",
                    code=code,
                )
            row = ModelCallLedger(
                account_id=account.id,
                task_id=self._task_id,
                request_id=current_request_id(),
                operation_key=self._operation_key,
                call_index=self._call_index,
                provider_key=provider_key,
                model=model,
                modality=modality,
                status="reserved",
                estimated_cost_cny=estimated,
                billing_status="unknown",
                usage_json={},
            )
            db.add(row)
            account.allocated_cost_cny = projected
            db.commit()
            return ModelCallPermit(ledger_id=row.id, estimated_cost_cny=estimated)

    def record_success(
        self,
        permit: ModelCallPermit,
        *,
        usage: dict[str, int],
        actual_cost_cny: float | None,
    ) -> None:
        actual = _validate_cost(actual_cost_cny)
        with self._session_factory() as db:
            row = db.scalar(
                select(ModelCallLedger)
                .where(ModelCallLedger.id == permit.ledger_id)
                .with_for_update()
            )
            if row is None or row.status != "reserved":
                raise RuntimeError("模型调用预留不存在或已结算")
            account = db.scalar(
                select(ModelCallCostAccount)
                .where(ModelCallCostAccount.id == row.account_id)
                .with_for_update()
            )
            if account is None:
                raise RuntimeError("模型成本账户不存在")
            row.status = "succeeded"
            row.usage_json = dict(usage)
            row.actual_cost_cny = actual
            row.billing_status = "metered" if actual is not None else "unknown"
            row.completed_at = _utc_now()
            if actual is None:
                account.unknown_cost_call_count += 1
            else:
                account.actual_cost_cny = float(account.actual_cost_cny or 0.0) + actual
                account.allocated_cost_cny = max(
                    0.0,
                    float(account.allocated_cost_cny or 0.0)
                    - permit.estimated_cost_cny
                    + actual,
                )
            db.commit()

    def record_failure(
        self,
        permit: ModelCallPermit,
        *,
        failure_code: str,
    ) -> None:
        with self._session_factory() as db:
            row = db.scalar(
                select(ModelCallLedger)
                .where(ModelCallLedger.id == permit.ledger_id)
                .with_for_update()
            )
            if row is None or row.status != "reserved":
                raise RuntimeError("模型调用预留不存在或已结算")
            account = db.scalar(
                select(ModelCallCostAccount)
                .where(ModelCallCostAccount.id == row.account_id)
                .with_for_update()
            )
            if account is None:
                raise RuntimeError("模型成本账户不存在")
            row.status = "failed"
            row.failure_code = failure_code[:50]
            row.billing_status = "unknown"
            row.completed_at = _utc_now()
            account.unknown_cost_call_count += 1
            db.commit()

    def record_blocked(
        self,
        permit: ModelCallPermit,
        *,
        failure_code: str,
    ) -> None:
        """供应商请求未发出时释放预留，同时保留失败关闭证据。"""
        with self._session_factory() as db:
            row = db.scalar(
                select(ModelCallLedger)
                .where(ModelCallLedger.id == permit.ledger_id)
                .with_for_update()
            )
            if row is None or row.status != "reserved":
                raise RuntimeError("模型调用预留不存在或已结算")
            account = db.scalar(
                select(ModelCallCostAccount)
                .where(ModelCallCostAccount.id == row.account_id)
                .with_for_update()
            )
            if account is None:
                raise RuntimeError("模型成本账户不存在")
            row.status = "blocked"
            row.failure_code = failure_code[:50]
            row.billing_status = "not_billable"
            row.completed_at = _utc_now()
            account.allocated_cost_cny = max(
                0.0,
                float(account.allocated_cost_cny or 0.0) - permit.estimated_cost_cny,
            )
            db.commit()


def build_model_call_hooks(
    *,
    session_factory: sessionmaker = SessionLocal,
    scope_kind: ScopeKind,
    scope_id: str,
    task_id: int | None,
    operation_key: str,
    cost_limit_cny: float,
) -> PersistentModelCallHooks:
    return PersistentModelCallHooks(
        session_factory=session_factory,
        scope_kind=scope_kind,
        scope_id=scope_id,
        task_id=task_id,
        operation_key=operation_key,
        cost_limit_cny=cost_limit_cny,
    )


def build_provider_hooks(
    *,
    session_factory: sessionmaker = SessionLocal,
    failure_threshold: int,
    cooldown_seconds: int,
    probe_lease_seconds: int,
):
    from app.services.llm_service import ProviderCallHooks

    def before_call(provider_key: str):
        with session_factory() as db:
            try:
                return provider_circuit_service.acquire_provider_call(
                    db,
                    provider_key=provider_key,
                    cooldown_seconds=cooldown_seconds,
                    probe_lease_seconds=probe_lease_seconds,
                )
            except provider_circuit_service.ProviderCircuitOpen as exc:
                code = (
                    "provider_probe_in_progress"
                    if isinstance(
                        exc,
                        provider_circuit_service.ProviderProbeInProgress,
                    )
                    else "provider_circuit_open"
                )
                raise ModelProviderUnavailable(str(exc), code=code) from exc

    def record_success(permit: Any) -> None:
        with session_factory() as db:
            provider_circuit_service.record_provider_success(db, permit=permit)

    def record_failure(permit: Any, failure_code: str) -> None:
        with session_factory() as db:
            provider_circuit_service.record_provider_failure(
                db,
                permit=permit,
                failure_code=failure_code,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds,
            )

    def release_call(permit: Any) -> None:
        with session_factory() as db:
            provider_circuit_service.release_provider_call(db, permit=permit)

    return ProviderCallHooks(
        before_call=before_call,
        record_success=record_success,
        record_failure=record_failure,
        release_call=release_call,
    )


@contextmanager
def govern_model_calls(
    db: Session,
    *,
    scope_kind: ScopeKind,
    scope_id: str,
    task_id: int | None,
    operation_key: str,
    cost_limit_cny: float,
    failure_threshold: int,
    cooldown_seconds: int,
    probe_lease_seconds: int,
) -> Iterator[None]:
    """在独立短事务中治理调用，避免提交业务事务中的未完成状态。"""
    isolated_factory = sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    cost_hooks = build_model_call_hooks(
        session_factory=isolated_factory,
        scope_kind=scope_kind,
        scope_id=scope_id,
        task_id=task_id,
        operation_key=operation_key,
        cost_limit_cny=cost_limit_cny,
    )
    provider_hooks = build_provider_hooks(
        session_factory=isolated_factory,
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
        probe_lease_seconds=probe_lease_seconds,
    )
    from app.services import llm_service

    with (
        llm_service.model_call_governance(cost_hooks),
        llm_service.provider_call_guard(provider_hooks),
    ):
        yield


def govern_task_model_calls(
    db: Session,
    *,
    task_id: int,
    operation_key: str,
):
    from app.core.config import settings

    return govern_model_calls(
        db,
        scope_kind="task",
        scope_id=str(task_id),
        task_id=task_id,
        operation_key=operation_key,
        cost_limit_cny=settings.generation_task_cost_limit_cny,
        failure_threshold=settings.provider_circuit_failure_threshold,
        cooldown_seconds=settings.provider_circuit_cooldown_seconds,
        probe_lease_seconds=settings.provider_circuit_probe_lease_seconds,
    )


def govern_session_model_calls(
    db: Session,
    *,
    session_id: str,
    operation_key: str,
):
    from app.core.config import settings

    return govern_model_calls(
        db,
        scope_kind="session",
        scope_id=session_id,
        task_id=None,
        operation_key=operation_key,
        cost_limit_cny=settings.generation_task_cost_limit_cny,
        failure_threshold=settings.provider_circuit_failure_threshold,
        cooldown_seconds=settings.provider_circuit_cooldown_seconds,
        probe_lease_seconds=settings.provider_circuit_probe_lease_seconds,
    )
