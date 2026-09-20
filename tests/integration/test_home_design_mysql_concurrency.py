"""显式启用的家装 MySQL 并发验收，仅清理本测试创建的精确记录。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from threading import Barrier, Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import home_design_agent
from app.core.config import settings
from app.db.database import get_db
from app.db.models import (
    AnonymousSession,
    AnonymousSessionTask,
    DesignSpace,
    DesignSpaceVersion,
    DesignTask,
    HomeDesign,
    HomeDesignAgentTurn,
    HomeDesignAsset,
    HomeDesignVersion,
    ModelCallCostAccount,
    ModelCallLedger,
    Product,
    TaskExecutionEvent,
)
from app.schemas.home_design_agent import HomeDesignAgentPlan
from app.schemas.home_design import HomeDesignSaveRequest
from app.schemas.spatial import SpatialSaveRequest
from app.services import llm_service
from app.services.anonymous_session_service import attach_task, create_anonymous_session
from app.services.home_design_asset_service import _digest as asset_digest
from app.services.home_design_service import save_design
from app.services.spatial_service import SpatialConflict, save_space
from tests.unit.test_home_design import document
from tests.unit.test_spatial_document import document as spatial_document


@pytest.fixture
def mysql_context():
    if os.environ.get("HAUS_RUN_MYSQL_HOME_DESIGN_TESTS") != "1":
        pytest.skip("本机家装 MySQL 并发验收未显式启用")
    url = make_url(settings.database_url)
    assert url.get_backend_name() == "mysql" and url.host in {"localhost", "127.0.0.1"}
    engine = create_engine(
        settings.database_url,
        pool_size=3,
        max_overflow=0,
        isolation_level="REPEATABLE READ",
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    task_id = session_id = None
    created_product_ids = set()
    try:
        with factory() as db:
            owner = create_anonymous_session(db)
            task = DesignTask(status="waiting_input", raw_user_input="家装隔离并发验收")
            db.add(task)
            db.flush()
            attach_task(db, session_id=owner.id, task_id=task.id)
            db.commit()
            task_id, session_id = task.id, owner.id
            space = spatial_document()
            space["scale_status"] = "confirmed"
            save_space(
                db,
                task_id=task_id,
                session_id=session_id,
                payload=SpatialSaveRequest(
                    base_version=0, client_mutation_id="space", document=space
                ),
            )
        yield factory, task_id, session_id, created_product_ids
    finally:
        try:
            if task_id is not None and session_id is not None:
                with factory() as db:
                    account_ids = db.scalars(
                        select(ModelCallCostAccount.id).where(
                            ModelCallCostAccount.task_id == task_id
                        )
                    ).all()
                    if account_ids:
                        db.execute(
                            delete(ModelCallLedger).where(
                                ModelCallLedger.account_id.in_(account_ids)
                            )
                        )
                    db.execute(
                        delete(ModelCallCostAccount).where(
                            ModelCallCostAccount.task_id == task_id
                        )
                    )
                    db.execute(
                        delete(TaskExecutionEvent).where(
                            TaskExecutionEvent.task_id == task_id
                        )
                    )
                    for model in (
                        HomeDesignAgentTurn,
                        HomeDesignAsset,
                        HomeDesignVersion,
                        HomeDesign,
                        DesignSpaceVersion,
                        DesignSpace,
                    ):
                        db.execute(delete(model).where(model.task_id == task_id))
                    db.execute(
                        delete(AnonymousSessionTask).where(
                            AnonymousSessionTask.task_id == task_id,
                            AnonymousSessionTask.session_id == session_id,
                        )
                    )
                    db.execute(delete(DesignTask).where(DesignTask.id == task_id))
                    if created_product_ids:
                        db.execute(
                            delete(Product).where(Product.id.in_(created_product_ids))
                        )
                    db.execute(
                        delete(AnonymousSession).where(
                            AnonymousSession.id == session_id
                        )
                    )
                    db.commit()
                    assert db.get(DesignTask, task_id) is None
                    assert db.get(AnonymousSession, session_id) is None
                    for model in (
                        HomeDesignAgentTurn,
                        HomeDesignAsset,
                        TaskExecutionEvent,
                        ModelCallCostAccount,
                    ):
                        assert not db.scalars(
                            select(model).where(model.task_id == task_id)
                        ).all()
                    assert not db.scalars(
                        select(ModelCallLedger).where(
                            ModelCallLedger.task_id == task_id
                        )
                    ).all()
                    if created_product_ids:
                        assert not db.scalars(
                            select(Product).where(Product.id.in_(created_product_ids))
                        ).all()
        finally:
            engine.dispose()


@pytest.mark.parametrize("same_key", [False, True])
def test_mysql_home_initial_snapshot_cannot_bypass_cas_or_idempotency(
    mysql_context, same_key
):
    factory, task_id, session_id, _ = mysql_context
    barrier = Barrier(2)

    def save(key):
        with factory() as db:
            # 两个事务都先建立旧快照，要求加锁后重新读取版本与幂等记录。
            db.scalar(select(DesignTask).where(DesignTask.id == task_id))
            barrier.wait(timeout=10)
            try:
                result = save_design(
                    db,
                    task_id=task_id,
                    session_id=session_id,
                    payload=HomeDesignSaveRequest(
                        base_version=0, client_mutation_id=key, document=document()
                    ),
                )
                return result.model_dump(mode="json")
            except SpatialConflict as exc:
                db.rollback()
                return {"conflict": exc.code, "current_version": exc.current_version}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["same", "same" if same_key else "other"]))
    if same_key:
        assert results[0] == results[1]
        assert results[0]["version"] == 1
    else:
        assert sum("version" in result for result in results) == 1
        assert {
            "conflict": "home_design_version_conflict",
            "current_version": 1,
        } in results
    with factory() as db:
        rows = db.scalars(
            select(HomeDesignVersion).where(HomeDesignVersion.task_id == task_id)
        ).all()
        assert len(rows) == 1
        assert rows[0].version == 1
        assert rows[0].document_json["space_version"] == 1
        assert db.get(HomeDesign, task_id).current_version == 1


def _save_home_v1(factory, task_id, session_id):
    with factory() as db:
        value = document()
        value["objects"] = []
        return save_design(
            db,
            task_id=task_id,
            session_id=session_id,
            payload=HomeDesignSaveRequest(
                base_version=0,
                client_mutation_id="agent-home-v1",
                document=value,
            ),
        )


def _add_commercial_asset(factory, task_id, created_product_ids):
    with factory() as db:
        now = datetime.now(timezone.utc)
        product = Product(
            sku=f"MYSQL-D02-{task_id}",
            name="MySQL D02 隔离椅",
            price=680,
            price_max=680,
            is_active=True,
            record_version=1,
            data_origin="merchant",
            source_name="MySQL D02 隔离目录",
            source_product_id=f"mysql-d02-{task_id}",
            source_retrieved_at=now - timedelta(days=1),
            price_observed_at=now - timedelta(days=1),
            verification_status="verified",
            verified_at=now - timedelta(hours=1),
            verified_by="mysql-d02-reviewer",
            data_version="mysql-d02-v1",
            availability_status="in_stock",
            stock_quantity=5,
            region_codes=["CN-SH"],
            price_valid_from=now - timedelta(days=1),
            price_valid_to=now + timedelta(days=1),
        )
        db.add(product)
        db.flush()
        snapshot = {
            "kind": "product",
            "source_id": product.id,
            "source_version": 1,
            "name": product.name,
            "size": {"width": 0.5, "height": 0.8, "depth": 0.5},
            "material": {"name": "短绒", "color": "#eeeeee"},
            "model_spec": {"test_only": True},
            "source_summary": {
                "sku": product.sku,
                "data_origin": "merchant",
                "data_version": product.data_version,
                "verification_status": "verified",
            },
        }
        asset = HomeDesignAsset(
            task_id=task_id,
            client_mutation_id="mysql-d02-asset",
            request_digest="0" * 64,
            snapshot_json=snapshot,
            content_digest=asset_digest(snapshot),
        )
        db.add(asset)
        db.commit()
        created_product_ids.add(product.id)
        return asset.id, product.id


def _agent_client(factory):
    app = FastAPI()
    app.include_router(home_design_agent.router, prefix="/api/design/tasks")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _agent_payload(key, asset_id):
    return {
        "client_turn_id": key,
        "base_version": 1,
        "space_version": 1,
        "message": "在客厅放入已授权椅子",
        "region": "CN-SH",
        "budget_max": 1000,
        "allowed_asset_ids": [asset_id],
    }


def _asset_plan(asset_id):
    return HomeDesignAgentPlan.model_validate(
        {
            "outcome": "proposal",
            "message": "待确认候选",
            "operations": [
                {
                    "type": "add_asset_object",
                    "id": "mysql-d02-chair",
                    "asset_id": asset_id,
                    "room_id": "r1",
                    "position": {"x": 2.5, "y": 0, "z": 2.0},
                    "rotation": 0,
                }
            ],
        }
    )


def test_mysql_home_agent_discards_candidate_when_product_price_changes(
    mysql_context, monkeypatch
):
    factory, task_id, session_id, created_product_ids = mysql_context
    _save_home_v1(factory, task_id, session_id)
    asset_id, product_id = _add_commercial_asset(
        factory, task_id, created_product_ids
    )
    calls = 0

    def planner(**_kwargs):
        nonlocal calls
        calls += 1
        with factory() as db:
            product = db.get(Product, product_id)
            product.price = 700
            db.commit()
        return _asset_plan(asset_id)

    monkeypatch.setattr(llm_service, "plan_home_design", planner)
    with _agent_client(factory) as client:
        response = client.post(
            f"/api/design/tasks/{task_id}/home-design/agent-turns",
            headers={"X-Session-ID": session_id},
            json=_agent_payload("mysql-price-drift", asset_id),
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "home_agent_version_conflict"
    assert calls == 1
    with factory() as db:
        turns = db.scalars(
            select(HomeDesignAgentTurn).where(HomeDesignAgentTurn.task_id == task_id)
        ).all()
        assert len(turns) == 1
        assert turns[0].status == "failed"
        assert turns[0].response_json is None
        assert db.get(HomeDesign, task_id).current_version == 1
        assert not db.scalars(
            select(ModelCallLedger).where(ModelCallLedger.task_id == task_id)
        ).all()


def test_mysql_home_agent_same_turn_concurrency_has_one_reservation_and_no_double_billing(
    mysql_context, monkeypatch
):
    factory, task_id, session_id, created_product_ids = mysql_context
    _save_home_v1(factory, task_id, session_id)
    asset_id, _ = _add_commercial_asset(factory, task_id, created_product_ids)
    started = Event()
    release = Event()
    calls = 0

    def planner(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(15)
        return _asset_plan(asset_id)

    monkeypatch.setattr(llm_service, "plan_home_design", planner)
    url = f"/api/design/tasks/{task_id}/home-design/agent-turns"
    headers = {"X-Session-ID": session_id}
    body = _agent_payload("mysql-same-turn", asset_id)

    def post():
        with _agent_client(factory) as client:
            response = client.post(url, headers=headers, json=body)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post)
        assert started.wait(15)
        second = pool.submit(post)
        second_result = second.result(timeout=15)
        release.set()
        first_result = first.result(timeout=15)

    assert calls == 1
    assert {first_result[0], second_result[0]} == {200, 409}
    failed = second_result if second_result[0] == 409 else first_result
    assert failed[1]["detail"]["code"] == "home_agent_running"
    succeeded = first_result if first_result[0] == 200 else second_result
    assert succeeded[1]["outcome"] == "proposal"
    with factory() as db:
        turns = db.scalars(
            select(HomeDesignAgentTurn).where(HomeDesignAgentTurn.task_id == task_id)
        ).all()
        assert len(turns) == 1
        assert turns[0].status == "completed"
        events = db.scalars(
            select(TaskExecutionEvent).where(
                TaskExecutionEvent.task_id == task_id,
                TaskExecutionEvent.event_code == "agent.home_design.completed",
            )
        ).all()
        assert len(events) == 1
        assert events[0].billing_status == "not_billable"
        assert events[0].cost_cny is None
        assert not db.scalars(
            select(ModelCallLedger).where(ModelCallLedger.task_id == task_id)
        ).all()
