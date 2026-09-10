from contextlib import contextmanager
from copy import deepcopy

import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import design_agent, open_geometry as open_geometry_routes, tasks, upload
from app.db.database import Base, get_db
from app.db.models import (
    ChatLog,
    CustomQuoteRule,
    DesignAgentEvent,
    DesignAgentTurn,
    DesignResult,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    DesignTask,
    GenerationRun,
    Product,
    RoomFactConfirmation,
    UploadedImage,
)
from app.schemas.agent_action_plan import AgentActionPlan
from app.schemas.open_geometry import OpenGeometryOperation
from app.services.anonymous_session_service import (
    attach_image,
    attach_task,
    create_anonymous_session,
)
from app.services import design_version_service, generation_run_service
from app.services import open_geometry_service
from app.services.open_geometry_service import prepare_command as prepare_open_geometry_command
from app.services.scene_agent_rate_limit import SceneAgentRateLimiter
from tests.scene_fixtures import attach_scene_versions


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
                source_name="测试供应商",
                source_product_id="SOFA-001",
                source_retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                price_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                verification_status="verified",
                availability_status="in_stock",
                stock_quantity=5,
                region_codes=["CN-SH"],
                price_valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                price_valid_to=datetime(2027, 1, 1, tzinfo=timezone.utc),
                verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                verified_by="test:fixture",
                data_version="catalog-test-v1",
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
    app.include_router(
        open_geometry_routes.router,
        prefix="/api/design/tasks",
    )
    app.include_router(tasks.router, prefix="/api/design/tasks")
    app.include_router(upload.router, prefix="/api/upload")
    shared_open_geometry_limiter = SceneAgentRateLimiter(
        max_requests=120,
        window_seconds=60,
    )
    monkeypatch.setattr(
        design_agent,
        "open_geometry_rate_limiter",
        shared_open_geometry_limiter,
    )
    monkeypatch.setattr(
        open_geometry_routes,
        "open_geometry_rate_limiter",
        shared_open_geometry_limiter,
    )
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

    timeline = client.get(
        f"/api/design/tasks/{task_id}/timeline",
        headers={"X-Session-ID": owner_id},
    )
    assert timeline.status_code == 200
    assert timeline.json()["events"][-1]["event_code"] == (
        "agent.turn.waiting_user"
    )
    assert timeline.json()["events"][-1]["billing_status"] == "not_billable"

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
def test_agent_open_geometry_turn_returns_compact_result_and_checkpoint(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context

    def prepare(*, instruction, current_state, planner=None):
        del planner
        return prepare_open_geometry_command(
            instruction=instruction,
            current_state=current_state,
            planner=lambda *_: TypeAdapter(OpenGeometryOperation).validate_python(
                {"operation": "create", "design": _open_geometry_chair_design()}
            ),
        )

    monkeypatch.setattr(open_geometry_service, "prepare_command", prepare)
    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "agent-open-geometry-001",
            "message": "创建开放式书柜",
            "active_mode": "custom_furniture",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "open_geometry"
    assert payload["result"]["code"] == "completed"
    assert payload["reply"] == "已生成开放几何版本 1。"
    assert payload["open_geometry"]["current_version"] == 1
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task.agent_state_json["open_geometry_furniture"]["current_version"] == 1


@pytest.mark.integration
def test_agent_open_geometry_resets_completed_goal_step_budget(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    calls = []
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.agent_state_json = {
            "status": "completed",
            "exit_reason": "goal_completed",
            "step_count": 12,
            "retry_count": 2,
            "max_steps": 12,
            "max_retries": 2,
        }
        db.commit()

    def prepare(*, instruction, current_state, planner=None):
        del planner
        calls.append(True)
        return prepare_open_geometry_command(
            instruction=instruction,
            current_state=current_state,
            planner=lambda *_: TypeAdapter(OpenGeometryOperation).validate_python(
                {"operation": "create", "design": _open_geometry_chair_design()}
            ),
        )

    monkeypatch.setattr(open_geometry_service, "prepare_command", prepare)
    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "agent-open-geometry-reset-001",
            "message": "再设计一件家具",
            "active_mode": "custom_furniture",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["state"]["step_count"] < 12
    assert response.json()["state"]["retry_count"] == 0
    assert calls == [True]


@pytest.mark.integration
def test_agent_open_geometry_rejects_invalid_private_extension_before_commit(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    prior_extension = {"current_version": 0, "current": None, "history": []}
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.agent_state_json = {"open_geometry_furniture": prior_extension}
        db.commit()

    monkeypatch.setattr(
        open_geometry_service,
        "prepare_command",
        lambda **_: SimpleNamespace(
            result={
                "status": "completed",
                "code": "completed",
                "message": "候选不应提交",
                "current_version": 1,
                "model_id": "OPEN-INVALID",
                "part_count": 1,
            },
            extension={"current_version": "invalid", "current": None, "history": []},
        ),
    )
    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "agent-open-geometry-invalid-extension-001",
            "message": "创建一把椅子",
            "active_mode": "custom_furniture",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["open_geometry"]["current_version"] == 0
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task.agent_state_json["open_geometry_furniture"] == prior_extension


@pytest.mark.integration
@pytest.mark.parametrize(
    "result_patch",
    [
        {"current_version": 2},
        {"part_count": 99},
        {"model_id": "OPEN-WRONG"},
    ],
)
def test_agent_open_geometry_rejects_result_extension_drift_before_commit(
    agent_api_context,
    monkeypatch,
    result_patch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    prepared = prepare_open_geometry_command(
        instruction="创建概念椅",
        current_state={"current_version": 0, "current": None, "history": []},
        planner=lambda *_: TypeAdapter(OpenGeometryOperation).validate_python(
            {"operation": "create", "design": _open_geometry_chair_design()}
        ),
    )
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.agent_state_json = {
            "open_geometry_furniture": {
                "current_version": 0,
                "current": None,
                "history": [],
            }
        }
        db.commit()
    monkeypatch.setattr(
        open_geometry_service,
        "prepare_command",
        lambda **_: SimpleNamespace(
            result={**prepared.result, **result_patch},
            extension=prepared.extension,
        ),
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "agent-open-geometry-result-drift-001",
            "message": "创建一把概念椅",
            "active_mode": "custom_furniture",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["open_geometry"]["current_version"] == 0
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task.agent_state_json["open_geometry_furniture"] == {
            "current_version": 0,
            "current": None,
            "history": [],
        }


@pytest.mark.integration
def test_agent_open_geometry_stale_base_is_rejected_before_model(
    agent_api_context,
    monkeypatch,
):
    client, _, owner_id, _, task_id = agent_api_context
    calls = []

    def prepare(**_kwargs):
        calls.append(True)
        raise AssertionError("过期基线不应调用模型")

    monkeypatch.setattr(open_geometry_service, "prepare_command", prepare)
    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "agent-open-geometry-stale-001",
            "message": "创建开放式书柜",
            "active_mode": "custom_furniture",
            "base_state_version": 1,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agent_state_conflict"
    assert response.json()["detail"]["state_version"] == 0
    assert calls == []


@pytest.mark.integration
def test_agent_open_geometry_replay_does_not_call_prepare_twice(
    agent_api_context,
    monkeypatch,
):
    client, _, owner_id, _, task_id = agent_api_context
    calls = []

    def prepare(*, instruction, current_state, planner=None):
        del instruction, planner
        calls.append(True)
        extension = {
            "current_version": current_state.get("current_version", 0) + 1,
            "current": None,
            "history": [],
        }
        return SimpleNamespace(
            result={
                "status": "completed",
                "code": "completed",
                "message": "已生成开放几何版本。",
                "current_version": extension["current_version"],
                "model_id": "OPEN-REPLAY",
                "part_count": 1,
            },
            extension=extension,
        )

    monkeypatch.setattr(open_geometry_service, "prepare_command", prepare)
    body = {
        "client_turn_id": "agent-open-geometry-replay-001",
        "message": "创建开放式书柜",
        "active_mode": "custom_furniture",
    }
    first = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=body,
    )
    replay = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=body,
    )

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert calls == [True]


@pytest.mark.integration
def test_agent_open_geometry_unsupported_preserves_last_version_without_retry(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    created = open_geometry_service.prepare_command(
        instruction="创建概念椅",
        current_state={"current_version": 0, "current": None, "history": []},
        planner=lambda *_: TypeAdapter(OpenGeometryOperation).validate_python(
            {"operation": "create", "design": _open_geometry_chair_design()}
        ),
    )
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.agent_state_json = {
            "open_geometry_furniture": created.extension,
        }
        task.agent_state_version = 1
        db.commit()

    calls = []

    def unsupported_chat(*_args, **_kwargs):
        from app.services import llm_service

        llm_service._mark_model_call_attempted()
        calls.append(True)
        return {"operation": "unsupported", "reason": "需要 NURBS 自由曲面"}

    monkeypatch.setattr(open_geometry_service.llm_service, "_chat_json", unsupported_chat)
    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "agent-open-geometry-unsupported-001",
            "message": "把椅背改成 NURBS 自由曲面",
            "active_mode": "custom_furniture",
            "base_state_version": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["exit_reason"] == "unsupported_geometry"
    assert payload["approval_required"] is False
    assert payload["state"]["retry_count"] == 0
    assert payload["result"]["code"] == "unsupported_geometry"
    assert payload["open_geometry"]["current_version"] == 1
    assert "NURBS 自由曲面" in payload["reply"]
    assert calls == [True]
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task.agent_state_json["open_geometry_furniture"] == created.extension


def _open_geometry_chair_design():
    return {
        "schema_version": "furniture-open-geometry/1.0",
        "name": "概念椅",
        "description": "",
        "materials": [
            {
                "id": "wood",
                "name": "木材",
                "base_color": "#8B6A4F",
                "roughness": 0.7,
                "metallic": 0.0,
            }
        ],
        "parts": [
            {
                "id": "seat",
                "name": "座面",
                "material_id": "wood",
                "parent_id": None,
                "position_mm": [0.0, 450.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "geometry": {
                    "type": "box",
                    "size_mm": [600.0, 80.0, 600.0],
                    "radius_mm": 20.0,
                },
            }
        ],
    }


def _attach_empty_scene(factory, task_id, *, openings=None):
    with factory() as db:
        task = db.get(DesignTask, task_id)
        revision = design_version_service.persist_generation(
            db,
            task=task,
            generator="llm",
            plans=[
                {
                    "id": "plan-action",
                    "name": "动作规划测试方案",
                    "furnitureSuggestions": [{"id": "SOFA-001"}],
                    "shopQuote": {
                        "furnitureTotal": 5000,
                        "customTotal": 0,
                        "total": 5000,
                        "lineItems": [
                            {"sku": "SOFA-001", "unitPrice": 5000, "quantity": 1}
                        ],
                        "customLineItems": [],
                    },
                }
            ],
        )
        attach_scene_versions(db, revision)
        scene = db.scalar(
            select(DesignScene)
            .join(DesignScene.plan_version)
            .where(DesignScene.plan_version_id == revision.plans[0].id)
        )
        version = db.scalar(
            select(DesignSceneVersion).where(
                DesignSceneVersion.scene_id == scene.id,
                DesignSceneVersion.version == 1,
            )
        )
        document = deepcopy(version.scene_json)
        document["items"] = []
        document["openings"] = openings or []
        version.scene_json = document
        db.commit()
        return scene.id, scene.current_version


def _mock_open_geometry_create(
    *,
    instruction,
    current_state,
    planner=None,
    max_attempts=2,
):
    del planner
    return prepare_open_geometry_command(
        instruction=instruction,
        current_state=current_state,
        max_attempts=max_attempts,
        planner=lambda *_: TypeAdapter(OpenGeometryOperation).validate_python(
            {"operation": "create", "design": _open_geometry_chair_design()}
        ),
    )


@pytest.mark.integration
def test_action_plan_creates_places_and_replays_without_duplicate(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    scene_id, scene_version = _attach_empty_scene(factory, task_id)
    planner_calls = []
    geometry_budgets = []

    def plan(**kwargs):
        planner_calls.append(kwargs)
        return AgentActionPlan.model_validate(
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "创建并放到房间中心",
                "steps": [
                    {
                        "id": "shape",
                        "tool": "open_geometry.edit",
                        "instruction": "做一把包裹感椅子",
                    },
                    {
                        "id": "place",
                        "tool": "scene.place_open_geometry",
                        "dependsOn": ["shape"],
                        "placement": {"kind": "room_center"},
                    },
                ],
            }
        )

    def prepare(**kwargs):
        geometry_budgets.append(kwargs.get("max_attempts"))
        return _mock_open_geometry_create(**kwargs)

    @contextmanager
    def captured_calls():
        yield SimpleNamespace(
            attempted=True,
            attempt_count=2,
            usage={
                "prompt_tokens": 120,
                "completion_tokens": 40,
                "total_tokens": 160,
            },
        )

    monkeypatch.setattr(open_geometry_service, "prepare_command", prepare)
    monkeypatch.setattr(design_agent.design_agent_service.llm_service, "plan_agent_actions", plan)
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "capture_model_call",
        captured_calls,
    )
    monkeypatch.setattr(
        design_agent.design_agent_service.settings,
        "llm_input_price_per_mtok",
        2.0,
    )
    monkeypatch.setattr(
        design_agent.design_agent_service.settings,
        "llm_output_price_per_mtok",
        8.0,
    )
    body = {
        "client_turn_id": "action-create-place-001",
        "message": "做一把包裹感椅子并放到客厅中间",
        "active_mode": "custom_furniture",
        "scene_id": scene_id,
        "base_scene_version": scene_version,
    }

    first = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=body,
    )
    replay = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=body,
    )

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    payload = first.json()
    assert payload["intent"] == "action_plan"
    assert payload["result"]["partialCompletion"] is False
    assert payload["scene_ref"] == {"scene_id": scene_id, "version": 2}
    assert payload["open_geometry"]["current_version"] == 1
    assert len(planner_calls) == 1
    assert geometry_budgets == [1]
    timeline = client.get(
        f"/api/design/tasks/{task_id}/timeline",
        headers={"X-Session-ID": owner_id},
    ).json()
    assert timeline["events"][-1]["attempt"] == 2
    assert timeline["events"][-1]["billing_status"] == "metered"
    assert timeline["events"][-1]["cost_cny"] == pytest.approx(0.00056)
    with factory() as db:
        scene = db.get(DesignScene, scene_id)
        assert scene.current_version == 2
        current = db.scalar(
            select(DesignSceneVersion).where(
                DesignSceneVersion.scene_id == scene_id,
                DesignSceneVersion.version == 2,
            )
        )
        items = current.scene_json["items"]
        assert len(items) == 1
        assert items[0]["sourceType"] == "open_geometry_draft"
        assert items[0]["transform"]["position"] | {"x": 0.0, "z": 0.0} == items[0]["transform"]["position"]


@pytest.mark.integration
def test_custom_mode_without_scene_stays_in_open_geometry_domain(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    planner_calls = []
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "plan_agent_actions",
        lambda **_: planner_calls.append("planner"),
    )
    monkeypatch.setattr(
        open_geometry_service,
        "prepare_command",
        _mock_open_geometry_create,
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "geometry-without-scene-001",
            "message": "做一把包裹感椅子",
            "active_mode": "custom_furniture",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["intent"] == "open_geometry"
    assert planner_calls == []
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task.agent_state_json["open_geometry_furniture"]["current_version"] == 1


@pytest.mark.integration
def test_action_plan_placement_failure_rolls_back_staged_geometry(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    scene_id, scene_version = _attach_empty_scene(factory, task_id)
    monkeypatch.setattr(open_geometry_service, "prepare_command", _mock_open_geometry_create)
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "plan_agent_actions",
        lambda **_: AgentActionPlan.model_validate(
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "创建后放到房间外",
                "steps": [
                    {
                        "id": "shape",
                        "tool": "open_geometry.edit",
                        "instruction": "创建一把椅子",
                    },
                    {
                        "id": "place",
                        "tool": "scene.place_open_geometry",
                        "dependsOn": ["shape"],
                        "placement": {
                            "kind": "explicit",
                            "position": {"x": 50, "z": 50},
                        },
                    },
                ],
            }
        ),
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "action-rollback-001",
            "message": "创建椅子并放到指定位置",
            "active_mode": "custom_furniture",
            "scene_id": scene_id,
            "base_scene_version": scene_version,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["partialCompletion"] is False
    assert response.json()["result"]["code"] in {
        "item_outside_room",
        "item_exceeds_room",
    }
    assert response.json()["result"]["partialCompletion"] is False
    with factory() as db:
        task = db.get(DesignTask, task_id)
        scene = db.get(DesignScene, scene_id)
        assert "open_geometry_furniture" not in task.agent_state_json
        assert scene.current_version == 1
        assert db.scalar(
            select(DesignSceneVersion).where(
                DesignSceneVersion.scene_id == scene_id,
                DesignSceneVersion.version == 2,
            )
        ) is None


@pytest.mark.integration
def test_action_plan_geometry_failure_uses_two_call_budget_and_fails_closed(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    scene_id, scene_version = _attach_empty_scene(factory, task_id)
    calls = []

    def plan(**_):
        calls.append("action_planner")
        return AgentActionPlan.model_validate(
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "创建并放置椅子",
                "steps": [
                    {
                        "id": "shape",
                        "tool": "open_geometry.edit",
                        "instruction": "创建一把椅子",
                    },
                    {
                        "id": "place",
                        "tool": "scene.place_open_geometry",
                        "dependsOn": ["shape"],
                        "placement": {"kind": "room_center"},
                    },
                ],
            }
        )

    def invalid_geometry(*_):
        calls.append("geometry_planner")
        raise open_geometry_service.OpenGeometryError(
            "invalid_model_output",
            "候选无效",
        )

    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "plan_agent_actions",
        plan,
    )
    monkeypatch.setattr(open_geometry_service, "_plan_operation", invalid_geometry)
    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "action-two-call-budget-001",
            "message": "创建一把椅子并放到房间中间",
            "active_mode": "custom_furniture",
            "scene_id": scene_id,
            "base_scene_version": scene_version,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["partialCompletion"] is False
    assert response.json()["result"]["code"] == "invalid_model_output"
    assert calls == ["action_planner", "geometry_planner"]
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert "open_geometry_furniture" not in task.agent_state_json
        assert db.get(DesignScene, scene_id).current_version == 1


@pytest.mark.integration
def test_action_plan_moves_recent_open_geometry_near_known_window(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    scene_id, scene_version = _attach_empty_scene(
        factory,
        task_id,
        openings=[
            {
                "id": "window-east",
                "type": "window",
                "wallIndex": 1,
                "offset": 2,
                "width": 1,
                "height": 1.2,
                "sillHeight": 0.8,
            }
        ],
    )
    monkeypatch.setattr(open_geometry_service, "prepare_command", _mock_open_geometry_create)
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "plan_agent_actions",
        lambda **_: AgentActionPlan.model_validate(
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "创建并放到房间中心",
                "steps": [
                    {
                        "id": "shape",
                        "tool": "open_geometry.edit",
                        "instruction": "做一把包裹感椅子",
                    },
                    {
                        "id": "place",
                        "tool": "scene.place_open_geometry",
                        "dependsOn": ["shape"],
                        "placement": {"kind": "room_center"},
                    },
                ],
            }
        ),
    )
    created = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "action-move-create-001",
            "message": "做一把包裹感椅子并放到客厅中间",
            "active_mode": "custom_furniture",
            "scene_id": scene_id,
            "base_scene_version": scene_version,
        },
    )
    with factory() as db:
        current = db.scalar(
            select(DesignSceneVersion).where(
                DesignSceneVersion.scene_id == scene_id,
                DesignSceneVersion.version == 2,
            )
        )
        instance_id = current.scene_json["items"][0]["instanceId"]

    planner_contexts = []

    def move_plan(**kwargs):
        planner_contexts.append(kwargs["context"])
        return AgentActionPlan.model_validate(
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "已将椅子移到东侧窗边",
                "steps": [
                    {
                        "id": "move",
                        "tool": "scene.move_item",
                        "instanceId": instance_id,
                        "placement": {
                            "kind": "near_opening",
                            "openingId": "window-east",
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "plan_agent_actions",
        move_plan,
    )
    moved = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "action-move-window-002",
            "message": "把刚做的椅子靠窗移动",
            "active_mode": "custom_furniture",
            "scene_id": scene_id,
            "base_scene_version": 2,
            "base_state_version": created.json()["state_version"],
        },
    )

    assert moved.status_code == 200
    assert moved.json()["status"] == "completed"
    assert moved.json()["scene_ref"] == {"scene_id": scene_id, "version": 3}
    assert moved.json()["open_geometry"]["current_version"] == 1
    assert planner_contexts[0]["scene"]["openings"] == [
        {"id": "window-east", "type": "window"}
    ]
    assert planner_contexts[0]["openGeometryItems"][0]["instanceId"] == instance_id
    with factory() as db:
        current = db.scalar(
            select(DesignSceneVersion).where(
                DesignSceneVersion.scene_id == scene_id,
                DesignSceneVersion.version == 3,
            )
        )
        position = current.scene_json["items"][0]["transform"]["position"]
        assert position["x"] == pytest.approx(2.55)
        assert position["z"] == pytest.approx(-0.5)


@pytest.mark.integration
def test_action_plan_ambiguous_reference_clarifies_without_scene_write(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    scene_id, scene_version = _attach_empty_scene(factory, task_id)
    contexts = []

    def clarify(**kwargs):
        contexts.append(kwargs["context"])
        return AgentActionPlan.model_validate(
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "clarify",
                "summary": "无法唯一确定目标",
                "steps": [],
                "question": {
                    "field": "target_instance",
                    "prompt": "要移动哪一件家具？",
                    "candidateIds": [],
                },
            }
        )

    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "plan_agent_actions",
        clarify,
    )
    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "action-clarify-target-001",
            "message": "把刚才那个往旁边挪一下",
            "active_mode": "custom_furniture",
            "scene_id": scene_id,
            "base_scene_version": scene_version,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "waiting_user"
    assert response.json()["exit_reason"] == "clarification_required"
    assert response.json()["pending_questions"][0]["field"] == "target_instance"
    assert response.json()["result"]["partialCompletion"] is False
    assert len(contexts) == 1
    with factory() as db:
        assert db.get(DesignScene, scene_id).current_version == 1


