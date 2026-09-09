import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.api.routes import design_agent
from app.db.database import Base, get_db
from app.db.models import DesignAgentTurn, DesignTask, User
from app.services import agent_approval_service
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)


@pytest.fixture
def approval_api():
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
        task = DesignTask(status="needs_human")
        db.add(task)
        db.flush()
        attach_task(db, owner.id, task.id)
        turn = DesignAgentTurn(
            task_id=task.id,
            client_turn_id="approval-api-turn-001",
            active_mode="catalog_design",
            intent="design",
            status="needs_human",
            request_json={"message": "审核布局"},
        )
        db.add(turn)
        db.flush()
        approval = agent_approval_service.ensure_for_agent_handoff(
            db,
            task=task,
            turn=turn,
            state={
                "status": "needs_human",
                "exit_reason": "retry_exhausted",
                "current_node": "escalate",
                "hard_errors": ["layout_hard_conflict"],
            },
        )
        construction_turn = DesignAgentTurn(
            task_id=task.id,
            client_turn_id="approval-construction-turn-001",
            active_mode="catalog_design",
            intent="design",
            status="needs_human",
            request_json={"message": "拆除承重墙"},
        )
        db.add(construction_turn)
        db.flush()
        construction_approval = agent_approval_service.ensure_for_agent_handoff(
            db,
            task=task,
            turn=construction_turn,
            state={
                "status": "needs_human",
                "exit_reason": "safety_blocked",
                "current_node": "escalate",
                "hard_errors": ["load_bearing_structure_change"],
            },
        )
        admin = User(
            id=9001,
            phone="13800009001",
            nickname="受控复核管理员",
            role="admin",
            phone_verified=True,
        )
        db.add(admin)
        db.commit()
        values = (
            owner.id,
            stranger.id,
            task.id,
            approval.id,
            construction_approval.id,
        )

    app = FastAPI()
    app.include_router(design_agent.router, prefix="/api/design/tasks")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db

    def override_current_user():
        with factory() as db:
            return db.get(User, 9001)

    app.dependency_overrides[get_current_user] = override_current_user
    with TestClient(app) as client:
        yield client, values


def test_owner_can_list_and_idempotently_decide_approval(approval_api):
    client, (owner_id, _, task_id, approval_id, _) = approval_api

    listed = client.get(
        f"/api/design/tasks/{task_id}/agent-approvals",
        headers={"X-Session-ID": owner_id},
    )

    assert listed.status_code == 200
    item = next(
        approval
        for approval in listed.json()["approvals"]
        if approval["id"] == approval_id
    )
    assert item["id"] == approval_id
    assert item["approval_type"] == "quality_gate"
    assert item["reason_code"] == "layout_hard_conflict"
    assert item["status"] == "pending"

    request = {
        "client_decision_id": "approval-decision-001",
        "decision": "reject",
        "conclusion": "房间尺寸需要重新确认",
    }
    first = client.post(
        f"/api/design/tasks/{task_id}/agent-approvals/{approval_id}/decision",
        headers={"X-Session-ID": owner_id},
        json=request,
    )
    replay = client.post(
        f"/api/design/tasks/{task_id}/agent-approvals/{approval_id}/decision",
        headers={"X-Session-ID": owner_id},
        json=request,
    )

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == "rejected"
    assert first.json()["decision"] == "reject"
    assert first.json()["decided_by_type"] == "session"
    assert first.json()["decided_by_id"] == owner_id
    assert first.json()["decided_at"] is not None
    assert first.json()["resolution_code"] == "quality_revision_required"
    assert first.json()["agent_status"] == "waiting_user"
    assert first.json()["task_status"] == "waiting_input"
    assert first.json()["next_action"] == "revise_user_request"

    checkpoint = client.get(
        f"/api/design/tasks/{task_id}/agent-state",
        headers={"X-Session-ID": owner_id},
    )
    assert checkpoint.status_code == 200
    assert checkpoint.json()["status"] == "waiting_user"
    assert checkpoint.json()["exit_reason"] == "quality_revision_required"
    assert checkpoint.json()["approval_required"] is False

    conflict = client.post(
        f"/api/design/tasks/{task_id}/agent-approvals/{approval_id}/decision",
        headers={"X-Session-ID": owner_id},
        json={**request, "decision": "approve"},
    )
    assert conflict.status_code == 409


