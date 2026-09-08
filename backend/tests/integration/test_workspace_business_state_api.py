from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.api.routes import design_agent, scenes, tasks
from app.db.database import Base, get_db
from app.db.models import (
    CustomFurnitureDraftMutation,
    DesignAgentTurn,
    DesignFeedbackEvent,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    DesignTask,
    Product,
)
from app.schemas.scenes import SceneDocument
from app.services import catalog_service, design_version_service, scene_service
from app.services.anonymous_session_service import attach_task, create_anonymous_session


NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


def _product(sku: str, *, price: int, width: int = 800, depth: int = 800) -> Product:
    return Product(
        sku=sku,
        name=sku,
        category="沙发" if sku.startswith("SOFA") else "茶几",
        room="客厅",
        style="现代",
        material="实木",
        size=f"{width}x800x{depth}mm",
        price=price,
        is_active=True,
        data_origin="merchant_verified",
        verification_status="verified",
        availability_status="in_stock",
        region_codes=["CN-SH"],
        stock_quantity=10,
        lead_time_days_min=1,
        lead_time_days_max=3,
        price_valid_from=NOW - timedelta(days=1),
        price_valid_to=NOW + timedelta(days=30),
        verified_at=NOW,
        verified_by="catalog-owner",
        data_version="catalog-v1",
        record_version=1,
        model_width_mm=width,
        model_height_mm=800,
        model_depth_mm=depth,
    )


def _scene_payload(*, room_size: float = 5.0) -> dict:
    return {
        "schemaVersion": "1.0",
        "unit": "m",
        "coordinateSystem": "right-handed-y-up",
        "room": {
            "id": "living-room",
            "name": "客厅",
            "floorPolygon": [
                {"x": 0, "z": 0},
                {"x": room_size, "z": 0},
                {"x": room_size, "z": room_size},
                {"x": 0, "z": room_size},
            ],
            "ceilingHeight": 2.8,
            "wallThickness": 0.12,
        },
        "openings": [],
        "items": [
            {
                "instanceId": "sofa-main",
                "sku": "SOFA-001",
                "category": "沙发",
                "dimensions": {"x": 0.8, "y": 0.8, "z": 0.8},
                "transform": {
                    "position": {"x": 1.0, "y": 0.4, "z": 1.0},
                    "rotation": {"x": 0, "y": 0.75, "z": 0},
                    "scale": {"x": 1, "y": 1, "z": 1},
                },
            }
        ],
    }


@pytest.fixture
def workspace_state_context():
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
            active_mode="catalog_design",
            confirmed_requirement_json={
                "rooms": ["客厅"],
                "delivery_region": "CN-SH",
                "budget_max": 20_000,
            },
        )
        db.add_all([
            task,
            _product("SOFA-001", price=6000),
            _product("SOFA-002", price=6500),
            _product("TABLE-001", price=2000),
            _product("TABLE-HUGE", price=1000, width=6000, depth=6000),
        ])
        db.commit()
        attach_task(db, owner.id, task.id)
        plan = {
            "id": "plan-a",
            "name": "当前方案",
            "style": "现代",
            "furnitureSuggestions": [{"sku": "SOFA-001", "quantity": 1}],
        }
        catalog_service.verify_and_enrich_plans(
            db,
            [plan],
            at=NOW,
            region="CN-SH",
            budget_max=20_000,
        )
        revision = design_version_service.persist_generation(
            db,
            task=task,
            plans=[plan],
            generator="agent",
        )
        scene, _ = scene_service.create_scene(
            db,
            plan_version=revision.plans[0],
            document=SceneDocument.model_validate(_scene_payload()),
            source="manual",
        )
        db.commit()
        task_id = task.id
        owner_id = owner.id
        stranger_id = stranger.id
        plan_version_id = revision.plans[0].id
        scene_id = scene.id

    app = FastAPI()
    app.include_router(tasks.router, prefix="/api/design/tasks")
    app.include_router(design_agent.router, prefix="/api/design/tasks")
    app.include_router(scenes.router, prefix="/api/design")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield {
            "client": client,
            "factory": factory,
            "task_id": task_id,
            "owner": owner_id,
            "stranger": stranger_id,
            "plan_version_id": plan_version_id,
            "scene_id": scene_id,
        }


def _mutation_url(context) -> str:
    return f"/api/design/tasks/{context['task_id']}/plan-mutations"


