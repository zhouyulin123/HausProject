import pytest
from datetime import datetime, timezone
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
    CustomQuoteRule,
    DesignAgentEvent,
    DesignAgentTurn,
    DesignRevision,
    DesignTask,
    Product,
    RoomFactConfirmation,
    UploadedImage,
)
from app.services.anonymous_session_service import (
    attach_image,
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
                data_origin="merchant",
                verification_status="verified",
                availability_status="in_stock",
                stock_quantity=5,
                region_codes=["CN-SH"],
                price_valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                price_valid_to=datetime(2027, 1, 1, tzinfo=timezone.utc),
                verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                verified_by="test:fixture",
                model_width_mm=2200,
                model_height_mm=800,
                model_depth_mm=950,
                is_active=True,
            )
        )
        db.add(
            CustomQuoteRule(
                project_name="定制衣柜",
                category="柜类定制",
                pricing_unit="㎡",
                material_grade="E0 颗粒板",
                unit_price=680,
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
        "delivery_region",
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
def test_low_confidence_room_facts_require_audited_confirmation(
    agent_api_context,
):
    client, factory, owner_id, _, task_id = agent_api_context
    room_model = {
        "schemaVersion": "1.0",
        "imageKind": "floor_plan",
        "spaceType": "客厅",
        "rooms": [
            {
                "id": "living",
                "name": "客厅",
                "floorPolygon": [
                    {"x": 0, "z": 0},
                    {"x": 1, "z": 0},
                    {"x": 1, "z": 1},
                    {"x": 0, "z": 1},
                ],
                "widthM": 3.8,
                "depthM": 4.6,
                "confidence": 0.42,
            }
        ],
        "scale": {"source": "vl", "confidence": 0.42},
        "confidence": 0.42,
        "requiresConfirmation": ["roomDimensions", "spaceType"],
    }
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.confirmed_requirement_json = {}
        task.space_type = None
        image = UploadedImage(
            task_id=task_id,
            file_url="/uploads/private-room.png",
            analysis_json={"room_model": room_model},
        )
        db.add(image)
        db.commit()
        image_id = image.id
        attach_image(db, owner_id, image_id)

    first = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "turn-low-confidence-api-001",
            "message": "继续设计",
            "active_mode": "catalog_design",
            "answers": {
                "budget_max": 20000,
                "delivery_region": "CN-SH",
            },
        },
    )

    assert first.status_code == 200
    payload = first.json()
    assert payload["status"] == "waiting_user"
    assert payload["state"]["fact_evidence"]["space_type"] == {
        "source": "room_model",
        "confidence": 0.42,
        "image_id": image_id,
        "accepted": False,
        "confirmation_required": True,
    }
    question_event = next(
        event for event in payload["events"]
        if event["type"] == "question_created"
    )
    assert question_event["details"]["fact_evidence"]["space_type"][
        "confirmation_required"
    ] is True

    calibration = client.put(
        f"/api/upload/images/{image_id}/room-model",
        headers={"X-Session-ID": owner_id},
        json={
            "room_id": "living",
            "width_m": 4.2,
            "depth_m": 5.1,
            "ceiling_height_m": 2.9,
        },
    )
    assert calibration.status_code == 200

    second = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "turn-low-confidence-api-002",
            "message": "确认这是客厅",
            "active_mode": "catalog_design",
            "answers": {"space_type": "客厅"},
        },
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["state"]["facts"]["room_width_m"] == 4.2
    assert second_payload["state"]["fact_evidence"]["room_width_m"][
        "source"
    ] == "user_confirmation"

    with factory() as db:
        confirmations = db.scalars(
            select(RoomFactConfirmation).where(
                RoomFactConfirmation.image_id == image_id
            )
        ).all()
        assert len(confirmations) == 3
        assert {item.confirmed_by_id for item in confirmations} == {owner_id}


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
                "delivery_region": "CN-SH",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["exit_reason"] == "goal_completed"
    assert payload["state"]["facts"]["budget_max"] == 20000
    assert payload["state"]["facts"]["room_width_m"] == 4
    assert payload["state"]["facts"]["delivery_region"] == "CN-SH"
    assert payload["intent"] == "design"
    assert payload["result"]["plan_count"] == 3
    catalog_event = next(
        event for event in payload["events"] if event["node"] == "catalog_search"
    )
    assert catalog_event["details"]["candidate_count"] == 1
    assert catalog_event["details"]["data_status_counts"] == {"merchant": 1}
    assert catalog_event["details"]["contains_unverified_drafts"] is False


