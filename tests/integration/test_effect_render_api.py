from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import render
from app.db.database import Base, get_db
from app.db.models import (
    DesignScene,
    DesignSceneVersion,
    DesignTask,
    EffectRenderJob,
)
from app.services import design_version_service
from app.services import sd_service
from app.services.anonymous_session_service import attach_task, create_anonymous_session
from app.schemas.scenes import SceneDocument


def _scene_payload(*, sku: str | None = None) -> dict:
    items = []
    if sku is not None:
        items.append(
            {
                "instanceId": "item-main",
                "sku": sku,
                "dimensions": {"x": 2.0, "y": 0.8, "z": 1.0},
                "transform": {"position": {"x": 2.5, "y": 0.4, "z": 2.0}},
            }
        )
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
        "items": items,
    }


def _context(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = create_anonymous_session(db)
        task = DesignTask(status="completed", progress=100)
        db.add(task)
        db.flush()
        attach_task(db, owner.id, task.id)
        revision = design_version_service.persist_generation(
            db,
            task=task,
            plans=[{"id": "plan-a", "name": "方案 A", "style": "原木风"}],
            generator="test",
        )
        plan = revision.plans[0]
        scene = DesignScene(plan_version_id=plan.id, current_version=1)
        db.add(scene)
        db.flush()
        db.add(
            DesignSceneVersion(
                scene_id=scene.id,
                version=1,
                scene_json=_scene_payload(sku="SOFA-001"),
                validation_json={"valid": True},
            )
        )
        db.commit()
        owner_id = owner.id
        task_id = task.id
        plan_version_id = revision.plans[0].id
        scene_id = scene.id

    monkeypatch.setattr(
        sd_service,
        "render_effect_image",
        lambda *_: (_ for _ in ()).throw(AssertionError("API 不得调用 SD")),
    )
    app = FastAPI()
    app.include_router(render.router, prefix="/api/design/render")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return (
        engine,
        factory,
        TestClient(app),
        owner_id,
        task_id,
        plan_version_id,
        scene_id,
    )


def test_render_api_requires_key_is_idempotent_and_supports_restore(monkeypatch):
    engine, factory, client, owner_id, task_id, plan_version_id, scene_id = _context(
        monkeypatch
    )
    try:
        body = {
            "task_id": task_id,
            "plan_version_id": plan_version_id,
            "scene_id": scene_id,
            "scene_version": 1,
        }
        missing = client.post(
            "/api/design/render", headers={"X-Session-ID": owner_id}, json=body
        )
        first = client.post(
            "/api/design/render",
            headers={
                "X-Session-ID": owner_id,
                "Idempotency-Key": "effect-1",
                "X-Request-ID": "effect-trace-first-001",
            },
            json=body,
        )
        same = client.post(
            "/api/design/render",
            headers={
                "X-Session-ID": owner_id,
                "Idempotency-Key": "effect-1",
                "X-Request-ID": "effect-trace-retry-002",
            },
            json=body,
        )

        assert missing.status_code == 422
        assert first.status_code == 202
        assert same.status_code == 202
        assert same.json()["job_id"] == first.json()["job_id"]
        assert first.json()["request_id"] == "effect-trace-first-001"
        assert same.json()["request_id"] == "effect-trace-first-001"
        with factory() as db:
            assert db.query(EffectRenderJob).count() == 1

        job_id = first.json()["job_id"]
        detail = client.get(
            f"/api/design/render/{job_id}", headers={"X-Session-ID": owner_id}
        )
        restored = client.get(
            "/api/design/render"
            f"?plan_version_id={plan_version_id}&scene_id={scene_id}&scene_version=1",
            headers={"X-Session-ID": owner_id},
        )
        assert detail.status_code == 200
        assert detail.json()["request_id"] == "effect-trace-first-001"
        assert restored.status_code == 200
        assert restored.json()["request_id"] == "effect-trace-first-001"
        assert restored.json()["job_id"] == job_id
    finally:
        client.close()
        engine.dispose()


def test_render_api_same_key_changed_plan_conflicts_and_cancel_is_idempotent(
    monkeypatch,
):
    engine, _, client, owner_id, task_id, plan_version_id, scene_id = _context(
        monkeypatch
    )
    try:
        headers = {"X-Session-ID": owner_id, "Idempotency-Key": "effect-2"}
        first = client.post(
            "/api/design/render",
            headers=headers,
            json={
                "task_id": task_id,
                "plan_version_id": plan_version_id,
                "scene_id": scene_id,
                "scene_version": 1,
            },
        )
        conflict = client.post(
            "/api/design/render",
            headers=headers,
            json={
                "task_id": task_id,
                "plan_version_id": plan_version_id + 99,
                "scene_id": scene_id,
                "scene_version": 1,
            },
        )
        job_id = first.json()["job_id"]
        cancelled = client.post(
            f"/api/design/render/{job_id}/cancel",
            headers={"X-Session-ID": owner_id},
        )
        cancelled_again = client.post(
            f"/api/design/render/{job_id}/cancel",
            headers={"X-Session-ID": owner_id},
        )

        assert conflict.status_code == 409
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled_again.json()["status"] == "cancelled"
    finally:
        client.close()
        engine.dispose()


def test_render_api_binds_exact_scene_snapshot_and_rejects_changed_scene_for_same_key(
    monkeypatch,
):
    engine, factory, client, owner_id, task_id, plan_version_id, scene_id = _context(
        monkeypatch
    )
    try:
        with factory() as db:
            scene = db.get(DesignScene, scene_id)
            scene.current_version = 2
            db.add(
                DesignSceneVersion(
                    scene_id=scene.id,
                    version=2,
                    scene_json=_scene_payload(sku="NEW-001"),
                    validation_json={"valid": True},
                )
            )
            db.commit()

        headers = {
            "X-Session-ID": owner_id,
            "Idempotency-Key": "effect-scene-1",
        }
        first = client.post(
            "/api/design/render",
            headers=headers,
            json={
                "task_id": task_id,
                "plan_version_id": plan_version_id,
                "scene_id": scene_id,
                "scene_version": 1,
            },
        )
        changed = client.post(
            "/api/design/render",
            headers=headers,
            json={
                "task_id": task_id,
                "plan_version_id": plan_version_id,
                "scene_id": scene_id,
                "scene_version": 2,
            },
        )
        partial = client.post(
            "/api/design/render",
            headers={
                "X-Session-ID": owner_id,
                "Idempotency-Key": "effect-scene-partial",
            },
            json={
                "task_id": task_id,
                "plan_version_id": plan_version_id,
                "scene_id": scene_id,
            },
        )

        assert first.status_code == 202
        assert first.json()["scene_id"] == scene_id
        assert first.json()["scene_version"] == 1
        assert first.json()["scene_version_id"] > 0
        assert first.json()["scene_digest"].startswith("sha256:")
        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "idempotency_conflict"
        assert partial.status_code == 422
        with factory() as db:
            job = db.query(EffectRenderJob).one()
            assert job.scene_id == scene_id
            assert job.scene_version == 1
            assert job.scene_version_id == first.json()["scene_version_id"]
            assert job.scene_snapshot_json == SceneDocument.model_validate(
                _scene_payload(sku="SOFA-001")
            ).model_dump(by_alias=True, mode="json")
            assert job.scene_digest == first.json()["scene_digest"]
    finally:
        client.close()
        engine.dispose()


def test_render_api_rejects_scene_from_a_different_plan(monkeypatch):
    engine, factory, client, owner_id, task_id, plan_version_id, _ = _context(
        monkeypatch
    )
    try:
        with factory() as db:
            task = db.get(DesignTask, task_id)
            revision = design_version_service.persist_generation(
                db,
                task=task,
                plans=[{"id": "plan-b", "name": "方案 B", "style": "现代"}],
                generator="test",
            )
            foreign_plan = revision.plans[0]
            scene = DesignScene(plan_version_id=foreign_plan.id, current_version=1)
            db.add(scene)
            db.flush()
            db.add(
                DesignSceneVersion(
                    scene_id=scene.id,
                    version=1,
                    scene_json=_scene_payload(),
                    validation_json={"valid": True},
                )
            )
            db.commit()
            scene_id = scene.id

        response = client.post(
            "/api/design/render",
            headers={
                "X-Session-ID": owner_id,
                "Idempotency-Key": "effect-wrong-plan",
            },
            json={
                "task_id": task_id,
                "plan_version_id": plan_version_id,
                "scene_id": scene_id,
                "scene_version": 1,
            },
        )

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "scene_snapshot_not_found"
    finally:
        client.close()
        engine.dispose()
