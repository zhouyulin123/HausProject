from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import WorkerHeartbeat
from app.services import worker_presence_service


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    WorkerHeartbeat.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def test_readiness_requires_one_fresh_instance_of_every_worker_type(db):
    now = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    for worker_type in worker_presence_service.REQUIRED_WORKER_TYPES:
        worker_presence_service.record_heartbeat(
            db,
            worker_type=worker_type,
            worker_id=f"{worker_type}-1",
            now=now,
        )

    snapshot = worker_presence_service.readiness_snapshot(
        db,
        now=now + timedelta(seconds=20),
        stale_after_seconds=45,
    )

    assert snapshot.ready is True
    assert all(check.status == "ok" for check in snapshot.checks.values())
    assert all(check.active_workers == 1 for check in snapshot.checks.values())


def test_readiness_fails_closed_for_missing_and_stale_workers(db):
    now = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    worker_presence_service.record_heartbeat(
        db,
        worker_type="generation",
        worker_id="generation-stale",
        now=now - timedelta(seconds=46),
    )
    worker_presence_service.record_heartbeat(
        db,
        worker_type="effect_render",
        worker_id="effect-fresh",
        now=now,
    )

    snapshot = worker_presence_service.readiness_snapshot(
        db,
        now=now,
        stale_after_seconds=45,
    )

    assert snapshot.ready is False
    assert snapshot.checks["generation"].status == "stale"
    assert snapshot.checks["generation"].active_workers == 0
    assert snapshot.checks["effect_render"].status == "ok"
    assert snapshot.checks["blender"].status == "missing"


def test_stopped_worker_is_immediately_excluded_from_readiness(db):
    now = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    worker_presence_service.record_heartbeat(
        db,
        worker_type="blender",
        worker_id="blender-1",
        now=now,
    )
    worker_presence_service.mark_stopped(
        db,
        worker_type="blender",
        worker_id="blender-1",
        now=now + timedelta(seconds=1),
    )

    snapshot = worker_presence_service.readiness_snapshot(
        db,
        now=now + timedelta(seconds=2),
        stale_after_seconds=45,
    )

    assert snapshot.checks["blender"].status == "missing"
    assert snapshot.checks["blender"].active_workers == 0


def test_unknown_worker_type_is_rejected(db):
    with pytest.raises(ValueError, match="worker_type"):
        worker_presence_service.record_heartbeat(
            db,
            worker_type="unknown",
            worker_id="worker-1",
        )


def test_reporter_registers_before_work_and_marks_graceful_stop(monkeypatch):
    events: list[tuple[str, str, str]] = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        worker_presence_service,
        "record_heartbeat",
        lambda _db, *, worker_type, worker_id, now=None: events.append(
            ("heartbeat", worker_type, worker_id)
        ),
    )
    monkeypatch.setattr(
        worker_presence_service,
        "mark_stopped",
        lambda _db, *, worker_type, worker_id, now=None: events.append(
            ("stopped", worker_type, worker_id)
        ),
    )

    reporter = worker_presence_service.WorkerPresenceReporter(
        worker_type="generation",
        worker_id="generation-1",
        heartbeat_seconds=30,
        session_factory=FakeSession,
    )
    with reporter:
        assert events == [("heartbeat", "generation", "generation-1")]

    assert events[-1] == ("stopped", "generation", "generation-1")