@pytest.mark.integration
def test_agent_api_persists_construction_safety_block_before_tools(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    calls = []
    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_catalog_tool",
        lambda *_: lambda _: calls.append("catalog") or {},
    )
    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_design_tool",
        lambda *_: lambda _: calls.append("design") or {},
    )
    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_scene_tool",
        lambda *_: lambda _: calls.append("scene") or {},
    )
    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_custom_furniture_tool",
        lambda *_: lambda _: calls.append("custom") or {},
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "construction-risk-001",
            "message": "拆除承重墙，并把消防喷淋移位",
            "active_mode": "catalog_design",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls == []
    assert payload["status"] == "needs_human"
    assert payload["approval_required"] is True
    assert payload["exit_reason"] == "safety_blocked"
    assert payload["state"]["hard_errors"] == [
        "load_bearing_structure_change",
        "fire_safety_system_change",
    ]
    gate_event = next(
        event for event in payload["events"] if event["node"] == "safety_intent_gate"
    )
    assert gate_event["type"] == "validation_failed"
    assert gate_event["status"] == "rejected"
    assert gate_event["source"] == "deterministic"
    assert gate_event["details"]["reason_codes"] == payload["state"]["hard_errors"]

    with factory() as db:
        task = db.get(DesignTask, task_id)
        events = db.scalars(
            select(DesignAgentEvent).where(DesignAgentEvent.task_id == task_id)
        ).all()
        assert task.agent_state_json["exit_reason"] == "safety_blocked"
        assert task.agent_state_json["approval_required"] is True
        assert any(event.node == "safety_intent_gate" for event in events)


@pytest.mark.integration
def test_agent_api_does_not_block_explicit_negative_construction_constraints(
    agent_api_context,
):
    client, _, owner_id, _, task_id = agent_api_context

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "construction-negative-001",
            "message": "不拆墙、不动水电，只换家具",
            "active_mode": "catalog_design",
            "answers": {
                "budget_max": 20000,
                "room_width_m": 4,
                "room_depth_m": 5,
                "delivery_region": "CN-SH",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["exit_reason"] == "goal_completed"
    assert payload["approval_required"] is False
    assert not any(
        event["node"] == "safety_intent_gate" for event in payload["events"]
    )


@pytest.mark.integration
def test_agent_turn_accumulates_steps_across_pause_and_resume(
    agent_api_context,
):
    client, _, owner_id, _, task_id = agent_api_context
    first = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "turn-budget-wait-001",
            "message": "继续设计",
            "active_mode": "catalog_design",
        },
    )
    second = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "turn-budget-resume-002",
            "message": "补充预算、尺寸和配送地区",
            "active_mode": "catalog_design",
            "answers": {
                "budget_max": 20000,
                "room_width_m": 4,
                "room_depth_m": 5,
                "delivery_region": "CN-SH",
            },
        },
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "waiting_user"
    assert first.json()["state"]["step_count"] == 2
    assert first.json()["state"]["retry_count"] == 0
    assert second.json()["status"] == "completed"
    assert second.json()["state"]["step_count"] == 7
    assert second.json()["state"]["retry_count"] == 0


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
            "delivery_region": "CN-SH",
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
    checkpoint = client.get(
        f"/api/design/tasks/{task_id}/agent-state",
        headers={"X-Session-ID": owner_id},
    )

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert checkpoint.status_code == 200
    assert checkpoint.json()["step_count"] == first.json()["state"]["step_count"]
    assert checkpoint.json()["retry_count"] == first.json()["state"]["retry_count"]
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
            "deliveryRegion": "CN-SH",
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
        "delivery_region": "CN-SH",
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
                "delivery_region": "CN-SH",
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
def test_retry_budget_cannot_be_reset_by_starting_a_new_turn(
    agent_api_context,
    monkeypatch,
):
    client, _, owner_id, _, task_id = agent_api_context
    attempts: list[int] = []

    def invalid_plan(*_):
        attempts.append(1)
        return [
            {
                "id": "plan-a",
                "name": "包含无效商品的方案",
                "style": "现代简约",
                "furnitureSuggestions": [{"sku": "NOT-EXISTS"}],
            }
        ]

    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "generate_plans",
        invalid_plan,
    )
    body = {
        "message": "开始设计",
        "active_mode": "catalog_design",
        "answers": {
            "budget_max": 20000,
            "room_width_m": 4,
            "room_depth_m": 5,
            "delivery_region": "CN-SH",
        },
    }

    first = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={**body, "client_turn_id": "retry-budget-first-001"},
    )
    second = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={**body, "client_turn_id": "retry-budget-second-002"},
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "needs_human"
    assert first.json()["state"]["retry_count"] == 2
    assert second.json()["status"] == "needs_human"
    assert second.json()["exit_reason"] == "retry_exhausted"
    assert second.json()["state"]["retry_count"] == 2
    assert second.json()["state"]["step_count"] == first.json()["state"]["step_count"]
    assert len(attempts) == 3


