from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import design_agent
from app.db.database import Base, get_db
from app.db.models import DesignAgentEvent, DesignAgentTurn, DesignTask
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)


@pytest.fixture
def agent_events_api():
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
        task = DesignTask(status="running")
        db.add(task)
        db.flush()
        attach_task(db, owner.id, task.id)
        turn = DesignAgentTurn(
            task_id=task.id,
            client_turn_id="events-api-turn-001",
            active_mode="catalog_design",
            intent="design",
            status="completed",
            request_json={"message": "用户原始需求不得出现在事件接口"},
        )
        db.add(turn)
        db.flush()
        for sequence in range(1, 5):
            db.add(
                DesignAgentEvent(
                    task_id=task.id,
                    turn_id=turn.id,
                    sequence=sequence,
                    event_type="tool_completed",
                    node="catalog_search",
                    status="completed",
                    source="deterministic",
                    summary=f"敏感自由文本 {sequence} 13800000000",
                    details_json={
                        "message": "完整用户需求",
                        "fact_evidence": {"address": "测试地址"},
                    },
                    created_at=datetime(2026, 9, 8, 8, sequence, tzinfo=timezone.utc),
                )
            )
        db.commit()
        values = owner.id, stranger.id, task.id

    app = FastAPI()
    app.include_router(design_agent.router, prefix="/api/design/tasks")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, values


@pytest.mark.integration
def test_owner_reads_bounded_recent_events_with_cursor(agent_events_api):
    client, (owner_id, _, task_id) = agent_events_api

    recent = client.get(
        f"/api/design/tasks/{task_id}/agent-events?limit=2",
        headers={"X-Session-ID": owner_id},
    )

    assert recent.status_code == 200
    payload = recent.json()
    assert [event["sequence"] for event in payload["events"]] == [3, 4]
    assert payload["has_more"] is True
    assert payload["next_before_id"] == payload["events"][0]["event_id"]

    older = client.get(
        (
            f"/api/design/tasks/{task_id}/agent-events?limit=2"
            f"&before_id={payload['next_before_id']}"
        ),
        headers={"X-Session-ID": owner_id},
    )
    assert older.status_code == 200
    assert [event["sequence"] for event in older.json()["events"]] == [1, 2]
    assert older.json()["has_more"] is False
    assert older.json()["next_before_id"] is None


@pytest.mark.integration
def test_event_feed_hides_other_sessions_and_sensitive_payload(agent_events_api):
    client, (owner_id, stranger_id, task_id) = agent_events_api

    forbidden = client.get(
        f"/api/design/tasks/{task_id}/agent-events",
        headers={"X-Session-ID": stranger_id},
    )
    assert forbidden.status_code == 404

    visible = client.get(
        f"/api/design/tasks/{task_id}/agent-events?limit=1",
        headers={"X-Session-ID": owner_id},
    )
    event = visible.json()["events"][0]
    serialized = str(event)
    assert event["summary"] == "商品检索已完成"
    assert event["details"] == {}
    assert "13800000000" not in serialized
    assert "完整用户需求" not in serialized
    assert "测试地址" not in serialized


@pytest.mark.integration
def test_event_feed_rejects_unbounded_or_invalid_pagination(agent_events_api):
    client, (owner_id, _, task_id) = agent_events_api
    headers = {"X-Session-ID": owner_id}

    assert client.get(
        f"/api/design/tasks/{task_id}/agent-events?limit=101",
        headers=headers,
    ).status_code == 422
    assert client.get(
        f"/api/design/tasks/{task_id}/agent-events?before_id=0",
        headers=headers,
    ).status_code == 422