@pytest.mark.integration
def test_pure_geometry_edit_preserves_prior_scene_reference(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    scene_id, scene_version = _attach_empty_scene(factory, task_id)
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.agent_state_json = {
            "scene_ref": {"scene_id": scene_id, "version": scene_version}
        }
        db.commit()
    monkeypatch.setattr(open_geometry_service, "prepare_command", _mock_open_geometry_create)
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "plan_agent_actions",
        lambda **_: AgentActionPlan.model_validate(
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "创建包裹感椅子",
                "steps": [
                    {
                        "id": "shape",
                        "tool": "open_geometry.edit",
                        "instruction": "做一把包裹感椅子",
                    }
                ],
            }
        ),
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "pure-geometry-scene-ref-001",
            "message": "做一把包裹感椅子",
            "active_mode": "custom_furniture",
            "scene_id": scene_id,
            "base_scene_version": scene_version,
        },
    )

    assert response.status_code == 200
    assert response.json()["intent"] == "action_plan"
    assert response.json()["scene_ref"] == {
        "scene_id": scene_id,
        "version": scene_version,
    }


@pytest.mark.integration
def test_open_geometry_rate_limit_is_shared_across_agent_and_legacy_routes(
    agent_api_context,
    monkeypatch,
):
    from app.services.scene_agent_rate_limit import SceneAgentRateLimiter

    client, _, owner_id, _, task_id = agent_api_context
    limiter = SceneAgentRateLimiter(max_requests=1, window_seconds=60)
    monkeypatch.setattr(design_agent, "open_geometry_rate_limiter", limiter)
    monkeypatch.setattr(open_geometry_routes, "open_geometry_rate_limiter", limiter)
    calls = []

    def prepare(*, instruction, current_state, planner=None):
        del instruction, planner
        calls.append(True)
        next_version = current_state.get("current_version", 0) + 1
        return SimpleNamespace(
            result={
                "status": "completed",
                "code": "completed",
                "message": f"已生成开放几何版本 {next_version}。",
                "current_version": next_version,
                "model_id": "OPEN-LIMIT",
                "part_count": 1,
            },
            extension={
                "current_version": next_version,
                "current": None,
                "history": [],
            },
        )

    monkeypatch.setattr(open_geometry_service, "prepare_command", prepare)
    agent_body = {
        "client_turn_id": "agent-open-geometry-limit-001",
        "message": "创建一把椅子",
        "active_mode": "custom_furniture",
    }
    first = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=agent_body,
    )
    replay = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=agent_body,
    )
    limited = client.post(
        f"/api/design/tasks/{task_id}/open-geometry/commands",
        headers={"X-Session-ID": owner_id},
        json={
            "client_mutation_id": "legacy-open-geometry-limit-002",
            "base_version": 1,
            "instruction": "靠背更弯",
        },
    )

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1
    assert calls == [True]


