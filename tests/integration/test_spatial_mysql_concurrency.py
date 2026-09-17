"""显式启用的本机 MySQL 并发验收，仅创建和清理本测试的记录。"""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import (
    AnonymousSession,
    AnonymousSessionTask,
    DesignSpace,
    DesignSpaceVersion,
    DesignTask,
)
from app.schemas.spatial import SpatialSaveRequest
from app.services.anonymous_session_service import create_anonymous_session, attach_task
from app.services.spatial_service import save_space, SpatialConflict
from tests.unit.test_spatial_document import document


@pytest.fixture
def mysql_context():
    if os.environ.get("HAUS_RUN_MYSQL_SPATIAL_TESTS") != "1":
        pytest.skip("本机 MySQL 并发验收未显式启用")
    url = make_url(settings.database_url)
    assert url.get_backend_name() == "mysql" and url.host in {"localhost", "127.0.0.1"}
    engine = create_engine(
        settings.database_url,
        pool_size=3,
        max_overflow=0,
        isolation_level="REPEATABLE READ",
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = create_anonymous_session(db)
        task = DesignTask(status="waiting_input", raw_user_input="整屋隔离并发验收")
        db.add(task)
        db.flush()
        attach_task(db, session_id=owner.id, task_id=task.id)
        db.commit()
        task_id, session_id = task.id, owner.id
    try:
        yield factory, task_id, session_id
    finally:
        with factory() as db:
            db.execute(
                delete(DesignSpaceVersion).where(DesignSpaceVersion.task_id == task_id)
            )
            db.execute(delete(DesignSpace).where(DesignSpace.task_id == task_id))
            db.execute(
                delete(AnonymousSessionTask).where(
                    AnonymousSessionTask.task_id == task_id
                )
            )
            db.execute(delete(DesignTask).where(DesignTask.id == task_id))
            db.execute(
                delete(AnonymousSession).where(AnonymousSession.id == session_id)
            )
            db.commit()
        engine.dispose()


@pytest.mark.parametrize("same_key", [False, True])
def test_mysql_initial_snapshot_cannot_bypass_cas_or_idempotency(
    mysql_context, same_key
):
    factory, task_id, session_id = mysql_context
    barrier = Barrier(2)

    def save(key):
        with factory() as db:
            # 在另一事务提交前建立旧快照，再等待父任务写锁。
            db.scalar(select(DesignTask).where(DesignTask.id == task_id))
            barrier.wait(timeout=10)
            try:
                return save_space(
                    db,
                    task_id=task_id,
                    session_id=session_id,
                    payload=SpatialSaveRequest(
                        base_version=0, client_mutation_id=key, document=document()
                    ),
                ).version
            except SpatialConflict:
                db.rollback()
                return 409

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["same", "same" if same_key else "other"]))
    assert sorted(results) == ([1, 1] if same_key else [1, 409])
    with factory() as db:
        assert (
            len(
                db.scalars(
                    select(DesignSpaceVersion).where(
                        DesignSpaceVersion.task_id == task_id
                    )
                ).all()
            )
            == 1
        )
