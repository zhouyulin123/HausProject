import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import tasks
from app.db.database import Base, get_db
from app.db.models import DesignTask
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)


@pytest.fixture
def async_generation_context(monkeypatch):
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
            status="confirmed",
            progress=50,
            confirmed_requirement_json={"rooms": ["客厅"]},
        )
        db.add(task)
        db.commit()
        attach_task(db, owner.id, task.id)
        owner_id = owner.id
        stranger_id = stranger.id
        task_id = task.id

    scheduled: list[int] = []
    monkeypatch.setattr(
        tasks,
        "execute_generation_run",
        scheduled.append,
    )

    app = FastAPI()
    app.include_router(tasks.router, prefix="/api/design/tasks")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, owner_id, stranger_id, task_id, scheduled


@pytest.mark.integration
def test_owner_can_queue_and_query_persistent_generation(
    async_generation_context,
):
    client, owner_id, _, task_id, scheduled = async_generation_context

    queued = client.post(
        f"/api/design/tasks/{task_id}/generate-async",
        headers={"X-Session-ID": owner_id},
    )
    status = client.get(
        f"/api/design/tasks/{task_id}/generation",
        headers={"X-Session-ID": owner_id},
    )

    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"
    assert scheduled == [queued.json()["run_id"]]
    assert status.status_code == 200
    assert status.json() == {
        "run_id": queued.json()["run_id"],
        "attempt": 1,
        "status": "queued",
        "progress": 0,
        "current_node": "queued",
        "generator": None,
        "error_message": None,
        "events": [],
    }


@pytest.mark.integration
def test_foreign_session_cannot_queue_generation(async_generation_context):
    client, _, stranger_id, task_id, scheduled = async_generation_context

    response = client.post(
        f"/api/design/tasks/{task_id}/generate-async",
        headers={"X-Session-ID": stranger_id},
    )

    assert response.status_code == 404
    assert scheduled == []
