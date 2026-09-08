from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import tasks
from app.db.database import Base, get_db
from app.db.models import DesignTask
from app.services import task_timeline_service
from app.services.anonymous_session_service import attach_task, create_anonymous_session


def test_task_timeline_is_owner_scoped_paginated_and_returns_safe_summaries():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with factory() as db:
        owner = create_anonymous_session(db)
        stranger = create_anonymous_session(db)
        task = DesignTask(status="completed", progress=100)
        db.add(task)
        db.flush()
        attach_task(db, owner.id, task.id)
        task_timeline_service.append_event(
            db,
            task_id=task.id,
            source_type="agent",
            source_id=1,
            attempt=None,
            event_code="agent.turn.completed",
            billing_status="not_billable",
            cost_cny=None,
            event_key="agent:1:completed",
        )
        task_timeline_service.append_event(
            db,
            task_id=task.id,
            source_type="generation",
            source_id=2,
            attempt=1,
            event_code="generation.completed",
            billing_status="metered",
            cost_cny=2.5,
            event_key="generation:2:a1:completed",
        )
        task_timeline_service.append_event(
            db,
            task_id=task.id,
            source_type="effect",
            source_id=3,
            attempt=1,
            event_code="effect.failed",
            billing_status="unknown",
            cost_cny=None,
            event_key="effect:3:a1:failed",
        )
        db.commit()
        owner_id = owner.id
        stranger_id = stranger.id
        task_id = task.id

    app = FastAPI()
    app.include_router(tasks.router, prefix="/api/design/tasks")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        first = client.get(
            f"/api/design/tasks/{task_id}/timeline?limit=2",
            headers={"X-Session-ID": owner_id},
        )
        before_cursor = first.json()["next_before_id"]
        older = client.get(
            f"/api/design/tasks/{task_id}/timeline?limit=2&before_id={before_cursor}",
            headers={"X-Session-ID": owner_id},
        )
        with factory() as db:
            task_timeline_service.append_event(
                db,
                task_id=task_id,
                source_type="blender",
                source_id=4,
                attempt=1,
                event_code="blender.completed",
                billing_status="unknown",
                cost_cny=None,
                event_key="blender:4:a1:completed",
            )
            db.commit()
        after_cursor = first.json()["events"][-1]["event_id"]
        newer = client.get(
            f"/api/design/tasks/{task_id}/timeline?limit=2&after_id={after_cursor}",
            headers={"X-Session-ID": owner_id},
        )
        ambiguous = client.get(
            f"/api/design/tasks/{task_id}/timeline?before_id=2&after_id=1",
            headers={"X-Session-ID": owner_id},
        )
        forbidden = client.get(
            f"/api/design/tasks/{task_id}/timeline",
            headers={"X-Session-ID": stranger_id},
        )

    assert first.status_code == 200
    assert [event["event_code"] for event in first.json()["events"]] == [
        "generation.completed",
        "effect.failed",
    ]
    assert first.json()["known_cost_cny"] == 2.5
    assert first.json()["has_unknown_cost"] is True
    assert first.json()["unknown_cost_event_count"] == 1
    assert before_cursor == first.json()["events"][0]["event_id"]
    assert first.json()["next_after_id"] is None
    assert [event["event_code"] for event in older.json()["events"]] == [
        "agent.turn.completed",
    ]
    assert older.json()["next_before_id"] is None
    assert [event["event_code"] for event in newer.json()["events"]] == [
        "blender.completed",
    ]
    assert newer.json()["next_after_id"] is None
    assert ambiguous.status_code == 422
    assert forbidden.status_code == 404
    serialized = str(first.json()) + str(older.json()) + str(newer.json())
    assert "prompt" not in serialized.lower()
    assert "exception" not in serialized.lower()
    assert "用户原始输入" not in serialized
    engine.dispose()
