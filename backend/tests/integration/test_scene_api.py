import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import scenes
from app.db.database import Base, get_db
from app.db.models import DesignTask, Product
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)
from app.services.design_version_service import persist_generation


def _scene_payload(*, sofa_x: float = 2.5, sku: str = "SOFA-001") -> dict:
    return {
        "schemaVersion": "1.0",
        "unit": "m",
        "coordinateSystem": "right-handed-y-up",
        "room": {
            "id": "living-room",
            "name": "客厅",
            "floorPolygon": [
                {"x": 0, "z": 0},
                {"x": 5, "z": 0},
                {"x": 5, "z": 4},
                {"x": 0, "z": 4},
            ],
            "ceilingHeight": 2.8,
            "wallThickness": 0.12,
        },
        "openings": [],
        "items": [
            {
                "instanceId": "sofa-main",
                "sku": sku,
                "transform": {
                    "position": {"x": sofa_x, "y": 0, "z": 3.2},
                    "rotation": {"x": 0, "y": 3.1416, "z": 0},
                    "scale": {"x": 1, "y": 1, "z": 1},
                },
            }
        ],
    }


@pytest.fixture
def scene_api_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        owner = create_anonymous_session(db)
        stranger = create_anonymous_session(db)
        task = DesignTask(
            status="completed",
            progress=100,
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
                    "shopQuote": {"total": 8999},
                }
            ],
            generator="llm",
        )
        db.commit()
        owner_id = owner.id
        stranger_id = stranger.id
        plan_version_id = revision.plans[0].id

    app = FastAPI()
    app.include_router(scenes.router, prefix="/api/design")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, owner_id, stranger_id, plan_version_id


@pytest.mark.integration
def test_scene_create_read_update_and_version_history(scene_api_context):
    client, owner_id, _, plan_version_id = scene_api_context
    headers = {"X-Session-ID": owner_id}

    created = client.post(
        f"/api/design/plan-versions/{plan_version_id}/scene",
        headers=headers,
        json={"scene": _scene_payload(), "source": "manual"},
    )

    assert created.status_code == 201
    body = created.json()
    assert body["plan_version_id"] == plan_version_id
    assert body["current_version"] == 1
    assert body["validation"]["valid"] is True
    scene_id = body["id"]

    restored = client.get(
        f"/api/design/scenes/{scene_id}",
        headers=headers,
    )
    assert restored.status_code == 200
    assert restored.json()["scene"]["items"][0]["sku"] == "SOFA-001"

    updated = client.put(
        f"/api/design/scenes/{scene_id}",
        headers=headers,
        json={
            "base_version": 1,
            "scene": _scene_payload(sofa_x=2.8),
            "source": "scene_agent",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["current_version"] == 2
    assert (
        updated.json()["scene"]["items"][0]["transform"]["position"]["x"]
        == 2.8
    )

    history = client.get(
        f"/api/design/scenes/{scene_id}/versions",
        headers=headers,
    )
    assert history.status_code == 200
    assert [item["version"] for item in history.json()["versions"]] == [2, 1]
    assert history.json()["versions"][0]["source"] == "scene_agent"


@pytest.mark.integration
def test_scene_update_rejects_stale_base_version(scene_api_context):
    client, owner_id, _, plan_version_id = scene_api_context
    headers = {"X-Session-ID": owner_id}
    created = client.post(
        f"/api/design/plan-versions/{plan_version_id}/scene",
        headers=headers,
        json={"scene": _scene_payload()},
    )
    scene_id = created.json()["id"]

    response = client.put(
        f"/api/design/scenes/{scene_id}",
        headers=headers,
        json={"base_version": 0, "scene": _scene_payload(sofa_x=3)},
    )

    assert response.status_code == 409


@pytest.mark.integration
def test_foreign_session_cannot_access_scene(scene_api_context):
    client, owner_id, stranger_id, plan_version_id = scene_api_context
    created = client.post(
        f"/api/design/plan-versions/{plan_version_id}/scene",
        headers={"X-Session-ID": owner_id},
        json={"scene": _scene_payload()},
    )

    response = client.get(
        f"/api/design/scenes/{created.json()['id']}",
        headers={"X-Session-ID": stranger_id},
    )

    assert response.status_code == 404


@pytest.mark.integration
def test_scene_rejects_sku_missing_from_product_catalog(scene_api_context):
    client, owner_id, _, plan_version_id = scene_api_context

    response = client.post(
        f"/api/design/plan-versions/{plan_version_id}/scene",
        headers={"X-Session-ID": owner_id},
        json={"scene": _scene_payload(sku="UNKNOWN-001")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["validation"]["valid"] is False
    assert response.json()["detail"]["validation"]["errors"][0]["code"] == (
        "unknown_sku"
    )

