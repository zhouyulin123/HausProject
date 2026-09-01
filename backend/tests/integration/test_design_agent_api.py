import pytest
from types import SimpleNamespace
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import design_agent, upload
from app.db.database import Base, get_db
from app.db.models import (
    ChatLog,
    DesignAgentEvent,
    DesignAgentTurn,
    DesignRevision,
    DesignTask,
    Product,
    UploadedImage,
)
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
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "generate_plans",
        lambda requirement, _: [
            {
                "id": f"plan-{index}",
                "name": f"测试方案 {index}",
                "style": requirement.get("style") or "现代简约",
                "furnitureSuggestions": [
                    {"sku": "SOFA-001", "quantity": 1}
                ],
            }
            for index in ("a", "b", "c")
        ],
    )

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
        db.add(
            Product(
                sku="SOFA-001",
                name="测试沙发",
                category="沙发",
                room="客厅",
                style="现代简约",
                price=5000,
                data_origin="merchant_draft",
                is_active=True,
            )
        )
        db.add(
            Product(
                sku="REF-001",
                name="只读公开参考",
                category="沙发",
                room="客厅",
                style="现代简约",
                price=3000,
                data_origin="public_reference",
                is_active=True,
            )
        )
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
    app.include_router(upload.router, prefix="/api/upload")
    monkeypatch.setattr(upload.llm_service, "analyze_room_model", lambda *_: None)
    monkeypatch.setattr(
        upload.settings,
        "upload_dir",
        str(Path(__file__).resolve().parents[2] / ".test_artifacts" / "uploads-agent"),
    )

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, factory, owner_id, stranger_id, task_id


@pytest.mark.integration
def test_agent_turn_pauses_persists_checkpoint_and_task_bound_chat(
    agent_api_context,
):
    client, factory, owner_id, _, task_id = agent_api_context

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "turn-waiting-001",
            "message": "继续设计",
            "active_mode": "catalog_design",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task_id
    assert payload["exit_reason"] == "missing_facts"
    assert payload["state"]["status"] == "waiting_user"
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
        assert task.agent_state_json["exit_reason"] == "missing_facts"
        assert task.agent_state_version == 1
        assert [log.role for log in logs] == ["user", "ai"]
        assert events


@pytest.mark.integration
def test_agent_turn_resumes_from_structured_answers(agent_api_context):
    client, _, owner_id, _, task_id = agent_api_context

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "turn-resume-001",
            "message": "预算两万元，房间宽4米、深5米，先看商品",
            "active_mode": "catalog_design",
            "answers": {
                "budget_max": 20000,
                "room_width_m": 4,
                "room_depth_m": 5,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["exit_reason"] == "goal_completed"
    assert payload["state"]["facts"]["budget_max"] == 20000
    assert payload["state"]["facts"]["room_width_m"] == 4
    assert payload["intent"] == "design"
    assert payload["result"]["plan_count"] == 3
    catalog_event = next(
        event for event in payload["events"] if event["node"] == "catalog_search"
    )
    assert catalog_event["details"]["candidate_count"] == 1
    assert catalog_event["details"]["data_status_counts"] == {
        "merchant_draft": 1
    }
    assert catalog_event["details"]["contains_unverified_drafts"] is True


@pytest.mark.integration
def test_agent_turn_rejects_foreign_task_before_execution(agent_api_context):
    client, _, _, stranger_id, task_id = agent_api_context

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": stranger_id},
        json={
            "client_turn_id": "turn-foreign-001",
            "message": "继续设计",
            "active_mode": "catalog_design",
        },
    )

    assert response.status_code == 404


@pytest.mark.integration
def test_agent_state_can_be_reloaded_after_page_refresh(agent_api_context):
    client, _, owner_id, _, task_id = agent_api_context
    client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "turn-reload-001",
            "message": "继续设计",
            "active_mode": "catalog_design",
        },
    )

    response = client.get(
        f"/api/design/tasks/{task_id}/agent-state",
        headers={"X-Session-ID": owner_id},
    )

    assert response.status_code == 200
    assert response.json()["exit_reason"] == "missing_facts"
    assert [message["role"] for message in response.json()["messages"]] == [
        "user",
        "ai",
    ]
    assert all(message["id"] > 0 for message in response.json()["messages"])


@pytest.mark.integration
def test_agent_turn_is_idempotent_by_client_turn_id(agent_api_context):
    client, factory, owner_id, _, task_id = agent_api_context
    body = {
        "client_turn_id": "stable-turn-001",
        "message": "先看看商品",
        "active_mode": "catalog_design",
        "answers": {
            "budget_max": 20000,
            "room_width_m": 4,
            "room_depth_m": 5,
        },
    }

    first = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=body,
    )
    second = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=body,
    )

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    with factory() as db:
        assert len(
            db.scalars(select(ChatLog).where(ChatLog.task_id == task_id)).all()
        ) == 2
        turn_id = first.json()["turn_id"]
        assert len(
            db.scalars(
                select(DesignAgentEvent).where(
                    DesignAgentEvent.turn_id == turn_id
                )
            ).all()
        ) == len(first.json()["events"])