@pytest.mark.integration
def test_step_budget_cannot_be_reset_by_starting_a_new_turn(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    attempts: list[int] = []
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "generate_plans",
        lambda *_: attempts.append(1),
    )
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.agent_state_json = {
            "status": "waiting_user",
            "active_mode": "catalog_design",
            "active_room_id": None,
            "intent": "design",
            "current_node": "request_clarification",
            "facts": {"space_type": "客厅"},
            "pending_questions": [],
            "step_count": 12,
            "retry_count": 0,
            "max_steps": 12,
            "max_retries": 2,
            "hard_errors": [],
            "custom_furniture_spec": None,
            "approval_required": False,
            "exit_reason": "missing_facts",
            "scene_ref": None,
            "result": None,
        }
        db.commit()

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "step-budget-exhausted-001",
            "message": "继续执行",
            "active_mode": "catalog_design",
            "answers": {
                "budget_max": 20000,
                "room_width_m": 4,
                "room_depth_m": 5,
                "delivery_region": "CN-SH",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "needs_human"
    assert response.json()["exit_reason"] == "retry_exhausted"
    assert response.json()["state"]["hard_errors"] == ["step_limit_exceeded"]
    assert response.json()["state"]["step_count"] == 12
    assert attempts == []


@pytest.mark.integration
def test_agent_missing_sku_retries_then_hands_off_without_quote(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "generate_plans",
        lambda *_: [{
            "id": "plan-a",
            "name": "未绑定商品的方案",
            "style": "现代简约",
            "furnitureSuggestions": [],
        }],
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "missing-sku-001",
            "message": "开始设计",
            "active_mode": "catalog_design",
            "answers": {
                "budget_max": 20000,
                "room_width_m": 4,
                "room_depth_m": 5,
                "delivery_region": "CN-SH",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_human"
    assert payload["exit_reason"] == "retry_exhausted"
    assert "missing_product_sku" in payload["state"]["hard_errors"]
    with factory() as db:
        assert not db.scalars(
            select(DesignRevision).where(DesignRevision.task_id == task_id)
        ).all()


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
            "delivery_region": "CN-SH",
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


def _custom_cabinet_spec():
    return {
        "family": "cabinet",
        "name": "主卧定制衣柜",
        "purpose": "wardrobe",
        "material": "E0 颗粒板",
        "dimensions": {
            "width_mm": 1200,
            "height_mm": 2400,
            "depth_mm": 600,
        },
        "structure": {
            "door_style": "hinged",
            "door_count": 3,
            "compartment_count": 3,
            "shelf_count": 4,
            "drawer_count": 2,
            "panel_thickness_mm": 18,
            "leg_height_mm": 80,
        },
    }


@pytest.mark.integration
def test_custom_furniture_agent_collects_partial_spec_across_turns(
    agent_api_context,
):
    client, factory, owner_id, _, task_id = agent_api_context

    first = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "custom-missing-family-001",
            "message": "我想定制一件家具",
            "active_mode": "custom_furniture",
        },
    )
    second = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "custom-missing-structure-002",
            "message": "做主卧衣柜",
            "active_mode": "custom_furniture",
            "custom_furniture_spec": {
                "family": "cabinet",
                "name": "主卧定制衣柜",
                "purpose": "wardrobe",
                "material": "E0 颗粒板",
                "dimensions": {
                    "width_mm": 1200,
                    "height_mm": 2400,
                    "depth_mm": 600,
                },
            },
        },
    )
    third = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "custom-complete-structure-003",
            "message": "补充柜体结构",
            "active_mode": "custom_furniture",
            "custom_furniture_spec": {
                "structure": {
                    "door_style": "hinged",
                    "door_count": 3,
                    "compartment_count": 3,
                    "shelf_count": 4,
                    "drawer_count": 2,
                    "panel_thickness_mm": 18,
                    "leg_height_mm": 80,
                },
            },
        },
    )

    assert first.status_code == second.status_code == third.status_code == 200
    assert first.json()["intent"] == "custom_furniture"
    assert [question["field"] for question in first.json()["pending_questions"]] == [
        "custom_furniture_spec.family"
    ]
    assert [question["field"] for question in second.json()["pending_questions"]] == [
        "custom_furniture_spec.structure"
    ]
    assert second.json()["state"]["custom_furniture_spec"]["family"] == "cabinet"
    assert third.json()["status"] == "completed"
    assert third.json()["result"]["quote_preview"]["status"] == "estimated"
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task.agent_state_json["custom_furniture_spec"]["dimensions"] == {
            "width_mm": 1200,
            "height_mm": 2400,
            "depth_mm": 600,
        }
        assert task.agent_state_json["custom_furniture_spec"]["structure"] == {
            "door_style": "hinged",
            "door_count": 3,
            "compartment_count": 3,
            "shelf_count": 4,
            "drawer_count": 2,
            "panel_thickness_mm": 18,
            "leg_height_mm": 80,
        }


