import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import feedback
from app.db.database import Base, get_db
from app.db.models import DesignFeedbackEvent, DesignTask, Product
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)
from app.services.design_version_service import persist_generation


@pytest.fixture
def feedback_api_context():
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
        other_task = DesignTask(status="completed", progress=100)
        db.add_all(
            [
                task,
                other_task,
                Product(
                    sku="SOFA-OLD",
                    name="旧沙发",
                    category="沙发",
                    room="客厅",
                    style="现代",
                    price=5000,
                ),
                Product(
                    sku="SOFA-NEW",
                    name="新沙发",
                    category="沙发",
                    room="客厅",
                    style="现代",
                    price=5200,
                ),
            ]
        )
        db.commit()
        attach_task(db, owner.id, task.id)
        revision = persist_generation(
            db,
            task=task,
            plans=[{"id": "plan-a", "name": "方案 A", "shopQuote": {}}],
            generator="agent",
        )
        other_revision = persist_generation(
            db,
            task=other_task,
            plans=[{"id": "plan-b", "name": "方案 B", "shopQuote": {}}],
            generator="agent",
        )
        db.commit()
        context = {
            "owner_id": owner.id,
            "stranger_id": stranger.id,
            "task_id": task.id,
            "plan_version_id": revision.plans[0].id,
            "foreign_plan_version_id": other_revision.plans[0].id,
        }

    app = FastAPI()
    app.include_router(feedback.router, prefix="/api/design/tasks")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, factory, context


@pytest.mark.integration
def test_feedback_event_is_task_owned_structured_and_idempotent(feedback_api_context):
    client, factory, context = feedback_api_context
    body = {
        "client_event_id": "feedback-replace-001",
        "action_type": "replace",
        "plan_version_id": context["plan_version_id"],
        "instance_id": "sofa-main",
        "source_sku": "SOFA-OLD",
        "target_sku": "SOFA-NEW",
    }
    url = f"/api/design/tasks/{context['task_id']}/feedback-events"
    headers = {"X-Session-ID": context["owner_id"]}

    first = client.post(url, headers=headers, json=body)
    second = client.post(url, headers=headers, json=body)

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert first.json()["action_type"] == "replace"
    assert first.json()["source_sku"] == "SOFA-OLD"
    assert first.json()["target_sku"] == "SOFA-NEW"
    assert "message" not in first.json()
    with factory() as db:
        events = db.scalars(select(DesignFeedbackEvent)).all()
        assert len(events) == 1
        assert events[0].task_id == context["task_id"]


@pytest.mark.integration
def test_feedback_event_rejects_idempotency_conflict_and_foreign_resources(
    feedback_api_context,
):
    client, _, context = feedback_api_context
    url = f"/api/design/tasks/{context['task_id']}/feedback-events"
    owner_headers = {"X-Session-ID": context["owner_id"]}
    base = {
        "client_event_id": "feedback-adopt-001",
        "action_type": "adopt",
        "plan_version_id": context["plan_version_id"],
        "target_sku": "SOFA-NEW",
    }
    assert client.post(url, headers=owner_headers, json=base).status_code == 200

    conflict = client.post(
        url,
        headers=owner_headers,
        json={**base, "target_sku": "SOFA-OLD"},
    )
    assert conflict.status_code == 409

    foreign_plan = client.post(
        url,
        headers=owner_headers,
        json={
            **base,
            "client_event_id": "feedback-foreign-plan",
            "plan_version_id": context["foreign_plan_version_id"],
        },
    )
    assert foreign_plan.status_code == 404

    stranger = client.post(
        url,
        headers={"X-Session-ID": context["stranger_id"]},
        json={**base, "client_event_id": "feedback-stranger"},
    )
    assert stranger.status_code == 404


@pytest.mark.integration
@pytest.mark.parametrize(
    "payload",
    [
        {
            "client_event_id": "invalid-replace",
            "action_type": "replace",
            "source_sku": "SOFA-OLD",
            "target_sku": "SOFA-OLD",
        },
        {
            "client_event_id": "invalid-move",
            "action_type": "move",
            "instance_id": "sofa-main",
        },
        {
            "client_event_id": "invalid-final",
            "action_type": "final_select",
            "satisfaction_score": 6,
        },
        {
            "client_event_id": "invalid-blank-sku",
            "action_type": "adopt",
            "plan_version_id": 1,
            "target_sku": "   ",
        },
    ],
)
def test_feedback_event_validates_action_specific_fields(
    feedback_api_context,
    payload,
):
    client, _, context = feedback_api_context
    response = client.post(
        f"/api/design/tasks/{context['task_id']}/feedback-events",
        headers={"X-Session-ID": context["owner_id"]},
        json=payload,
    )

    assert response.status_code == 422