@pytest.mark.integration
def test_agent_turn_preserves_open_geometry_extension_checkpoint(
    agent_api_context,
):
    client, factory, owner_id, _, task_id = agent_api_context
    open_geometry_state = {
        "current_version": 1,
        "current": {
            "version": 1,
            "source": "llm",
            "instruction": "生成一组开放式书柜",
            "design": {
                "schema_version": "furniture-open-geometry/1.0",
                "name": "开放式书柜",
                "description": "",
                "scale": [1.0, 1.0, 1.0],
                "materials": [
                    {
                        "id": "wood",
                        "name": "木饰面",
                        "base_color": "#8B5A2B",
                        "roughness": 0.6,
                        "metallic": 0.0,
                    }
                ],
                "parts": [
                    {
                        "id": "shelf",
                        "name": "书柜主体",
                        "material_id": "wood",
                        "position_mm": [0.0, 1000.0, 0.0],
                        "rotation_deg": [0.0, 0.0, 0.0],
                        "geometry": {
                            "type": "box",
                            "size_mm": [1200.0, 2000.0, 350.0],
                            "radius_mm": 8.0,
                        },
                    }
                ],
            },
            "model_spec": {"生成器": "open_geometry_v1"},
        },
        "history": [],
    }
    open_geometry_state["history"] = [open_geometry_state["current"]]
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.agent_state_json = {"open_geometry_furniture": open_geometry_state}
        db.commit()

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "preserve-open-geometry-001",
            "message": "继续设计",
            "active_mode": "catalog_design",
        },
    )

    assert response.status_code == 200
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task.agent_state_json["open_geometry_furniture"] == open_geometry_state


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
    assert payload["exit_reason"] == "generation_queued"
    assert payload["state"]["facts"]["budget_max"] == 20000
    assert payload["state"]["facts"]["room_width_m"] == 4
    assert payload["state"]["facts"]["delivery_region"] == "CN-SH"
    assert payload["intent"] == "design"
    assert payload["result"]["generation_status"] == "queued"
    assert payload["run_id"] == payload["result"]["run_id"]
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
        lambda *_, **__: lambda _: calls.append("design") or {},
    )
    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_scene_tool",
        lambda *_, **__: lambda _: calls.append("scene") or {},
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
    assert payload["status"] == "running"
    assert payload["exit_reason"] == "generation_queued"
    assert payload["approval_required"] is False
    assert not any(
        event["node"] == "safety_intent_gate" for event in payload["events"]
    )