def test_approval_api_hides_other_sessions_tasks(approval_api):
    client, (_, stranger_id, task_id, approval_id, _) = approval_api
    headers = {"X-Session-ID": stranger_id}

    listed = client.get(
        f"/api/design/tasks/{task_id}/agent-approvals",
        headers=headers,
    )
    decided = client.post(
        f"/api/design/tasks/{task_id}/agent-approvals/{approval_id}/decision",
        headers=headers,
        json={
            "client_decision_id": "stranger-decision-001",
            "decision": "approve",
            "conclusion": "越权操作",
        },
    )

    assert listed.status_code == 404
    assert decided.status_code == 404


def test_approval_decision_rejects_blank_audit_conclusion(approval_api):
    client, (owner_id, _, task_id, approval_id, _) = approval_api

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-approvals/{approval_id}/decision",
        headers={"X-Session-ID": owner_id},
        json={
            "client_decision_id": "blank-conclusion-001",
            "decision": "approve",
            "conclusion": "   ",
        },
    )

    assert response.status_code == 422


def test_construction_risk_requires_controlled_admin_review(approval_api):
    client, (owner_id, _, task_id, _, approval_id) = approval_api
    request = {
        "client_decision_id": "construction-approve-001",
        "decision": "approve",
        "conclusion": "已完成平台风险分流复核",
    }

    owner_attempt = client.post(
        f"/api/design/tasks/{task_id}/agent-approvals/{approval_id}/decision",
        headers={"X-Session-ID": owner_id},
        json=request,
    )

    assert owner_attempt.status_code == 403

    controlled_review = client.post(
        f"/api/design/tasks/{task_id}/agent-approvals/{approval_id}/controlled-review",
        json=request,
    )
    assert controlled_review.status_code == 200
    assert controlled_review.json()["status"] == "approved"
    assert controlled_review.json()["decided_by_type"] == "admin_controlled_review"
    assert controlled_review.json()["decided_by_id"] == "user:9001"
    assert "不代表施工资质" in controlled_review.json()["conclusion"]
    assert controlled_review.json()["resolution_code"] == (
        "safety_user_revision_required"
    )
    assert controlled_review.json()["task_status"] == "waiting_input"


@pytest.mark.parametrize(
    ("exit_reason", "hard_error", "approval_type"),
    [
        ("approval_required", "quote_rule_missing", "quote_review"),
        (
            "safety_blocked",
            "load_bearing_structure_change",
            "construction_risk",
        ),
        ("retry_exhausted", "layout_hard_conflict", "quality_gate"),
    ],
)
def test_agent_needs_human_turn_automatically_persists_typed_approval(
    approval_api,
    monkeypatch,
    exit_reason,
    hard_error,
    approval_type,
):
    client, (owner_id, _, task_id, _, _) = approval_api

    class FakeWorkflow:
        def __init__(self, **_):
            pass

        def run(self, **kwargs):
            return {
                "status": "needs_human",
                "current_node": "escalate",
                "intent": kwargs["intent"],
                "pending_questions": [],
                "tool_events": [],
                "step_count": 1,
                "retry_count": 1,
                "max_steps": 12,
                "max_retries": 2,
                "hard_errors": [hard_error],
                "custom_furniture_spec": None,
                "approval_required": True,
                "exit_reason": exit_reason,
                "result": None,
            }

    monkeypatch.setattr(
        design_agent.design_agent_service,
        "DesignAgentWorkflow",
        FakeWorkflow,
    )
    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": f"approval-auto-{approval_type}",
            "message": "触发人工审核",
            "active_mode": "catalog_design",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "needs_human"
    listed = client.get(
        f"/api/design/tasks/{task_id}/agent-approvals",
        headers={"X-Session-ID": owner_id},
    )
    approvals = listed.json()["approvals"]
    created = next(
        item for item in approvals if item["turn_id"] == response.json()["turn_id"]
    )
    assert created["approval_type"] == approval_type
    assert created["reason_code"] == hard_error
    assert created["status"] == "pending"
