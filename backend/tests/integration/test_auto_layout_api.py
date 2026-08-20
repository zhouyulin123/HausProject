import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import scenes
from app.db.database import Base, get_db
from app.db.models import DesignTask, LayoutRun, Product
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)
from app.services.design_version_service import persist_generation


@pytest.fixture
def auto_layout_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        owner = create_anonymous_session(db)
        task = DesignTask(
            status="completed",
            progress=100,
            space_type="客厅",
            confirmed_requirement_json={"rooms": ["客厅"]},
        )
        db.add_all(
            [
                task,
                Product(
                    sku="SOFA-001",
                    name="云朵三人沙发",
                    category="沙发",
                    room="客厅",
                    style="奶油风",
                    price=8999,
                    is_active=True,
                    model_width_mm=2200,
                    model_height_mm=850,
                    model_depth_mm=950,
                ),
                Product(
                    sku="TV-CAB-001",
                    name="电视收纳柜",
                    category="柜子",
                    room="客厅",
                    style="奶油风",
                    price=3600,
                    is_active=True,
                    model_width_mm=1600,
                    model_height_mm=1900,
                    model_depth_mm=400,
                ),
                Product(
                    sku="TEA-001",
                    name="岩板茶几",
                    category="茶几",
                    room="客厅",
                    style="奶油风",
                    price=1200,
                    is_active=True,
                    model_width_mm=1000,
                    model_height_mm=420,
                    model_depth_mm=550,
                ),
            ]
        )
        db.commit()
        attach_task(db, owner.id, task.id)
        revision = persist_generation(
            db,
            task=task,
            plans=[
                {
                    "id": "plan-a",
                    "name": "暖居方案",
                    "style": "奶油风",
                    "shopQuote": {"total": 13799},
                    "furnitureSuggestions": [
                        {"sku": "SOFA-001", "quantity": 1},
                        {"sku": "TV-CAB-001", "quantity": 1},
                        {"sku": "TEA-001", "quantity": 1},
                    ],
                }
            ],
            generator="llm",
        )
        db.commit()
        owner_id = owner.id
        plan_version_id = revision.plans[0].id

    app = FastAPI()
    app.include_router(scenes.router, prefix="/api/design")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, owner_id, plan_version_id, factory


@pytest.mark.integration
def test_auto_layout_generates_editable_scene(auto_layout_context):
    client, owner_id, plan_version_id, _ = auto_layout_context

    resp = client.post(
        f"/api/design/plan-versions/{plan_version_id}/auto-layout",
        headers={"X-Session-ID": owner_id},
        json={},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["plan_version_id"] == plan_version_id
    assert body["source"] == "auto_layout"
    assert body["validation"]["valid"] is True

    items = {item["sku"]: item for item in body["scene"]["items"]}
    assert len(items) == 3

    # 沙发靠后墙（z 负），电视柜靠前墙（z 正）且面向沙发
    assert items["SOFA-001"]["transform"]["position"]["z"] < 0
    assert items["TV-CAB-001"]["transform"]["position"]["z"] > 0
    assert (
        abs(abs(items["TV-CAB-001"]["transform"]["rotation"]["y"]) - math.pi)
        < 1e-3
    )
    # 家具带真实三维尺寸
    assert items["SOFA-001"]["dimensions"] == {
        "x": 2.2,
        "y": 0.85,
        "z": 0.95,
    }


@pytest.mark.integration
def test_auto_layout_is_idempotent(auto_layout_context):
    client, owner_id, plan_version_id, _ = auto_layout_context
    headers = {"X-Session-ID": owner_id}

    first = client.post(
        f"/api/design/plan-versions/{plan_version_id}/auto-layout",
        headers=headers,
        json={},
    )
    second = client.post(
        f"/api/design/plan-versions/{plan_version_id}/auto-layout",
        headers=headers,
        json={},
    )

    assert first.status_code == 201
    assert second.status_code in (200, 201)
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["current_version"] == 1


@pytest.mark.integration
def test_auto_layout_records_layout_run_metadata(auto_layout_context):
    client, owner_id, plan_version_id, factory = auto_layout_context

    resp = client.post(
        f"/api/design/plan-versions/{plan_version_id}/auto-layout",
        headers={"X-Session-ID": owner_id},
        json={},
    )
    assert resp.status_code == 201

    with factory() as db:
        run = db.scalars(
            select(LayoutRun).where(
                LayoutRun.plan_version_id == plan_version_id
            )
        ).first()
        assert run is not None
        assert run.best_score == 100
        assert run.best_valid is True
        assert run.furniture_count == 3
        assert run.candidate_count == 3
        assert run.issue_codes == []
        assert run.room_name == "客厅"
        assert run.source == "auto_layout"
        assert run.duration_ms is not None and run.duration_ms >= 0
        assert run.scene_version_id is not None