@pytest.mark.integration
def test_agent_design_queues_one_worker_run_without_sync_generation_side_effects(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    sync_calls: list[str] = []

    def forbidden_sync_generation(*_args, **_kwargs):
        sync_calls.append("called")
        raise AssertionError("Agent HTTP 请求不得同步调用模型")

    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "generate_plans",
        forbidden_sync_generation,
    )
    body = {
        "client_turn_id": "agent-worker-queue-001",
        "message": "开始生成家具搭配方案",
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
    replay = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=body,
    )

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    payload = first.json()
    assert payload["status"] == "running"
    assert payload["exit_reason"] == "generation_queued"
    assert isinstance(payload["run_id"], int)
    assert payload["state"]["run_id"] == payload["run_id"]
    assert payload["result"] == {
        "run_id": payload["run_id"],
        "generation_status": "queued",
    }
    queued_event = next(
        event for event in payload["events"] if event["type"] == "generation_queued"
    )
    assert queued_event["details"]["run_id"] == payload["run_id"]
    assert sync_calls == []

    with factory() as db:
        runs = db.scalars(
            select(GenerationRun).where(GenerationRun.task_id == task_id)
        ).all()
        assert len(runs) == 1
        assert runs[0].id == payload["run_id"]
        assert runs[0].idempotency_key.startswith(f"agent-generation:{task_id}:")
        assert runs[0].request_digest
        assert db.scalars(
            select(DesignRevision).where(DesignRevision.task_id == task_id)
        ).all() == []
        assert db.scalars(
            select(DesignResult).where(DesignResult.task_id == task_id)
        ).all() == []