@pytest.mark.integration
def test_agent_scene_edit_rejects_stale_base_version(
    agent_api_context,
    monkeypatch,
):
    client, _, owner_id, _, task_id = agent_api_context
    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_load_task_scene",
        lambda *_, **__: SimpleNamespace(id=9, current_version=4),
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "stale-scene-001",
            "message": "把沙发向左移动",
            "active_mode": "catalog_design",
            "scene_id": 9,
            "base_scene_version": 3,
        },
    )

    assert response.status_code == 409
    assert "版本 4" in response.json()["detail"]


@pytest.mark.integration
def test_agent_turn_rejects_client_turn_id_already_in_progress(
    agent_api_context,
):
    client, factory, owner_id, _, task_id = agent_api_context
    with factory() as db:
        db.add(
            DesignAgentTurn(
                task_id=task_id,
                client_turn_id="concurrent-turn-001",
                active_mode="catalog_design",
                intent="design",
                status="running",
                request_json={"message": "第一次请求"},
            )
        )
        db.commit()

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "concurrent-turn-001",
            "message": "重复请求",
            "active_mode": "catalog_design",
        },
    )

    assert response.status_code == 409
    assert "仍在处理中" in response.json()["detail"]


@pytest.mark.integration
def test_agent_normalizes_current_frontend_requirement_shape(
    agent_api_context,
):
    client, factory, owner_id, _, task_id = agent_api_context
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.space_type = None
        task.style = None
        task.budget_min = None
        task.budget_max = None
        task.agent_state_json = None
        task.confirmed_requirement_json = {
            "rooms": ["客厅", "餐厅"],
            "styles": ["原木风"],
            "budgetRange": "8-15 万",
            "area": 90,
        }
        db.commit()

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "frontend-shape-001",
            "message": "开始设计",
            "active_mode": "catalog_design",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "waiting_user"
    assert [q["field"] for q in payload["pending_questions"]] == [
        "room_dimensions"
    ]
    assert payload["state"]["facts"] == {
        "space_type": "客厅",
        "style": "原木风",
        "budget_min": 80000,
        "budget_max": 150000,
    }


@pytest.mark.integration
def test_agent_invalid_sku_never_creates_completed_revision(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "generate_plans",
        lambda *_: [
            {
                "id": "plan-a",
                "name": "包含无效商品的方案",
                "style": "现代简约",
                "furnitureSuggestions": [{"sku": "NOT-EXISTS"}],
            }
        ],
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "invalid-sku-001",
            "message": "开始设计",
            "active_mode": "catalog_design",
            "answers": {
                "budget_max": 20000,
                "room_width_m": 4,
                "room_depth_m": 5,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_human"
    assert payload["exit_reason"] == "retry_exhausted"
    assert "invalid_sku" in payload["state"]["hard_errors"]
    with factory() as db:
        revision_count = len(
            db.scalars(
                select(DesignRevision).where(DesignRevision.task_id == task_id)
            ).all()
        )
        assert revision_count == 0


@pytest.mark.integration
def test_unexpected_failure_is_persisted_and_idempotently_replayed(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    calls = []

    def crash(*_):
        calls.append("called")
        raise RuntimeError("供应商连接意外中断")

    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "generate_plans",
        crash,
    )
    body = {
        "client_turn_id": "failed-turn-001",
        "message": "开始设计",
        "active_mode": "catalog_design",
        "answers": {
            "budget_max": 20000,
            "room_width_m": 4,
            "room_depth_m": 5,
        },
    }

    first = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=body,
    )
    second = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=body,
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "failed"
    assert first.json()["exit_reason"] == "tool_failed"
    assert calls == ["called"]
    with factory() as db:
        turn = db.scalars(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task_id,
                DesignAgentTurn.client_turn_id == "failed-turn-001",
            )
        ).one()
        assert turn.status == "failed"
        assert turn.response_json is not None
        assert len(
            db.scalars(select(ChatLog).where(ChatLog.task_id == task_id)).all()
        ) == 2
        assert len(
            db.scalars(
                select(DesignAgentEvent).where(
                    DesignAgentEvent.turn_id == turn.id
                )
            ).all()
        ) == 1


@pytest.mark.integration
def test_workspace_upload_can_bind_directly_to_owned_task(agent_api_context):
    client, factory, owner_id, _, task_id = agent_api_context

    response = client.post(
        "/api/upload/image",
        headers={"X-Session-ID": owner_id},
        data={"task_id": str(task_id)},
        files={"file": ("客厅.png", b"\x89PNG\r\n\x1a\nimage", "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["task_id"] == task_id
    with factory() as db:
        image = db.get(UploadedImage, response.json()["image_id"])
        assert image.task_id == task_id


@pytest.mark.integration
def test_workspace_upload_rejects_foreign_task_before_analysis(agent_api_context):
    client, _, _, stranger_id, task_id = agent_api_context

    response = client.post(
        "/api/upload/image",
        headers={"X-Session-ID": stranger_id},
        data={"task_id": str(task_id)},
        files={"file": ("客厅.png", b"\x89PNG\r\n\x1a\nimage", "image/png")},
    )

    assert response.status_code == 404
