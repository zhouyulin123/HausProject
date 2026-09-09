from datetime import datetime, timedelta, timezone
import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base


def _service():
    return importlib.import_module("app.services.provider_circuit_service")


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.mark.unit
def test_failures_persist_across_sessions_and_open_provider_circuit(
    session_factory,
):
    service = _service()
    now = datetime(2026, 9, 2, tzinfo=timezone.utc)

    with session_factory() as db:
        first = service.acquire_provider_call(
            db,
            provider_key="primary-llm",
            cooldown_seconds=30,
            probe_lease_seconds=10,
            now=now,
        )
        state = service.record_provider_failure(
            db,
            permit=first,
            failure_code="timeout",
            failure_threshold=2,
            cooldown_seconds=30,
            now=now,
        )
        assert state.state == "closed"
        assert state.consecutive_failures == 1

    with session_factory() as db:
        second = service.acquire_provider_call(
            db,
            provider_key="primary-llm",
            cooldown_seconds=30,
            probe_lease_seconds=10,
            now=now + timedelta(seconds=1),
        )
        state = service.record_provider_failure(
            db,
            permit=second,
            failure_code="rate_limited",
            failure_threshold=2,
            cooldown_seconds=30,
            now=now + timedelta(seconds=1),
        )
        assert state.state == "open"
        assert state.consecutive_failures == 2
        assert state.cooldown_until == now + timedelta(seconds=31)

    with session_factory() as db:
        with pytest.raises(service.ProviderCircuitOpen) as captured:
            service.acquire_provider_call(
                db,
                provider_key="primary-llm",
                cooldown_seconds=30,
                probe_lease_seconds=10,
                now=now + timedelta(seconds=2),
            )
        assert captured.value.state == "open"
        assert captured.value.retry_at == now + timedelta(seconds=31)


@pytest.mark.unit
def test_half_open_allows_one_probe_and_success_closes_circuit(session_factory):
    service = _service()
    now = datetime(2026, 9, 2, tzinfo=timezone.utc)
    with session_factory() as db:
        permit = service.acquire_provider_call(
            db,
            provider_key="primary-llm",
            cooldown_seconds=30,
            probe_lease_seconds=10,
            now=now,
        )
        service.record_provider_failure(
            db,
            permit=permit,
            failure_code="connection",
            failure_threshold=1,
            cooldown_seconds=30,
            now=now,
        )

    with session_factory() as probe_db:
        probe = service.acquire_provider_call(
            probe_db,
            provider_key="primary-llm",
            cooldown_seconds=30,
            probe_lease_seconds=10,
            now=now + timedelta(seconds=31),
        )
        assert probe.is_probe is True

    with session_factory() as other_worker_db:
        with pytest.raises(service.ProviderProbeInProgress):
            service.acquire_provider_call(
                other_worker_db,
                provider_key="primary-llm",
                cooldown_seconds=30,
                probe_lease_seconds=10,
                now=now + timedelta(seconds=32),
            )

    with session_factory() as probe_db:
        state = service.record_provider_success(probe_db, permit=probe)
        assert state.state == "closed"
        assert state.consecutive_failures == 0
        assert state.probe_token is None


@pytest.mark.unit
def test_expired_probe_can_be_replaced_and_stale_success_is_ignored(
    session_factory,
):
    service = _service()
    now = datetime(2026, 9, 2, tzinfo=timezone.utc)
    with session_factory() as db:
        permit = service.acquire_provider_call(
            db,
            provider_key="primary-llm",
            cooldown_seconds=5,
            probe_lease_seconds=5,
            now=now,
        )
        service.record_provider_failure(
            db,
            permit=permit,
            failure_code="server_error",
            failure_threshold=1,
            cooldown_seconds=5,
            now=now,
        )
        stale_probe = service.acquire_provider_call(
            db,
            provider_key="primary-llm",
            cooldown_seconds=5,
            probe_lease_seconds=5,
            now=now + timedelta(seconds=6),
        )
        replacement = service.acquire_provider_call(
            db,
            provider_key="primary-llm",
            cooldown_seconds=5,
            probe_lease_seconds=5,
            now=now + timedelta(seconds=12),
        )
        stale_state = service.record_provider_success(db, permit=stale_probe)
        assert stale_state.state == "half_open"
        assert stale_state.probe_token == replacement.probe_token

        closed = service.record_provider_success(db, permit=replacement)
        assert closed.state == "closed"

