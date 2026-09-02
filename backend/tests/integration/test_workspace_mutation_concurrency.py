from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from itertools import count
from threading import Barrier, BrokenBarrierError, local

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.api.routes import scenes, tasks
from app.db.database import Base, get_db
from app.db.models import (
    DesignFeedbackEvent,
    DesignPlanVersion,
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


def _product(sku: str, price: int) -> Product:
    return Product(
        sku=sku,
        name=sku,
        category="沙发" if sku.startswith("SOFA") else "茶几",
        room="客厅",
        style="现代",
        material="实木",
        size="800x800x800mm",
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
        model_width_mm=800,
        model_height_mm=800,
        model_depth_mm=800,
    )


def _scene(position_x: float = 1.0) -> dict:
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
                {"x": 5, "z": 5},
                {"x": 0, "z": 5},
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
                    "position": {"x": position_x, "y": 0.4, "z": 1.0},
                    "rotation": {"x": 0, "y": 0, "z": 0},
                    "scale": {"x": 1, "y": 1, "z": 1},
                },
            }
        ],
    }


@pytest.fixture
def file_workspace_factory(tmp_path):
    sequence = count(1)
    engines = []

    def create_context():
        database_path = tmp_path / f"workspace-concurrency-{next(sequence)}.db"
        engine = create_engine(
            f"sqlite+pysqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 5},
        )
        engines.append(engine)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            owner = create_anonymous_session(db)
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
            db.add_all(
                [
                    task,
                    _product("SOFA-001", 6000),
                    _product("SOFA-002", 6500),
                    _product("TABLE-001", 2000),
                ]
            )
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
                document=SceneDocument.model_validate(_scene()),
                source="manual",
            )
            db.commit()
            values = {
                "task_id": task.id,
                "owner": owner.id,
                "plan_version_id": revision.plans[0].id,
                "scene_id": scene.id,
            }

        app = FastAPI()
        app.include_router(tasks.router, prefix="/api/design/tasks")
        app.include_router(scenes.router, prefix="/api/design")

        def override_db():
            with factory() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        return {"app": app, "engine": engine, "factory": factory, **values}

    yield create_context
    for engine in engines:
        engine.dispose()


def _coordinate_query(engine, marker: str) -> None:
    barrier = Barrier(2)
    thread_state = local()

    @event.listens_for(engine, "after_cursor_execute")
    def wait_after_shared_read(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        del connection, cursor, parameters, context, executemany
        normalized = " ".join(statement.lower().split())
        if marker not in normalized or getattr(thread_state, "waited", False):
            return
        thread_state.waited = True
        try:
            barrier.wait(timeout=0.75)
        except BrokenBarrierError:
            pass


def _concurrent_requests(context, method: str, url: str, payloads: list[dict]):
    start = Barrier(2)

    def submit(payload: dict):
        start.wait()
        with TestClient(context["app"], raise_server_exceptions=False) as client:
            return client.request(
                method,
                url,
                headers={"X-Session-ID": context["owner"]},
                json=payload,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(submit, payloads))


def _plan_payload(context, client_id: str, sku: str = "TABLE-001") -> dict:
    return {
        "client_mutation_id": client_id,
        "base_revision_version": 1,
        "plan_version_id": context["plan_version_id"],
        "action": "adopt",
        "target_sku": sku,
        "placement_mode": "auto_place",
        "room_id": "living-room",
    }


@pytest.mark.integration
@pytest.mark.parametrize(
    ("second_id", "second_sku", "expected_statuses"),
    [
        ("concurrent-plan-same", "TABLE-001", [200, 200]),
        ("concurrent-plan-other", "SOFA-002", [200, 409]),
        ("concurrent-plan-same", "SOFA-002", [200, 409]),
    ],
)
def test_plan_mutation_concurrency_is_idempotent_and_atomic(
    file_workspace_factory,
    second_id,
    second_sku,
    expected_statuses,
):
    context = file_workspace_factory()
    _coordinate_query(
        context["engine"],
        "order by design_revisions.version desc",
    )
    payloads = [
        _plan_payload(context, "concurrent-plan-same"),
        _plan_payload(context, second_id, second_sku),
    ]

    responses = _concurrent_requests(
        context,
        "POST",
        f"/api/design/tasks/{context['task_id']}/plan-mutations",
        payloads,
    )

    assert sorted(response.status_code for response in responses) == expected_statuses
    assert all(response.status_code != 500 for response in responses)
    if expected_statuses == [200, 200]:
        assert responses[0].json() == responses[1].json()
    with context["factory"]() as db:
        assert db.scalar(select(func.count(DesignRevision.id))) == 2
        assert db.scalar(select(func.count(DesignPlanVersion.id))) == 2
        assert db.scalar(select(func.count(DesignScene.id))) == 2
        assert db.scalar(select(func.count(DesignSceneVersion.id))) == 2
        assert db.scalar(select(func.count(DesignFeedbackEvent.id))) == 1


def _scene_payload(client_id: str, position_x: float) -> dict:
    return {
        "base_version": 1,
        "scene": _scene(position_x),
        "source": "manual",
        "client_mutation_id": client_id,
        "moved_instance_ids": ["sofa-main"],
        "feedback_room_id": "living-room",
    }


@pytest.mark.integration
@pytest.mark.parametrize(
    ("second_id", "second_x", "expected_statuses"),
    [
        ("concurrent-scene-same", 2.0, [200, 200]),
        ("concurrent-scene-other", 3.0, [200, 409]),
        ("concurrent-scene-same", 3.0, [200, 409]),
    ],
)
def test_scene_mutation_concurrency_is_idempotent_and_atomic(
    file_workspace_factory,
    second_id,
    second_x,
    expected_statuses,
):
    context = file_workspace_factory()
    _coordinate_query(context["engine"], "from design_scenes join design_plan_versions")
    payloads = [
        _scene_payload("concurrent-scene-same", 2.0),
        _scene_payload(second_id, second_x),
    ]

    responses = _concurrent_requests(
        context,
        "PUT",
        f"/api/design/scenes/{context['scene_id']}",
        payloads,
    )

    assert sorted(response.status_code for response in responses) == expected_statuses
    assert all(response.status_code != 500 for response in responses)
    if expected_statuses == [200, 200]:
        assert responses[0].json() == responses[1].json()
    with context["factory"]() as db:
        assert db.scalar(select(func.count(DesignRevision.id))) == 1
        assert db.scalar(select(func.count(DesignScene.id))) == 1
        assert db.scalar(select(func.count(DesignSceneVersion.id))) == 2
        assert db.scalar(select(func.count(DesignFeedbackEvent.id))) == 1
