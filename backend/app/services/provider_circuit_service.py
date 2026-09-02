"""基于数据库行锁的模型供应商熔断状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ModelProviderCircuit


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ProviderCallPermit:
    provider_key: str
    probe_token: str | None = None

    @property
    def is_probe(self) -> bool:
        return self.probe_token is not None


class ProviderCircuitOpen(RuntimeError):
    def __init__(
        self,
        *,
        provider_key: str,
        state: str,
        retry_at: datetime | None,
        consecutive_failures: int,
    ) -> None:
        super().__init__("模型供应商熔断已开启，需等待冷却或人工处理")
        self.provider_key = provider_key
        self.state = state
        self.retry_at = retry_at
        self.consecutive_failures = consecutive_failures


class ProviderProbeInProgress(ProviderCircuitOpen):
    pass


def get_provider_state(
    db: Session,
    provider_key: str,
) -> ModelProviderCircuit | None:
    return db.get(ModelProviderCircuit, provider_key)


def _locked_state(
    db: Session,
    provider_key: str,
    *,
    create: bool,
) -> ModelProviderCircuit | None:
    state = db.scalar(
        select(ModelProviderCircuit)
        .where(ModelProviderCircuit.provider_key == provider_key)
        .with_for_update()
    )
    if state is not None:
        return state

    if not create:
        return None

    state = ModelProviderCircuit(
        provider_key=provider_key,
        state="closed",
        consecutive_failures=0,
    )
    db.add(state)
    try:
        db.flush()
    except IntegrityError:
        # 并发首次访问由唯一主键决定胜者，败者重读持久状态。
        db.rollback()
        state = db.scalar(
            select(ModelProviderCircuit)
            .where(ModelProviderCircuit.provider_key == provider_key)
            .with_for_update()
        )
    if state is None:
        raise RuntimeError("无法初始化模型供应商熔断状态")
    return state


def acquire_provider_call(
    db: Session,
    *,
    provider_key: str,
    cooldown_seconds: int,
    probe_lease_seconds: int,
    now: datetime | None = None,
) -> ProviderCallPermit:
    """请求一次供应商调用权；熔断期会在调用前拒绝。"""
    current = _as_utc(now or datetime.now(timezone.utc))
    state = _locked_state(db, provider_key, create=False)

    if state is None:
        db.commit()
        return ProviderCallPermit(provider_key=provider_key)

    if state.state == "closed":
        db.commit()
        return ProviderCallPermit(provider_key=provider_key)

    cooldown_until = (
        _as_utc(state.cooldown_until)
        if state.cooldown_until is not None
        else None
    )
    if state.state == "open" and (
        cooldown_until is None or cooldown_until > current
    ):
        failures = state.consecutive_failures
        db.commit()
        raise ProviderCircuitOpen(
            provider_key=provider_key,
            state="open",
            retry_at=cooldown_until,
            consecutive_failures=failures,
        )

    probe_expires_at = (
        _as_utc(state.probe_expires_at)
        if state.probe_expires_at is not None
        else None
    )
    if (
        state.state == "half_open"
        and probe_expires_at is not None
        and probe_expires_at > current
    ):
        failures = state.consecutive_failures
        db.commit()
        raise ProviderProbeInProgress(
            provider_key=provider_key,
            state="half_open",
            retry_at=probe_expires_at,
            consecutive_failures=failures,
        )

    token = str(uuid4())
    state.state = "half_open"
    state.probe_token = token
    state.probe_expires_at = current + timedelta(seconds=probe_lease_seconds)
    db.commit()
    return ProviderCallPermit(provider_key=provider_key, probe_token=token)


def record_provider_failure(
    db: Session,
    *,
    permit: ProviderCallPermit,
    failure_code: str,
    failure_threshold: int,
    cooldown_seconds: int,
    now: datetime | None = None,
) -> ModelProviderCircuit:
    current = _as_utc(now or datetime.now(timezone.utc))
    state = _locked_state(db, permit.provider_key, create=True)
    assert state is not None

    if state.state == "closed" and not permit.is_probe:
        state.consecutive_failures += 1
        state.last_failure_code = failure_code
        if state.consecutive_failures >= failure_threshold:
            state.state = "open"
            state.opened_at = current
            state.cooldown_until = current + timedelta(seconds=cooldown_seconds)
    elif (
        state.state == "half_open"
        and permit.probe_token is not None
        and state.probe_token == permit.probe_token
    ):
        state.state = "open"
        state.consecutive_failures = max(
            state.consecutive_failures + 1,
            failure_threshold,
        )
        state.opened_at = current
        state.cooldown_until = current + timedelta(seconds=cooldown_seconds)
        state.last_failure_code = failure_code
        state.probe_token = None
        state.probe_expires_at = None
    db.commit()
    return state


def record_provider_success(
    db: Session,
    *,
    permit: ProviderCallPermit,
) -> ModelProviderCircuit:
    state = _locked_state(db, permit.provider_key, create=True)
    assert state is not None
    should_close = state.state == "closed" or (
        state.state == "half_open"
        and permit.probe_token is not None
        and state.probe_token == permit.probe_token
    )
    if should_close:
        state.state = "closed"
        state.consecutive_failures = 0
        state.opened_at = None
        state.cooldown_until = None
        state.probe_token = None
        state.probe_expires_at = None
        state.last_failure_code = None
    db.commit()
    return state


def release_provider_call(
    db: Session,
    *,
    permit: ProviderCallPermit,
) -> None:
    """供应商请求发出前被其他门禁拒绝时释放半开探针。"""
    if not permit.is_probe:
        db.rollback()
        return
    state = _locked_state(db, permit.provider_key, create=False)
    if (
        state is not None
        and state.state == "half_open"
        and state.probe_token == permit.probe_token
    ):
        state.state = "open"
        state.probe_token = None
        state.probe_expires_at = None
    db.commit()
