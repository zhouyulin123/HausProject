import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import design_agent
from app.db.database import Base, get_db
from app.db.models import ChatLog, DesignAgentEvent, DesignTask
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)


@pytest.fixture
def agent_api_context(monkeypatch):
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
            status="waiting_input",
            raw_user_input="帮我设计客厅",
            confirmed_requirement_json={"space_type": "客厅"},
            space_type="客厅",
        )
        db.add(task)
        db.commit()
        attach_task(db, owner.id, task.id)
        owner_id = owner.id
        stranger_id = stranger.id
        task_id = task.id

    app = FastAPI()
    app.include_router(
        design_agent.router,
        prefix="/api/design/tasks",
    )

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, factory, owner_id, stranger_id, task_id


@pytest.mark.integration
def test_agent_turn_pauses_persists_checkpoint_and_task_bound_chat(
    agent_api_context,
):
    client, factory, owner_id, _, task_id = agent_api_context

    response = client.post(
        f"/api/design/tasks/{task_id}/agent/turns",
        headers={"X-Session-ID": owner_id},
        json={"message": "继续设计", "intent": "design"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task_id
    assert payload["exit_reason"] == "waiting_user"
    assert payload["state"]["status"] == "waiting_input"
    assert [q["field"] for q in payload["pending_questions"]] == [
        "budget_max",
        "room_dimensions",
    ]
    assert payload["events"]

    with factory() as db:
        task = db.get(DesignTask, task_id)
        logs = db.scalars(
            select(ChatLog).where(ChatLog.task_id == task_id)
        ).all()
        events = db.scalars(
            select(DesignAgentEvent).where(
                DesignAgentEvent.task_id == task_id
            )
        ).all()
        assert task.agent_state_json["exit_reason"] == "waiting_user"
        assert task.agent_state_version == 1
        assert [log.role for log in logs] == ["user", "ai"]
        assert events


@pytest.mark.integration
def test_agent_turn_resumes_from_structured_answers(agent_api_context):
    client, _, owner_id, _, task_id = agent_api_context

    response = client.post(
        f"/api/design/tasks/{task_id}/agent/turns",
        headers={"X-Session-ID": owner_id},
        json={
            "message": "预算两万元，房间宽4米、深5米",
            "intent": "catalog_search",
            "answers": {
                "budget_max": 20000,
                "room_width_m": 4,
                "room_depth_m": 5,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["exit_reason"] == "completed"
    assert payload["state"]["facts"]["budget_max"] == 20000
    assert payload["state"]["facts"]["room_width_m"] == 4
    assert payload["result"]["candidate_count"] >= 0


@pytest.mark.integration
def test_agent_turn_rejects_foreign_task_before_execution(agent_api_context):
    client, _, _, stranger_id, task_id = agent_api_context

    response = client.post(
        f"/api/design/tasks/{task_id}/agent/turns",
        headers={"X-Session-ID": stranger_id},
        json={"message": "继续设计", "intent": "design"},
    )

    assert response.status_code == 404


@pytest.mark.integration
def test_agent_state_can_be_reloaded_after_page_refresh(agent_api_context):
    client, _, owner_id, _, task_id = agent_api_context
    client.post(
        f"/api/design/tasks/{task_id}/agent/turns",
        headers={"X-Session-ID": owner_id},
        json={"message": "继续设计", "intent": "design"},
    )

    response = client.get(
        f"/api/design/tasks/{task_id}/agent/state",
        headers={"X-Session-ID": owner_id},
    )

    assert response.status_code == 200
    assert response.json()["exit_reason"] == "waiting_user"
