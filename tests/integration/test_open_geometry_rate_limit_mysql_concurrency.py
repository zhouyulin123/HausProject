from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
from typing import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import (
    AnonymousSession,
    AnonymousSessionTask,
    DesignTask,
    OpenGeometryRateLimitBucket,
)
from app.services.open_geometry_rate_limit import OpenGeometryRateLimiter


@pytest.fixture(scope="module")
def mysql_engine() -> Iterator[Engine]:
    if make_url(settings.database_url).get_backend_name() != "mysql":
        pytest.skip("真实共享限流验收只允许 MySQL，不能用 SQLite 代替")
    engine: Engine | None = None
    try:
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=8,
            max_overflow=0,
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            tables = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = DATABASE()"
                    )
                )
            }
        if "open_geometry_rate_limit_buckets" not in tables:
            pytest.skip("MySQL 未迁移到开放几何共享限流版本")
    except (ModuleNotFoundError, SQLAlchemyError) as exc:
        if engine is not None:
            engine.dispose()
        pytest.skip(f"当前环境没有可用的 MySQL 集成测试库: {type(exc).__name__}")

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.integration
def test_mysql_instances_share_one_atomic_sliding_window(
    mysql_engine: Engine,
) -> None:
    factory = sessionmaker(
        bind=mysql_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    session_id = str(uuid4())
    current = datetime.now(timezone.utc)
    with factory.begin() as db:
        owner = AnonymousSession(
            id=session_id,
            status="active",
            created_at=current,
            last_seen_at=current,
            expires_at=current + timedelta(days=1),
        )
        task = DesignTask(
            status="waiting_input",
            active_mode="custom_furniture",
            raw_user_input=f"mysql-open-geometry-limit:{uuid4().hex}",
            agent_state_json={},
        )
        db.add_all([owner, task])
        db.flush()
        task_id = task.id
        db.add(AnonymousSessionTask(session_id=session_id, task_id=task_id))

    workers = 8
    start = Barrier(workers, timeout=10)
    connection_lock = Lock()
    connection_ids: set[int] = set()

    def capture_bucket_connection(
        connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if "open_geometry_rate_limit_buckets" not in statement.lower():
            return
        with connection_lock:
            connection_ids.add(id(connection.connection.dbapi_connection))

    def attempt(_index: int) -> int | None:
        limiter = OpenGeometryRateLimiter(max_requests=3, window_seconds=60)
        with factory() as db:
            start.wait()
            return limiter.retry_after(
                db,
                session_id=session_id,
                task_id=task_id,
                now=current,
            )

    event.listen(mysql_engine, "before_cursor_execute", capture_bucket_connection)
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            decisions = list(executor.map(attempt, range(workers)))

        assert len(connection_ids) >= 2
        assert decisions.count(None) == 3
        assert decisions.count(60) == 5
        with factory() as db:
            bucket = db.scalar(
                select(OpenGeometryRateLimitBucket).where(
                    OpenGeometryRateLimitBucket.session_id == session_id,
                    OpenGeometryRateLimitBucket.task_id == task_id,
                )
            )
            assert bucket is not None
            assert len(bucket.attempted_at_json) == 3
            assert bucket.record_version == 3
    finally:
        event.remove(mysql_engine, "before_cursor_execute", capture_bucket_connection)
        with factory.begin() as db:
            db.execute(
                delete(OpenGeometryRateLimitBucket).where(
                    OpenGeometryRateLimitBucket.session_id == session_id,
                    OpenGeometryRateLimitBucket.task_id == task_id,
                )
            )
            db.execute(
                delete(AnonymousSessionTask).where(
                    AnonymousSessionTask.session_id == session_id,
                    AnonymousSessionTask.task_id == task_id,
                )
            )
            db.execute(delete(DesignTask).where(DesignTask.id == task_id))
            db.execute(
                delete(AnonymousSession).where(AnonymousSession.id == session_id)
            )
