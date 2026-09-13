from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from typing import Iterator

import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.core.config import settings
from app.db.models import (
    AnonymousSession,
    AnonymousSessionTask,
    DesignPlanVersion,
    DesignRevision,
    DesignTask,
    PlanShare,
    QuoteSnapshot,
)
from app.services import share_service
from tests.integration.test_plan_share_api import _context


@pytest.fixture(scope="module")
def mysql_engine() -> Iterator[Engine]:
    if make_url(settings.database_url).get_backend_name() != "mysql":
        pytest.skip("真实分享锁验收只允许 MySQL，不能用 SQLite 代替")
    engine: Engine | None = None
    try:
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=3,
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
        if not {
            "design_plan_versions",
            "quote_snapshots",
            "plan_shares",
        } <= tables:
            pytest.skip("MySQL 未迁移到方案分享版本")
    except (ModuleNotFoundError, SQLAlchemyError) as exc:
        if engine is not None:
            engine.dispose()
        pytest.skip(f"当前环境没有可用的 MySQL 集成测试库: {type(exc).__name__}")

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.integration
def test_mysql_share_audit_holds_plan_lock_until_snapshot_commit(
    mysql_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory, owner_id, _, task_id, plan_version_id = _context(mysql_engine)
    with factory() as db:
        revision_id = db.get(DesignPlanVersion, plan_version_id).revision_id

    share_reached_commit = Event()
    mutation_finished = Event()
    original_token = share_service.secrets.token_urlsafe

    def coordinated_token(length: int) -> str:
        share_reached_commit.set()
        assert mutation_finished.wait(timeout=5)
        return original_token(length)

    monkeypatch.setattr(share_service.secrets, "token_urlsafe", coordinated_token)

    def create_share():
        with factory() as db:
            plan = db.get(DesignPlanVersion, plan_version_id)
            return share_service.create_share(
                db,
                plan_version=plan,
                expires_in_hours=24,
            )

    def mutate_plan() -> int:
        assert share_reached_commit.wait(timeout=5)
        with factory() as db:
            db.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))
            plan = db.get(DesignPlanVersion, plan_version_id)
            changed = deepcopy(plan.plan_json)
            changed["name"] = "审计后并发改写"
            plan.plan_json = changed
            try:
                db.commit()
            except OperationalError as exc:
                db.rollback()
                error_args = getattr(exc.orig, "args", ())
                error_code = error_args[0] if error_args else None
            else:
                error_code = 0
        mutation_finished.set()
        return error_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            share_future = executor.submit(create_share)
            mutation_future = executor.submit(mutate_plan)
            mutation_error = mutation_future.result(timeout=5)
            share, _ = share_future.result(timeout=5)

        assert mutation_error == 1205
        assert share.snapshot_json["name"] == "服务端冻结方案"
        with factory() as db:
            persisted = db.get(DesignPlanVersion, plan_version_id)
            assert persisted.plan_json["name"] == "服务端冻结方案"
            assert db.scalar(
                select(PlanShare).where(
                    PlanShare.plan_version_id == plan_version_id
                )
            ) is not None
    finally:
        with factory.begin() as db:
            db.execute(
                delete(PlanShare).where(
                    PlanShare.plan_version_id == plan_version_id
                )
            )
            db.execute(
                delete(QuoteSnapshot).where(
                    QuoteSnapshot.plan_version_id == plan_version_id
                )
            )
            db.execute(
                delete(DesignPlanVersion).where(
                    DesignPlanVersion.id == plan_version_id
                )
            )
            db.execute(delete(DesignRevision).where(DesignRevision.id == revision_id))
            db.execute(
                delete(AnonymousSessionTask).where(
                    AnonymousSessionTask.session_id == owner_id,
                    AnonymousSessionTask.task_id == task_id,
                )
            )
            db.execute(delete(DesignTask).where(DesignTask.id == task_id))
            db.execute(
                delete(AnonymousSession).where(AnonymousSession.id == owner_id)
            )