@pytest.mark.integration
def test_agent_state_refresh_reconciles_bound_worker_completion(agent_api_context):
    client, factory, owner_id, _, task_id = agent_api_context
    queued = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "agent-worker-refresh-001",
            "message": "开始生成家具搭配方案",
            "active_mode": "catalog_design",
            "answers": {
                "budget_max": 20000,
                "room_width_m": 4,
                "room_depth_m": 5,
                "delivery_region": "CN-SH",
            },
        },
    )
    run_id = queued.json()["run_id"]
    with factory() as db:
        run = db.get(GenerationRun, run_id)
        assert run is not None
        run.cost_cny = 0.18
        run.cost_reserved_cny = 0.25
        run.cost_limit_cny = 1.0
        run.execution_deadline_at = datetime(2026, 9, 4, 8, 30, tzinfo=timezone.utc)
        task = db.get(DesignTask, task_id)
        assert task is not None
        revision = design_version_service.persist_generation(
            db,
            task=task,
            generator="llm",
            plans=[
                {
                    "id": "plan-agent",
                    "name": "Agent 方案",
                    "furnitureSuggestions": [{"id": "SOFA-001"}],
                    "shopQuote": {
                        "furnitureTotal": 1000,
                        "customTotal": 0,
                        "total": 1000,
                        "lineItems": [
                            {
                                "sku": "SOFA-001",
                                "unitPrice": 1000,
                                "quantity": 1,
                            }
                        ],
                        "customLineItems": [],
                    },
                }
            ],
        )
        attach_scene_versions(db, revision)
        assert generation_run_service.mark_completed(
            db,
            run=run,
            generator="llm",
            result_revision_id=revision.id,
        )

    refreshed = client.get(
        f"/api/design/tasks/{task_id}/agent-state",
        headers={"X-Session-ID": owner_id},
    )

    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["status"] == "completed"
    assert payload["current_node"] == "generation_completed"
    assert payload["exit_reason"] == "goal_completed"
    assert payload["run_id"] == run_id
    assert payload["cost_cny"] == pytest.approx(0.18)
    assert payload["cost_reserved_cny"] == pytest.approx(0.25)
    assert payload["cost_limit_cny"] == pytest.approx(1.0)
    assert payload["execution_deadline_at"] == "2026-09-04T08:30:00Z"
    assert payload["cancel_requested_at"] is None
    assert payload["result"] == {
        "run_id": run_id,
        "generation_status": "completed",
        "result_revision_id": revision.id,
        "output_digest": run.output_digest,
    }
    with factory() as db:
        persisted = db.get(DesignTask, task_id)
        assert persisted is not None
        assert persisted.agent_state_json["cost_cny"] == pytest.approx(0.18)
        assert persisted.agent_state_json["cost_reserved_cny"] == pytest.approx(0.25)
        assert persisted.agent_state_json["cost_limit_cny"] == pytest.approx(1.0)
        assert persisted.agent_state_json["execution_deadline_at"] == (
            "2026-09-04T08:30:00Z"
        )
        assert persisted.agent_state_json["cancel_requested_at"] is None


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
    assert second.json()["status"] == "running"
    assert second.json()["exit_reason"] == "generation_queued"
    assert second.json()["state"]["step_count"] == 7
    assert second.json()["state"]["retry_count"] == 0


