from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import DesignTask, OpenGeometryRateLimitBucket
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)
from app.services.open_geometry_rate_limit import (
    OpenGeometryRateLimiter,
    OpenGeometryRateLimitScopeError,
    OpenGeometryRateLimitStateError,
)


@pytest.fixture
def shared_rate_limit_db(tmp_path):
    database_path = tmp_path / "open-geometry-rate-limit.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        first_owner = create_anonymous_session(db)
        second_owner = create_anonymous_session(db)
        first_task = DesignTask(
            status="waiting_input",
            active_mode="custom_furniture",
            agent_state_json={},
        )
        second_task = DesignTask(
            status="waiting_input",
            active_mode="custom_furniture",
            agent_state_json={},
        )
        db.add_all([first_task, second_task])
        db.commit()
        attach_task(db, first_owner.id, first_task.id)
        attach_task(db, second_owner.id, second_task.id)
        result = (
            factory,
            first_owner.id,
            first_task.id,
            second_owner.id,
            second_task.id,
        )
    try:
        yield result
    finally:
        engine.dispose()


def test_limit_is_shared_by_independent_service_instances_and_sessions(
    shared_rate_limit_db,
):
    factory, owner_id, task_id, second_owner_id, second_task_id = (
        shared_rate_limit_db
    )
    first_instance = OpenGeometryRateLimiter(max_requests=1, window_seconds=60)
    second_instance = OpenGeometryRateLimiter(max_requests=1, window_seconds=60)
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)

    with factory() as first_db:
        assert (
            first_instance.retry_after(
                first_db,
                session_id=owner_id,
                task_id=task_id,
                now=now,
            )
            is None
        )
    with factory() as second_db:
        assert second_instance.retry_after(
            second_db,
            session_id=owner_id,
            task_id=task_id,
            now=now + timedelta(seconds=10),
        ) == 50

    # 限额以会话与任务组合为边界，其他用户的其他任务互不影响。
    with factory() as isolated_db:
        assert (
            second_instance.retry_after(
                isolated_db,
                session_id=second_owner_id,
                task_id=second_task_id,
                now=now + timedelta(seconds=10),
            )
            is None
        )

    with factory() as inspection_db:
        rows = inspection_db.scalars(
            select(OpenGeometryRateLimitBucket).order_by(
                OpenGeometryRateLimitBucket.task_id
            )
        ).all()
        assert len(rows) == 2
        assert rows[0].record_version == 1


def test_limit_expires_old_attempts_using_a_sliding_window(shared_rate_limit_db):
    factory, owner_id, task_id, _, _ = shared_rate_limit_db
    limiter = OpenGeometryRateLimiter(max_requests=2, window_seconds=60)
    started_at = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)

    with factory() as db:
        assert limiter.retry_after(
            db,
            session_id=owner_id,
            task_id=task_id,
            now=started_at,
        ) is None
    with factory() as db:
        assert limiter.retry_after(
            db,
            session_id=owner_id,
            task_id=task_id,
            now=started_at + timedelta(seconds=20),
        ) is None
    with factory() as db:
        assert limiter.retry_after(
            db,
            session_id=owner_id,
            task_id=task_id,
            now=started_at + timedelta(seconds=30),
        ) == 30
    with factory() as db:
        assert limiter.retry_after(
            db,
            session_id=owner_id,
            task_id=task_id,
            now=started_at + timedelta(seconds=61),
        ) is None

    with factory() as inspection_db:
        bucket = inspection_db.scalar(select(OpenGeometryRateLimitBucket))
        assert len(bucket.attempted_at_json) == 2
        assert bucket.record_version == 3


def test_limit_keeps_monotonic_time_when_a_node_clock_moves_back(
    shared_rate_limit_db,
):
    factory, owner_id, task_id, _, _ = shared_rate_limit_db
    limiter = OpenGeometryRateLimiter(max_requests=2, window_seconds=60)
    later = datetime(2026, 9, 11, 8, 0, 20, tzinfo=timezone.utc)
    earlier = later - timedelta(seconds=10)

    with factory() as db:
        assert limiter.retry_after(
            db,
            session_id=owner_id,
            task_id=task_id,
            now=later,
        ) is None
    with factory() as db:
        assert limiter.retry_after(
            db,
            session_id=owner_id,
            task_id=task_id,
            now=earlier,
        ) is None
    with factory() as db:
        assert limiter.retry_after(
            db,
            session_id=owner_id,
            task_id=task_id,
            now=earlier + timedelta(seconds=1),
        ) == 60

    with factory() as inspection_db:
        bucket = inspection_db.scalar(select(OpenGeometryRateLimitBucket))
        expected = int(later.timestamp() * 1000)
        assert bucket.attempted_at_json == [expected, expected]


def test_database_failure_does_not_fall_back_to_process_memory(
    shared_rate_limit_db,
):
    factory, owner_id, task_id, _, _ = shared_rate_limit_db
    limiter = OpenGeometryRateLimiter(max_requests=2, window_seconds=60)
    with factory() as db:
        OpenGeometryRateLimitBucket.__table__.drop(db.get_bind())

    with factory() as db, pytest.raises(OperationalError):
        limiter.retry_after(
            db,
            session_id=owner_id,
            task_id=task_id,
            now=datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc),
        )


def test_invalid_session_task_scope_fails_closed(shared_rate_limit_db):
    factory, owner_id, _, _, second_task_id = shared_rate_limit_db
    limiter = OpenGeometryRateLimiter(max_requests=2, window_seconds=60)

    with factory() as db, pytest.raises(OpenGeometryRateLimitScopeError):
        limiter.retry_after(
            db,
            session_id=owner_id,
            task_id=second_task_id,
            now=datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc),
        )


def test_corrupted_shared_bucket_fails_closed(shared_rate_limit_db):
    factory, owner_id, task_id, _, _ = shared_rate_limit_db
    with factory() as db:
        db.add(
            OpenGeometryRateLimitBucket(
                session_id=owner_id,
                task_id=task_id,
                attempted_at_json=["not-a-timestamp"],
                record_version=1,
            )
        )
        db.commit()

    limiter = OpenGeometryRateLimiter(max_requests=2, window_seconds=60)
    with factory() as db, pytest.raises(OpenGeometryRateLimitStateError):
        limiter.retry_after(
            db,
            session_id=owner_id,
            task_id=task_id,
            now=datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc),
        )


def test_concurrent_instances_cannot_admit_more_than_the_shared_limit(
    shared_rate_limit_db,
):
    factory, owner_id, task_id, _, _ = shared_rate_limit_db
    started_at = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    workers = 8
    barrier = Barrier(workers)

    def attempt(_index: int) -> int | None:
        limiter = OpenGeometryRateLimiter(max_requests=3, window_seconds=60)
        with factory() as db:
            barrier.wait(timeout=10)
            return limiter.retry_after(
                db,
                session_id=owner_id,
                task_id=task_id,
                now=started_at,
            )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        decisions = list(executor.map(attempt, range(workers)))

    assert decisions.count(None) == 3
    assert decisions.count(60) == 5