@pytest.mark.integration
def test_custom_furniture_agent_completes_unique_quote_preview(
    agent_api_context,
):
    client, factory, owner_id, _, task_id = agent_api_context

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "custom-complete-001",
            "message": "生成衣柜预览和报价",
            "active_mode": "custom_furniture",
            "custom_furniture_spec": _custom_cabinet_spec(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["exit_reason"] == "goal_completed"
    assert payload["approval_required"] is False
    assert payload["result"]["status"] == "preview_ready"
    assert payload["result"]["quote_preview"]["estimated_amount"] == "1958.40"
    assert payload["result"]["model_spec"]["确定性建模规则"]["生成器"] == "cabinet_v2"
    assert next(event for event in payload["events"] if event["node"] == "custom_furniture_preview")
    checkpoint = client.get(
        f"/api/design/tasks/{task_id}/agent-state",
        headers={"X-Session-ID": owner_id},
    )
    assert checkpoint.status_code == 200
    recovered = checkpoint.json()
    assert recovered["custom_furniture_spec"] == _custom_cabinet_spec()
    assert recovered["result"] == payload["result"]
    assert [message["role"] for message in recovered["messages"]] == [
        "user",
        "ai",
    ]
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task.agent_state_json["custom_furniture_spec"] == _custom_cabinet_spec()
        assert task.agent_state_json["result"] == payload["result"]


@pytest.mark.integration
def test_custom_furniture_agent_missing_quote_requires_approval_without_retry(
    agent_api_context,
):
    client, _, owner_id, _, task_id = agent_api_context
    table_spec = {
        "family": "table",
        "name": "六人位餐桌",
        "purpose": "dining_table",
        "material": "实木（橡木）",
        "dimensions": {
            "width_mm": 1600,
            "height_mm": 750,
            "depth_mm": 800,
        },
        "structure": {
            "top_shape": "rectangle",
            "base_style": "four_leg",
            "support_count": 4,
            "seat_count": 6,
            "top_thickness_mm": 36,
            "edge_radius_mm": 12,
        },
    }

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "custom-approval-001",
            "message": "生成餐桌预览",
            "active_mode": "custom_furniture",
            "custom_furniture_spec": table_spec,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_human"
    assert payload["approval_required"] is True
    assert payload["state"]["approval_required"] is True
    assert payload["exit_reason"] == "approval_required"
    assert payload["state"]["retry_count"] == 0
    assert payload["result"]["quote_preview"]["reason_code"] == "quote_rule_missing"


@pytest.mark.integration
def test_custom_furniture_agent_idempotency_does_not_repeat_preview_tool(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    original = design_agent.design_agent_service.custom_furniture_service.build_preview
    calls = []

    def counted_preview(db, spec):
        calls.append(spec.family)
        return original(db, spec)

    monkeypatch.setattr(
        design_agent.design_agent_service.custom_furniture_service,
        "build_preview",
        counted_preview,
    )
    body = {
        "client_turn_id": "custom-idempotent-001",
        "message": "生成衣柜预览和报价",
        "active_mode": "custom_furniture",
        "custom_furniture_spec": _custom_cabinet_spec(),
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
    assert calls == ["cabinet"]
    with factory() as db:
        turn = db.scalars(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task_id,
                DesignAgentTurn.client_turn_id == "custom-idempotent-001",
            )
        ).one()
        events = db.scalars(
            select(DesignAgentEvent).where(DesignAgentEvent.turn_id == turn.id)
        ).all()
        assert len([event for event in events if event.node == "custom_furniture_preview"]) == 1


@pytest.mark.integration
def test_custom_furniture_invalid_structure_waits_without_retry_or_500(
    agent_api_context,
):
    client, _, owner_id, _, task_id = agent_api_context
    invalid = _custom_cabinet_spec()
    invalid["structure"] = {**invalid["structure"], "door_style": "open"}

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "custom-invalid-001",
            "message": "用这个结构生成",
            "active_mode": "custom_furniture",
            "custom_furniture_spec": invalid,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "waiting_user"
    assert payload["exit_reason"] == "invalid_facts"
    assert payload["state"]["retry_count"] == 0
    assert payload["result"] is None
    assert [question["field"] for question in payload["pending_questions"]] == [
        "custom_furniture_spec.structure"
    ]
