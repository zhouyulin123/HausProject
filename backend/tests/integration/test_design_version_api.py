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
from app.services.design_version_service import persist_generation


@pytest.fixture
def version_api_context():
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
        db.add(task)
        db.commit()
        attach_task(db, owner.id, task.id)
        persist_generation(
            db,
            task=task,
            plans=[
                {
                    "id": "plan-a",
                    "name": "暖居方案",
                    "style": "奶油风",
                    "shopQuote": {
                        "furnitureTotal": 18000,
                        "customTotal": 12000,
                        "total": 30000,
                    },
                }
            ],
            generator="llm",
            workflow_trace=[
                {
                    "node": "validate_quality",
                    "status": "completed",
                    "duration_ms": 2,
                    "source": "deterministic",
                }
            ],
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
def test_owner_can_restore_design_revision(version_api_context):
    client, owner_id, _, task_id = version_api_context

    response = client.get(
        f"/api/design/tasks/{task_id}/versions/1",
        headers={"X-Session-ID": owner_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["requirement"]["rooms"] == ["客厅"]
    assert body["workflow_trace"][0]["node"] == "validate_quality"
    assert body["plans"][0]["id"] == "plan-a"
    assert body["plans"][0]["planVersionId"] > 0
    assert body["plans"][0]["shopQuote"]["total"] == 30000


@pytest.mark.integration
def test_latest_result_exposes_plan_version_id(version_api_context):
    client, owner_id, _, task_id = version_api_context

    response = client.get(
        f"/api/design/tasks/{task_id}/result",
        headers={"X-Session-ID": owner_id},
    )

    assert response.status_code == 200
    assert response.json()["plans"][0]["planVersionId"] > 0


@pytest.mark.integration
def test_version_list_returns_quote_range(version_api_context):
    client, owner_id, _, task_id = version_api_context

    response = client.get(
        f"/api/design/tasks/{task_id}/versions",
        headers={"X-Session-ID": owner_id},
    )

    assert response.status_code == 200
    assert response.json()["revisions"] == [
        {
            "version": 1,
            "generator": "llm",
            "status": "completed",
            "plan_count": 1,
            "quote_min": 30000,
            "quote_max": 30000,
            "created_at": response.json()["revisions"][0]["created_at"],
        }
    ]


@pytest.mark.integration
def test_foreign_session_cannot_restore_revision(version_api_context):
    client, _, stranger_id, task_id = version_api_context

    response = client.get(
        f"/api/design/tasks/{task_id}/versions/1",
        headers={"X-Session-ID": stranger_id},
    )

    assert response.status_code == 404