@pytest.mark.integration
def test_adopt_creates_versioned_plan_scene_and_derived_feedback_idempotently(
    workspace_state_context,
):
    context = workspace_state_context
    payload = {
        "client_mutation_id": "workspace:adopt:001",
        "base_revision_version": 1,
        "plan_version_id": context["plan_version_id"],
        "action": "adopt",
        "target_sku": "TABLE-001",
        "placement_mode": "auto_place",
        "room_id": "living-room",
    }
    headers = {"X-Session-ID": context["owner"]}

    first = context["client"].post(_mutation_url(context), headers=headers, json=payload)
    duplicate = context["client"].post(_mutation_url(context), headers=headers, json=payload)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json() == first.json()
    body = first.json()
    assert body["revision_version"] == 2
    assert body["plan"]["planVersionId"] != context["plan_version_id"]
    assert {item["sku"] for item in body["scene"]["scene"]["items"]} == {
        "SOFA-001",
        "TABLE-001",
    }
    persisted_sofa = next(
        item for item in body["scene"]["scene"]["items"] if item["sku"] == "SOFA-001"
    )
    assert persisted_sofa["transform"] == _scene_payload()["items"][0]["transform"]
    assert body["feedback"]["action_type"] == "adopt"
    assert body["feedback"]["plan_version_id"] == body["plan"]["planVersionId"]

    with context["factory"]() as db:
        assert db.scalar(select(func.count(DesignRevision.id))) == 2
        assert db.scalar(select(func.count(DesignFeedbackEvent.id))) == 1


@pytest.mark.integration
def test_catalog_mutation_rejects_stale_and_foreign_requests(workspace_state_context):
    context = workspace_state_context
    payload = {
        "client_mutation_id": "workspace-adopt-stale",
        "base_revision_version": 9,
        "plan_version_id": context["plan_version_id"],
        "action": "adopt",
        "target_sku": "TABLE-001",
        "placement_mode": "auto_place",
    }

    stale = context["client"].post(
        _mutation_url(context),
        headers={"X-Session-ID": context["owner"]},
        json=payload,
    )
    foreign = context["client"].post(
        _mutation_url(context),
        headers={"X-Session-ID": context["stranger"]},
        json={**payload, "client_mutation_id": "workspace-adopt-foreign"},
    )

    assert stale.status_code == 409
    assert foreign.status_code == 404