@pytest.mark.integration
def test_sync_agent_turn_deadline_is_applied_and_persisted(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    catalog_calls = []
    monkeypatch.setattr(
        design_agent.design_agent_service.settings,
        "design_agent_turn_lease_seconds",
        0,
    )
    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_catalog_tool",
        lambda _db: lambda _state: catalog_calls.append("catalog")
        or {"candidate_count": 1},
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "sync-deadline-api-001",
            "message": "先找可配送的沙发",
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
    assert payload["exit_reason"] == "timeout"
    assert payload["state"]["hard_errors"] == ["tool_timeout"]
    assert payload["state"]["retry_count"] == 0
    assert payload["state"]["turn_execution_deadline_at"] is not None
    assert catalog_calls == []
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task is not None
        assert task.agent_state_json["exit_reason"] == "timeout"
        assert task.agent_state_json["turn_execution_deadline_at"] is not None


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
def test_agent_checkpoint_contains_cold_start_project_seed(agent_api_context):
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
                "confidence": 0.88,
            }
        ],
        "confidence": 0.88,
    }
    requirement = {
        "rooms": ["客厅"],
        "styles": ["现代简约"],
        "budgetRange": "8-15 万",
    }
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.confirmed_requirement_json = requirement
        db.add(
            UploadedImage(
                task_id=task_id,
                file_url="/uploads/cold-start-room.png",
                analysis_json={"room_model": room_model},
            )
        )
        db.commit()

    response = client.get(
        f"/api/design/tasks/{task_id}/agent-state",
        headers={"X-Session-ID": owner_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["confirmed_requirement"] == requirement
    assert payload["room_model"]["spaceType"] == "客厅"
    assert payload["room_model"]["rooms"][0]["id"] == "living"


@pytest.mark.integration
def test_plan_refine_runs_as_metering_aware_agent_tool(
    agent_api_context,
    monkeypatch,
):
    client, _, owner_id, _, task_id = agent_api_context
    model_attempts: list[str] = []

    def plan_refine_tool(_db, _task, _payload, *, on_model_attempt):
        def execute(_state):
            on_model_attempt()
            model_attempts.append("plan_refine")
            return {
                "plan": {"id": "A", "planVersionId": 19},
                "version": 2,
                "message": "已调整方案",
            }

        return execute

    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_plan_refine_tool",
        plan_refine_tool,
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "plan-refine-agent-001",
            "message": "把主沙发换成浅灰色",
            "active_mode": "catalog_design",
            "plan_id": "A",
        },
    )

    assert response.status_code == 200
    assert response.json()["intent"] == "plan_refine"
    assert response.json()["result"]["plan"]["planVersionId"] == 19
    assert model_attempts == ["plan_refine"]
    timeline = client.get(
        f"/api/design/tasks/{task_id}/timeline",
        headers={"X-Session-ID": owner_id},
    )
    assert timeline.status_code == 200
    assert timeline.json()["events"][-1]["billing_status"] == "unknown"


