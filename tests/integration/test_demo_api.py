from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import demo
from app.db.database import Base, get_db
from app.db.models import AnonymousSession, DemoAgentInvocation, Product
from app.schemas.scene_agent import AddSceneItem, SceneOperationBatch
from app.schemas.scenes import Vector2XZ
from app.services import llm_service
from app.services.scene_agent_rate_limit import SceneAgentRateLimiter


def _scene_payload() -> dict:
    return {
        "schemaVersion": "1.0",
        "unit": "m",
        "coordinateSystem": "right-handed-y-up",
        "room": {
            "id": "living-room",
            "name": "客厅",
            "floorPolygon": [
                {"x": -2.3, "z": -2.8},
                {"x": 2.3, "z": -2.8},
                {"x": 2.3, "z": 2.8},
                {"x": -2.3, "z": 2.8},
            ],
            "ceilingHeight": 2.8,
            "wallThickness": 0.12,
        },
        "openings": [],
        "items": [
            {
                "instanceId": "sofa-main",
                "sku": "SF-001",
                "category": "沙发",
                "transform": {
                    "position": {"x": 0, "y": 0.425, "z": -2.2},
                    "rotation": {"x": 0, "y": 0, "z": 0},
                    "scale": {"x": 1, "y": 1, "z": 1},
                },
            }
        ],
    }