@pytest.mark.integration
def test_auto_place_failure_is_atomic(workspace_state_context):
    context = workspace_state_context
    response = context["client"].post(
        _mutation_url(context),
        headers={"X-Session-ID": context["owner"]},
        json={
            "client_mutation_id": "workspace-adopt-no-position",
            "base_revision_version": 1,
            "plan_version_id": context["plan_version_id"],
            "action": "adopt",
            "target_sku": "TABLE-HUGE",
            "placement_mode": "auto_place",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "placement_not_found"
    with context["factory"]() as db:
        assert db.scalar(select(func.count(DesignRevision.id))) == 1
        assert db.scalar(select(func.count(DesignScene.id))) == 1
        assert db.scalar(select(func.count(DesignSceneVersion.id))) == 1
        assert db.scalar(select(func.count(DesignFeedbackEvent.id))) == 0


@pytest.mark.integration
@pytest.mark.parametrize("action", ["remove", "replace"])
def test_remove_and_replace_target_exact_instance_and_replace_keeps_transform(
    workspace_state_context,
    action,
):
    context = workspace_state_context
    payload = {
        "client_mutation_id": f"workspace-{action}-001",
        "base_revision_version": 1,
        "plan_version_id": context["plan_version_id"],
        "action": action,
        "source_instance_id": "sofa-main",
        "room_id": "living-room",
    }
    if action == "replace":
        payload["target_sku"] = "SOFA-002"

    response = context["client"].post(
        _mutation_url(context),
        headers={"X-Session-ID": context["owner"]},
        json=payload,
    )

    assert response.status_code == 200
    items = response.json()["scene"]["scene"]["items"]
    assert all(item["instanceId"] != "sofa-main" for item in items) if action == "remove" else True
    if action == "replace":
        assert len(items) == 1
        assert items[0]["sku"] == "SOFA-002"
        assert items[0]["transform"] == _scene_payload()["items"][0]["transform"]


@pytest.mark.integration
def test_move_update_is_idempotent_and_updates_agent_checkpoint_and_feedback(
    workspace_state_context,
):
    context = workspace_state_context
    moved = _scene_payload()
    moved["items"][0]["transform"]["position"]["x"] = 2.5
    payload = {
        "base_version": 1,
        "scene": moved,
        "source": "manual",
        "client_mutation_id": "workspace-move-001",
        "moved_instance_ids": ["sofa-main"],
        "feedback_room_id": "living-room",
    }
    url = f"/api/design/scenes/{context['scene_id']}"
    headers = {"X-Session-ID": context["owner"]}

    first = context["client"].put(url, headers=headers, json=payload)
    duplicate = context["client"].put(url, headers=headers, json=payload)
    checkpoint = context["client"].get(
        f"/api/design/tasks/{context['task_id']}/agent-state",
        headers=headers,
    )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["current_version"] == 2
    assert checkpoint.json()["scene_ref"] == {
        "scene_id": context["scene_id"],
        "version": 2,
    }
    with context["factory"]() as db:
        assert db.scalar(select(func.count(DesignSceneVersion.id))) == 2
        assert db.scalar(select(func.count(DesignFeedbackEvent.id))) == 1


@pytest.mark.integration
def test_custom_draft_is_versioned_idempotent_and_task_isolated(workspace_state_context):
    context = workspace_state_context
    payload = {
        "client_mutation_id": "custom-draft-001",
        "base_state_version": 0,
        "custom_furniture_spec": {
            "family": "table",
            "name": "餐桌草稿",
            "purpose": "dining_table",
            "material": "实木（橡木）",
            "dimensions": {"width_mm": 1600, "height_mm": 760, "depth_mm": 800},
            "structure": {
                "top_shape": "rectangle",
                "base_style": "four_leg",
                "support_count": 4,
                "seat_count": 6,
                "top_thickness_mm": 30,
                "edge_radius_mm": 8,
            },
        },
    }
    url = f"/api/design/tasks/{context['task_id']}/custom-furniture-draft"
    headers = {"X-Session-ID": context["owner"]}

    first = context["client"].put(url, headers=headers, json=payload)
    duplicate = context["client"].put(url, headers=headers, json=payload)
    checkpoint = context["client"].get(
        f"/api/design/tasks/{context['task_id']}/agent-state",
        headers=headers,
    )
    foreign = context["client"].put(
        url,
        headers={"X-Session-ID": context["stranger"]},
        json={**payload, "client_mutation_id": "custom-draft-foreign"},
    )

    assert first.status_code == 200
    assert duplicate.json() == first.json()
    assert first.json()["state_version"] == 1
    assert checkpoint.json()["custom_furniture_draft"] == payload["custom_furniture_spec"]
    assert checkpoint.json()["custom_furniture_draft_ref"] == {
        "client_mutation_id": payload["client_mutation_id"],
        "state_version": 1,
    }
    assert foreign.status_code == 404
    with context["factory"]() as db:
        assert db.scalar(select(func.count(DesignAgentTurn.id))) == 0
        assert db.scalar(select(func.count(CustomFurnitureDraftMutation.id))) == 1


@pytest.mark.integration
def test_custom_draft_conflict_returns_authoritative_draft_after_scene_move(
    workspace_state_context,
):
    context = workspace_state_context
    headers = {"X-Session-ID": context["owner"]}
    draft_url = f"/api/design/tasks/{context['task_id']}/custom-furniture-draft"
    first_spec = {
        "family": "table",
        "name": "第一版餐桌",
        "purpose": "dining_table",
        "material": "实木（橡木）",
        "dimensions": {"width_mm": 1600, "height_mm": 760, "depth_mm": 800},
        "structure": {
            "top_shape": "rectangle",
            "base_style": "four_leg",
            "support_count": 4,
            "seat_count": 6,
            "top_thickness_mm": 30,
            "edge_radius_mm": 8,
        },
    }
    first = context["client"].put(
        draft_url,
        headers=headers,
        json={
            "client_mutation_id": "draft-before-scene-move",
            "base_state_version": 0,
            "custom_furniture_spec": first_spec,
        },
    )
    assert first.status_code == 200

    moved = _scene_payload()
    moved["items"][0]["transform"]["position"]["x"] = 2.0
    moved_response = context["client"].put(
        f"/api/design/scenes/{context['scene_id']}",
        headers=headers,
        json={
            "base_version": 1,
            "scene": moved,
            "source": "manual",
            "client_mutation_id": "scene-between-drafts",
            "moved_instance_ids": ["sofa-main"],
            "feedback_room_id": "living-room",
        },
    )
    assert moved_response.status_code == 200

    second_spec = {**first_spec, "name": "第二版餐桌"}
    stale = context["client"].put(
        draft_url,
        headers=headers,
        json={
            "client_mutation_id": "draft-after-scene-move",
            "base_state_version": 1,
            "custom_furniture_spec": second_spec,
        },
    )

    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "agent_state_conflict"
    assert detail["state_version"] == 2
    assert detail["custom_furniture_draft"] == first_spec
    assert detail["scene_ref"] == {
        "scene_id": context["scene_id"],
        "version": 2,
    }

    retried = context["client"].put(
        draft_url,
        headers=headers,
        json={
            "client_mutation_id": "draft-after-scene-move-retry",
            "base_state_version": detail["state_version"],
            "custom_furniture_spec": second_spec,
        },
    )
    assert retried.status_code == 200
    assert retried.json()["state_version"] == 3


@pytest.mark.integration
def test_custom_draft_idempotency_key_rejects_different_payload(workspace_state_context):
    context = workspace_state_context
    headers = {"X-Session-ID": context["owner"]}
    url = f"/api/design/tasks/{context['task_id']}/custom-furniture-draft"
    payload = {
        "client_mutation_id": "draft-same-key",
        "base_state_version": 0,
        "custom_furniture_spec": {
            "family": "table",
            "name": "原始草稿",
            "purpose": "dining_table",
            "material": "实木（橡木）",
            "dimensions": {"width_mm": 1600, "height_mm": 760, "depth_mm": 800},
            "structure": {
                "top_shape": "rectangle",
                "base_style": "four_leg",
                "support_count": 4,
                "seat_count": 6,
                "top_thickness_mm": 30,
                "edge_radius_mm": 8,
            },
        },
    }
    assert context["client"].put(url, headers=headers, json=payload).status_code == 200
    changed = {
        **payload,
        "custom_furniture_spec": {
            **payload["custom_furniture_spec"],
            "name": "同键篡改草稿",
        },
    }

    response = context["client"].put(url, headers=headers, json=changed)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"