@pytest.mark.integration
def test_agent_timeline_aggregates_multiple_model_calls_and_known_cost(
    agent_api_context,
    monkeypatch,
):
    client, _, owner_id, _, task_id = agent_api_context

    def plan_refine_tool(_db, _task, _payload, *, on_model_attempt):
        def execute(_state):
            on_model_attempt()
            return {
                "plan": {"id": "A", "planVersionId": 20},
                "version": 2,
                "message": "已调整方案",
            }

        return execute

    @contextmanager
    def captured_calls():
        yield SimpleNamespace(
            attempted=True,
            attempt_count=2,
            usage={"prompt_tokens": 150, "completion_tokens": 30},
        )

    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_plan_refine_tool",
        plan_refine_tool,
    )
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "capture_model_call",
        captured_calls,
    )
    monkeypatch.setattr(
        design_agent.design_agent_service.settings,
        "llm_input_price_per_mtok",
        2.0,
    )
    monkeypatch.setattr(
        design_agent.design_agent_service.settings,
        "llm_output_price_per_mtok",
        8.0,
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "plan-refine-metered-001",
            "message": "把主沙发换成浅灰色",
            "active_mode": "catalog_design",
            "plan_id": "A",
        },
    )

    assert response.status_code == 200
    timeline = client.get(
        f"/api/design/tasks/{task_id}/timeline",
        headers={"X-Session-ID": owner_id},
    ).json()
    event = timeline["events"][-1]
    assert event["attempt"] == 2
    assert event["billing_status"] == "metered"
    assert event["cost_cny"] == pytest.approx(0.00054)


