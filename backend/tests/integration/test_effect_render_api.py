from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import render
from app.db.database import Base, get_db
from app.db.models import DesignTask, EffectRenderJob
from app.services import design_version_service
from app.services import sd_service
from app.services.anonymous_session_service import attach_task, create_anonymous_session


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
        db.commit()
        owner_id = owner.id
        task_id = task.id
        plan_version_id = revision.plans[0].id

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
    return engine, factory, TestClient(app), owner_id, task_id, plan_version_id


def test_render_api_requires_key_is_idempotent_and_supports_restore(monkeypatch):
    engine, factory, client, owner_id, task_id, plan_version_id = _context(monkeypatch)
    try:
        body = {"task_id": task_id, "plan_version_id": plan_version_id}
        missing = client.post(
            "/api/design/render", headers={"X-Session-ID": owner_id}, json=body
        )
        first = client.post(
            "/api/design/render",
            headers={"X-Session-ID": owner_id, "Idempotency-Key": "effect-1"},
            json=body,
        )
        same = client.post(
            "/api/design/render",
            headers={"X-Session-ID": owner_id, "Idempotency-Key": "effect-1"},
            json=body,
        )

        assert missing.status_code == 422
        assert first.status_code == 202
        assert same.status_code == 202
        assert same.json()["job_id"] == first.json()["job_id"]
        with factory() as db:
            assert db.query(EffectRenderJob).count() == 1

        job_id = first.json()["job_id"]
        detail = client.get(
            f"/api/design/render/{job_id}", headers={"X-Session-ID": owner_id}
        )
        restored = client.get(
            f"/api/design/render?plan_version_id={plan_version_id}",
            headers={"X-Session-ID": owner_id},
        )
        assert detail.status_code == 200
        assert restored.status_code == 200
        assert restored.json()["job_id"] == job_id
    finally:
        client.close()
        engine.dispose()


def test_render_api_same_key_changed_plan_conflicts_and_cancel_is_idempotent(monkeypatch):
    engine, _, client, owner_id, task_id, plan_version_id = _context(monkeypatch)
    try:
        headers = {"X-Session-ID": owner_id, "Idempotency-Key": "effect-2"}
        first = client.post(
            "/api/design/render",
            headers=headers,
            json={"task_id": task_id, "plan_version_id": plan_version_id},
        )
        conflict = client.post(
            "/api/design/render",
            headers=headers,
            json={"task_id": task_id, "plan_version_id": plan_version_id + 99},
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