@pytest.fixture
def demo_api_context():
    original_session_limiter = demo.demo_session_rate_limiter
    original_ip_limiter = demo.demo_ip_rate_limiter
    demo.demo_session_rate_limiter = SceneAgentRateLimiter(
        max_requests=100,
        window_seconds=60,
    )
    demo.demo_ip_rate_limiter = SceneAgentRateLimiter(
        max_requests=100,
        window_seconds=60,
    )
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    session_id = "f5f4de50-783f-4d0d-86d9-d5963775505c"
    now = datetime.now(timezone.utc)
    db.add(
        AnonymousSession(
            id=session_id,
            status="active",
            created_at=now,
            last_seen_at=now,
            expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
    )
    db.add(
        Product(
            sku="CY-001",
            name="藤编靠背餐椅",
            category="餐椅",
            room="餐厅",
            style="原木风",
            price=460,
            is_active=True,
            data_origin="merchant",
            source_name="测试供应商",
            source_product_id="CY-001",
            source_retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            price_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            verification_status="verified",
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            verified_by="test:fixture",
            data_version="catalog-test-v1",
            availability_status="in_stock",
            stock_quantity=10,
            price_valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            price_valid_to=datetime(2030, 1, 1, tzinfo=timezone.utc),
            region_codes=["*"],
            model_width_mm=460,
            model_height_mm=810,
            model_depth_mm=535,
        )
    )
    db.add(
        Product(
            sku="SF-001",
            name="云朵感三人位布艺沙发",
            category="沙发",
            room="客厅",
            style="奶油风",
            price=4999,
            is_active=True,
            data_origin="merchant",
            source_name="测试供应商",
            source_product_id="SF-001",
            source_retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            price_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            verification_status="verified",
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            verified_by="test:fixture",
            data_version="catalog-test-v1",
            availability_status="in_stock",
            stock_quantity=10,
            price_valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            price_valid_to=datetime(2030, 1, 1, tzinfo=timezone.utc),
            region_codes=["*"],
            model_width_mm=2380,
            model_height_mm=760,
            model_depth_mm=980,
        )
    )
    db.add(
        Product(
            sku="DG-002",
            name="纸艺吊线床头灯（一对）",
            category="灯具",
            room="卧室",
            style="日式风",
            price=460,
            is_active=True,
            data_origin="merchant",
            source_name="测试供应商",
            source_product_id="DG-002",
            source_retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            price_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            verification_status="verified",
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            verified_by="test:fixture",
            data_version="catalog-test-v1",
            availability_status="in_stock",
            stock_quantity=10,
            price_valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            price_valid_to=datetime(2030, 1, 1, tzinfo=timezone.utc),
            region_codes=["*"],
            model_width_mm=300,
            model_height_mm=250,
            model_depth_mm=300,
            model_spec_json={
                "家具类型": "床头吊灯",
                "安装参数": {"锚点": "ceiling", "默认垂吊_mm": 600},
            },
        )
    )
    db.commit()

    app = FastAPI()
    app.include_router(demo.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.headers.update(
        {
            "X-Session-ID": session_id,
            "Idempotency-Key": "demo-request-001",
        }
    )
    app.state.demo_db = db
    yield client
    db.close()
    demo.demo_session_rate_limiter = original_session_limiter
    demo.demo_ip_rate_limiter = original_ip_limiter


@pytest.mark.integration
def test_demo_agent_command_returns_operations(demo_api_context, monkeypatch):
    batch = SceneOperationBatch(
        message="已在餐桌旁添加一把餐椅",
        operations=[
            AddSceneItem(
                type="add",
                sku="CY-001",
                position=Vector2XZ(x=0, z=0.75),
                rotation_y=0,
            )
        ],
    )
    monkeypatch.setattr(
        llm_service,
        "plan_scene_operations",
        lambda **kwargs: batch,
    )

    response = demo_api_context.post(
        "/demo/agent-command",
        json={"instruction": "加一把餐椅", "scene": _scene_payload()},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "已在餐桌旁添加一把餐椅"
    assert len(data["operations"]) == 1
    assert data["operations"][0]["type"] == "add"
    assert data["operations"][0]["sku"] == "CY-001"
    assert data["scene"]["items"][-1]["sku"] == "CY-001"
    assert data["scene"]["items"][-1]["transform"]["position"]["y"] == pytest.approx(
        0.405
    )


@pytest.mark.integration
def test_demo_agent_command_forwards_structured_history(
    demo_api_context, monkeypatch
):
    captured = {}

    def plan(**kwargs):
        captured.update(kwargs)
        return SceneOperationBatch(
            message="已移走刚才添加的餐椅",
            operations=[
                {
                    "type": "remove",
                    "instanceId": "item-CY-001-1",
                }
            ],
        )

    monkeypatch.setattr(llm_service, "plan_scene_operations", plan)
    payload = {
        "instruction": "把刚才那个移走",
        "scene": {
            **_scene_payload(),
            "items": [
                *_scene_payload()["items"],
                {
                    "instanceId": "item-CY-001-1",
                    "sku": "CY-001",
                    "category": "餐椅",
                    "dimensions": {"x": 0.46, "y": 0.81, "z": 0.535},
                    "transform": {
                        "position": {"x": 0, "y": 0.405, "z": 0.75},
                        "rotation": {"x": 0, "y": 0, "z": 0},
                        "scale": {"x": 1, "y": 1, "z": 1},
                    },
                },
            ],
        },
        "history": [
            {
                "instruction": "加一把餐椅",
                "message": "已添加餐椅",
                "operations": [
                    {
                        "type": "add",
                        "sku": "CY-001",
                        "position": {"x": 0, "z": 0.75},
                        "rotationY": 0,
                    }
                ],
                "affectedInstanceIds": ["item-CY-001-1"],
            }
        ],
    }

    response = demo_api_context.post("/demo/agent-command", json=payload)

    assert response.status_code == 200
    assert captured["history"][0]["affectedInstanceIds"] == ["item-CY-001-1"]


@pytest.mark.integration
def test_demo_agent_command_rejects_unsafe_scene_operations(
    demo_api_context, monkeypatch
):
    monkeypatch.setattr(
        llm_service,
        "plan_scene_operations",
        lambda **kwargs: SceneOperationBatch(
            message="已移动",
            operations=[
                {
                    "type": "move",
                    "instanceId": "sofa-main",
                    "position": {"x": 99, "z": 99},
                }
            ],
        ),
    )

    response = demo_api_context.post(
        "/demo/agent-command",
        json={"instruction": "把沙发移到房间外", "scene": _scene_payload()},
    )

    assert response.status_code == 422
    assert "validation" in response.json()["detail"]


@pytest.mark.integration
def test_demo_agent_command_places_ceiling_product_at_ceiling(
    demo_api_context, monkeypatch
):
    monkeypatch.setattr(
        llm_service,
        "plan_scene_operations",
        lambda **kwargs: SceneOperationBatch(
            message="已添加吊灯",
            operations=[
                {
                    "type": "add",
                    "sku": "DG-002",
                    "position": {"x": 0, "z": 0},
                    "rotationY": 0,
                }
            ],
        ),
    )

    response = demo_api_context.post(
        "/demo/agent-command",
        json={"instruction": "加一盏床头吊灯", "scene": _scene_payload()},
    )

    assert response.status_code == 200
    added = response.json()["scene"]["items"][-1]
    assert added["transform"]["position"]["y"] == pytest.approx(2.675)


@pytest.mark.integration
def test_demo_agent_command_keeps_ceiling_anchor_when_moving_light(
    demo_api_context, monkeypatch
):
    monkeypatch.setattr(
        llm_service,
        "plan_scene_operations",
        lambda **kwargs: SceneOperationBatch(
            message="已移动吊灯",
            operations=[
                {
                    "type": "move",
                    "instanceId": "lamp-main",
                    "position": {"x": 0.5, "z": 0},
                }
            ],
        ),
    )
    scene = _scene_payload()
    scene["items"] = [
        {
            "instanceId": "lamp-main",
            "sku": "DG-002",
            "category": "灯具",
            "dimensions": {"x": 0.3, "y": 0.25, "z": 0.3},
            "transform": {
                "position": {"x": 0, "y": 2.675, "z": 0},
                "rotation": {"x": 0, "y": 0, "z": 0},
                "scale": {"x": 1, "y": 1, "z": 1},
            },
        }
    ]

    response = demo_api_context.post(
        "/demo/agent-command",
        json={"instruction": "把吊灯向右移动", "scene": scene},
    )

    assert response.status_code == 200
    moved = response.json()["scene"]["items"][0]
    assert moved["transform"]["position"]["x"] == pytest.approx(0.5)
    assert moved["transform"]["position"]["y"] == pytest.approx(2.675)


@pytest.mark.integration
def test_demo_agent_command_enforces_rate_limit(demo_api_context, monkeypatch):
    monkeypatch.setattr(
        demo,
        "demo_session_rate_limiter",
        SceneAgentRateLimiter(max_requests=1, window_seconds=60),
    )
    monkeypatch.setattr(
        demo,
        "demo_ip_rate_limiter",
        SceneAgentRateLimiter(max_requests=10, window_seconds=60),
    )
    monkeypatch.setattr(
        llm_service,
        "plan_scene_operations",
        lambda **kwargs: SceneOperationBatch(
            message="已添加",
            operations=[
                {
                    "type": "add",
                    "sku": "CY-001",
                    "position": {"x": 0, "z": 0.75},
                    "rotationY": 0,
                }
            ],
        ),
    )
    payload = {"instruction": "加一把餐椅", "scene": _scene_payload()}

    first = demo_api_context.post(
        "/demo/agent-command",
        json=payload,
        headers={"Idempotency-Key": "demo-rate-001"},
    )
    second = demo_api_context.post(
        "/demo/agent-command",
        json=payload,
        headers={"Idempotency-Key": "demo-rate-002"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1


@pytest.mark.integration
def test_demo_agent_command_returns_503_when_llm_unavailable(
    demo_api_context, monkeypatch
):
    from app.services.llm_service import LLMUnavailable

    calls = 0

    def unavailable(**kwargs):
        nonlocal calls
        calls += 1
        llm_service._mark_model_call_attempted()
        llm_service._capture_model_usage(
            type(
                "Usage",
                (),
                {
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                    "total_tokens": 60,
                },
            )()
        )
        raise LLMUnavailable("模型不可用")

    monkeypatch.setattr(llm_service, "plan_scene_operations", unavailable)
    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 6.0)

    response = demo_api_context.post(
        "/demo/agent-command",
        json={"instruction": "加一把餐椅", "scene": _scene_payload()},
    )
    replay = demo_api_context.post(
        "/demo/agent-command",
        json={"instruction": "加一把餐椅", "scene": _scene_payload()},
    )
    assert response.status_code == 503
    assert replay.status_code == 503
    assert calls == 1
    invocation = demo_api_context.app.state.demo_db.query(DemoAgentInvocation).one()
    assert invocation.status == "failed"
    assert invocation.attempt_count == 1
    assert invocation.billing_status == "metered"
    assert invocation.cost_cny == pytest.approx(0.00016)
    assert invocation.error_code == "llm_unavailable"


@pytest.mark.integration
def test_demo_agent_command_is_idempotent_and_records_model_cost(
    demo_api_context, monkeypatch
):
    calls = 0
    batch = SceneOperationBatch(
        message="已添加",
        operations=[
            AddSceneItem(
                type="add",
                sku="CY-001",
                position=Vector2XZ(x=0, z=0.75),
                rotation_y=0,
            )
        ],
    )

    def plan(**kwargs):
        nonlocal calls
        calls += 1
        llm_service._mark_model_call_attempted()
        llm_service._capture_model_usage(
            type(
                "Usage",
                (),
                {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            )()
        )
        return batch

    monkeypatch.setattr(llm_service, "plan_scene_operations", plan)
    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 6.0)
    monkeypatch.setattr(
        demo,
        "demo_session_rate_limiter",
        SceneAgentRateLimiter(max_requests=1, window_seconds=60),
    )
    monkeypatch.setattr(
        demo,
        "demo_ip_rate_limiter",
        SceneAgentRateLimiter(max_requests=1, window_seconds=60),
    )
    payload = {"instruction": "加一把餐椅", "scene": _scene_payload()}

    first = demo_api_context.post("/demo/agent-command", json=payload)
    demo_api_context.app.state.demo_db.query(Product).filter_by(sku="CY-001").delete()
    demo_api_context.app.state.demo_db.commit()
    replay = demo_api_context.post("/demo/agent-command", json=payload)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert calls == 1
    invocation = demo_api_context.app.state.demo_db.query(DemoAgentInvocation).one()
    assert invocation.status == "completed"
    assert invocation.attempt_count == 1
    assert invocation.billing_status == "metered"
    assert invocation.cost_cny == pytest.approx(0.00032)
    assert invocation.usage_json == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }
    assert invocation.result_json == first.json()
    assert invocation.request_id is not None


@pytest.mark.integration
def test_demo_agent_command_records_and_replays_unexpected_provider_failure(
    demo_api_context, monkeypatch
):
    calls = 0

    def unexpected(**kwargs):
        nonlocal calls
        calls += 1
        llm_service._mark_model_call_attempted()
        raise RuntimeError("private provider failure")

    monkeypatch.setattr(llm_service, "plan_scene_operations", unexpected)
    payload = {"instruction": "加一把餐椅", "scene": _scene_payload()}

    first = demo_api_context.post("/demo/agent-command", json=payload)
    replay = demo_api_context.post("/demo/agent-command", json=payload)

    assert first.status_code == replay.status_code == 503
    assert first.json() == replay.json() == {"detail": "AI 服务暂时不可用，请稍后再试"}
    assert calls == 1
    invocation = demo_api_context.app.state.demo_db.query(DemoAgentInvocation).one()
    assert invocation.status == "failed"
    assert invocation.attempt_count == 1
    assert invocation.billing_status == "unknown"
    assert invocation.error_code == "provider_error"


@pytest.mark.integration
def test_demo_agent_command_rejects_idempotency_key_reuse_for_different_input(
    demo_api_context, monkeypatch
):
    monkeypatch.setattr(
        llm_service,
        "plan_scene_operations",
        lambda **kwargs: SceneOperationBatch(
            message="已移动",
            operations=[
                {
                    "type": "move",
                    "instanceId": "sofa-main",
                    "position": {"x": 0.2, "z": -2.2},
                }
            ],
        ),
    )
    first = demo_api_context.post(
        "/demo/agent-command",
        json={"instruction": "沙发向右移动", "scene": _scene_payload()},
    )
    conflict = demo_api_context.post(
        "/demo/agent-command",
        json={"instruction": "沙发向左移动", "scene": _scene_payload()},
    )

    assert first.status_code == 200
    assert conflict.status_code == 409


@pytest.mark.integration
def test_demo_agent_command_requires_valid_session_and_idempotency_key(
    demo_api_context,
):
    payload = {"instruction": "加一把餐椅", "scene": _scene_payload()}

    missing_key = demo_api_context.post(
        "/demo/agent-command",
        json=payload,
        headers={"Idempotency-Key": ""},
    )
    unknown_session = demo_api_context.post(
        "/demo/agent-command",
        json=payload,
        headers={
            "X-Session-ID": "00000000-0000-0000-0000-000000000000",
            "Idempotency-Key": "unknown-session-request",
        },
    )

    assert missing_key.status_code == 422
    assert unknown_session.status_code == 404