@pytest.mark.integration
def test_legacy_plan_refine_route_delegates_to_unified_agent(
    agent_api_context,
    monkeypatch,
):
    client, _, owner_id, _, task_id = agent_api_context
    captured = {}

    def run_turn(_db, *, task, payload):
        captured["task_id"] = task.id
        captured["payload"] = payload
        return {
            "status": "completed",
            "result": {
                "plan": {"id": "plan-a", "name": "调整后方案"},
                "version": 2,
                "message": "已调整方案",
            },
        }

    monkeypatch.setattr(tasks.design_agent_service, "run_turn", run_turn)

    response = client.post(
        f"/api/design/tasks/{task_id}/plans/plan-a/refine",
        headers={
            "X-Session-ID": owner_id,
            "Idempotency-Key": "legacy-refine-request-001",
        },
        json={"instruction": "换成浅灰色"},
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert captured["task_id"] == task_id
    assert captured["payload"].plan_id == "plan-a"
    assert captured["payload"].message == "换成浅灰色"


@pytest.mark.integration
def test_legacy_plan_refine_requires_caller_idempotency_and_does_not_alias_requests(
    agent_api_context,
    monkeypatch,
):
    client, _, owner_id, _, task_id = agent_api_context
    turn_ids: list[str] = []

    def run_turn(_db, *, task, payload):
        turn_ids.append(payload.client_turn_id)
        return {
            "status": "completed",
            "result": {
                "plan": {"id": "plan-a"},
                "version": len(turn_ids) + 1,
                "message": "已调整方案",
            },
        }

    monkeypatch.setattr(tasks.design_agent_service, "run_turn", run_turn)
    url = f"/api/design/tasks/{task_id}/plans/plan-a/refine"
    body = {"instruction": "换成浅灰色"}

    missing = client.post(
        url,
        headers={"X-Session-ID": owner_id},
        json=body,
    )
    first = client.post(
        url,
        headers={
            "X-Session-ID": owner_id,
            "Idempotency-Key": "legacy-refine-request-a",
        },
        json=body,
    )
    second = client.post(
        url,
        headers={
            "X-Session-ID": owner_id,
            "Idempotency-Key": "legacy-refine-request-b",
        },
        json=body,
    )

    assert missing.status_code == 422
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(turn_ids) == 2
    assert turn_ids[0] != turn_ids[1]


@pytest.mark.integration
@pytest.mark.parametrize(
    "changed_fields",
    [
        {"message": "换一个完全不同的请求"},
        {"active_mode": "custom_furniture"},
        {"scene_id": 999, "base_scene_version": 1},
        {"custom_furniture_spec": {"family": "table"}},
    ],
)
def test_agent_turn_idempotency_key_rejects_different_request(
    agent_api_context,
    monkeypatch,
    changed_fields,
):
    client, factory, owner_id, _, task_id = agent_api_context
    tool_calls: list[str] = []

    def catalog_tool(_db):
        def execute(_state):
            tool_calls.append("catalog_search")
            return {
                "products": [],
                "candidate_count": 0,
                "contains_unverified": False,
            }

        return execute

    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_catalog_tool",
        catalog_tool,
    )
    body = {
        "client_turn_id": "conflicting-turn-001",
        "message": "先看看商品",
        "active_mode": "catalog_design",
        "answers": {"budget_max": 20000, "delivery_region": "CN-SH"},
    }
    first = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json=body,
    )
    calls_after_first = list(tool_calls)
    conflict = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={**body, **changed_fields},
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"
    assert tool_calls == calls_after_first
    with factory() as db:
        assert len(
            db.scalars(
                select(DesignAgentTurn).where(DesignAgentTurn.task_id == task_id)
            ).all()
        ) == 1


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
@pytest.mark.parametrize(
    ("active_mode", "client_turn_id"),
    [
        ("catalog_design", "missing-scene-context-catalog-001"),
        ("room_reconstruction", "missing-scene-context-room-001"),
    ],
)
def test_explicit_scene_edit_without_scene_reference_never_runs_design(
    agent_api_context,
    monkeypatch,
    active_mode,
    client_turn_id,
):
    client, _, owner_id, _, task_id = agent_api_context
    design_calls: list[str] = []
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "generate_plans",
        lambda *_: design_calls.append("design") or [],
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": client_turn_id,
            "message": "把当前场景里的沙发向左移动 30 厘米",
            "active_mode": active_mode,
        },
    )

    assert response.status_code == 200
    assert response.json()["intent"] == "scene_edit"
    assert response.json()["status"] == "waiting_user"
    assert [
        question["field"] for question in response.json()["pending_questions"]
    ] == ["scene_context"]
    assert design_calls == []


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
                request_json={
                    "client_turn_id": "concurrent-turn-001",
                    "message": "重复请求",
                    "active_mode": "catalog_design",
                    "active_room_id": None,
                    "scene_id": None,
                    "base_scene_version": None,
                    "selected_instance_id": None,
                    "answers": None,
                    "custom_furniture_spec": None,
                },
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
def test_agent_turn_exposes_checkpoint_conflict_as_structured_409(
    agent_api_context,
    monkeypatch,
):
    client, _, owner_id, _, task_id = agent_api_context

    def raise_state_conflict(*_, **__):
        raise design_agent.design_agent_service.AgentStateVersionConflict(
            "Agent 状态版本发生并发冲突，本轮副作用已回滚",
            state_version=7,
        )

    monkeypatch.setattr(
        design_agent.design_agent_service,
        "run_turn",
        raise_state_conflict,
    )

    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "state-conflict-api-001",
            "message": "继续设计",
            "active_mode": "catalog_design",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "agent_state_conflict",
        "message": "Agent 状态版本发生并发冲突，本轮副作用已回滚",
        "state_version": 7,
    }


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
def test_generated_sku_validation_is_deferred_to_worker_without_sync_llm(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    calls: list[str] = []
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "generate_plans",
        lambda *_: calls.append("called") or [
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
    assert payload["status"] == "running"
    assert payload["exit_reason"] == "generation_queued"
    assert calls == []
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
    client, factory, owner_id, _, task_id = agent_api_context
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

    with factory() as db:
        product = db.scalar(select(Product).where(Product.sku == "SOFA-001"))
        assert product is not None
        product.is_active = False
        db.commit()
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
    assert attempts == []


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
def test_agent_does_not_validate_worker_generated_missing_sku_in_http_request(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    calls: list[str] = []
    monkeypatch.setattr(
        design_agent.design_agent_service.llm_service,
        "generate_plans",
        lambda *_: calls.append("called") or [{
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
    assert payload["status"] == "running"
    assert payload["exit_reason"] == "generation_queued"
    assert calls == []
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
    open_geometry_state = {
        "current_version": 1,
        "current": {"version": 1, "model_spec": {"generator": "open_geometry_v1"}},
        "history": [{"version": 1}],
    }
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.agent_state_json = {"open_geometry_furniture": open_geometry_state}
        db.commit()

    def crash(*_):
        calls.append("called")
        raise RuntimeError("供应商连接意外中断")

    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_design_tool",
        lambda *_, **__: lambda _state: crash(),
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
        task = db.get(DesignTask, task_id)
        assert task.agent_state_json["open_geometry_furniture"] == open_geometry_state
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
def test_unexpected_failure_preserves_task_execution_budget(
    agent_api_context,
    monkeypatch,
):
    client, factory, owner_id, _, task_id = agent_api_context
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task is not None
        task.agent_state_json = {
            "status": "waiting_user",
            "facts": {"space_type": "客厅"},
            "fact_evidence": {},
            "step_count": 2,
            "retry_count": 1,
            "max_steps": 20,
            "max_retries": 2,
            "hard_errors": ["prior_failure"],
        }
        db.commit()

    def crash(*_):
        raise RuntimeError("供应商连接意外中断")

    monkeypatch.setattr(
        design_agent.design_agent_service,
        "_design_tool",
        lambda *_, **__: lambda _state: crash(),
    )
    response = client.post(
        f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner_id},
        json={
            "client_turn_id": "budget-failure-001",
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
    assert response.json()["status"] == "failed"
    assert response.json()["state"] | {
        "step_count": 2,
        "retry_count": 1,
        "max_steps": 20,
        "max_retries": 2,
    } == response.json()["state"]
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task is not None
        assert task.agent_state_json["step_count"] == 2
        assert task.agent_state_json["retry_count"] == 1
        assert task.agent_state_json["max_steps"] == 20
        assert task.agent_state_json["max_retries"] == 2


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
            "client_turn_id": "custom-missing-name-001",
            "message": "我想按柜体模板定制家具",
            "active_mode": "custom_furniture",
            "custom_furniture_spec": {"family": "cabinet"},
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
        "custom_furniture_spec.name",
        "custom_furniture_spec.purpose",
        "custom_furniture_spec.material",
        "custom_furniture_spec.dimensions",
        "custom_furniture_spec.structure",
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
