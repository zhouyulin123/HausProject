import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import tasks
from app.db.database import Base, get_db
from app.db.models import DesignResult, DesignTask
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)


@pytest.fixture
def session_access_context():
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
        task = DesignTask(status="completed", progress=100)
        db.add(task)
        db.commit()
        attach_task(db, owner.id, task.id)
        db.add(
            DesignResult(
                task_id=task.id,
                plans_json=[],
                generator="template",
            )
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
        yield client, owner_id, stranger_id, task_id


@pytest.mark.integration
@pytest.mark.parametrize(
    ("method", "path_suffix", "json_body"),
    [
        ("get", "", None),
        ("get", "/result", None),
        (
            "post",
            "/confirm-requirement",
            {"confirmed_requirement": {"rooms": ["客厅"]}},
        ),
        ("post", "/generate", {}),
    ],
)
def test_task_endpoints_reject_another_anonymous_session(
    session_access_context,
    method: str,
    path_suffix: str,
    json_body: dict | None,
):
    client, _, stranger_id, task_id = session_access_context

    response = client.request(
        method,
        f"/api/design/tasks/{task_id}{path_suffix}",
        headers={"X-Session-ID": stranger_id},
        json=json_body,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "设计任务不属于当前会话"


@pytest.mark.integration
def test_task_status_allows_owner_session(session_access_context):
    client, owner_id, _, task_id = session_access_context

    response = client.get(
        f"/api/design/tasks/{task_id}",
        headers={"X-Session-ID": owner_id},
    )

    assert response.status_code == 200
    assert response.json()["task_id"] == task_id


@pytest.mark.integration
def test_task_status_requires_session_header(session_access_context):
    client, _, _, task_id = session_access_context

    response = client.get(f"/api/design/tasks/{task_id}")

    assert response.status_code == 422
