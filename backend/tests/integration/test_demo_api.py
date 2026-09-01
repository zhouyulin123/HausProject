import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import demo
from app.db.database import Base, get_db
from app.db.models import Product
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
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    db.add(
        Product(
            sku="CY-001",
            name="藤编靠背餐椅",
            category="餐椅",
            room="餐厅",
            style="原木风",
            price=460,
            is_active=True,
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
    yield TestClient(app)
    db.close()


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
    headers = {"X-Session-ID": "f5f4de50-783f-4d0d-86d9-d5963775505c"}
    payload = {"instruction": "加一把餐椅", "scene": _scene_payload()}

    first = demo_api_context.post("/demo/agent-command", json=payload, headers=headers)
    second = demo_api_context.post("/demo/agent-command", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1


@pytest.mark.integration
def test_demo_agent_command_returns_503_when_llm_unavailable(
    demo_api_context, monkeypatch
):
    from app.services.llm_service import LLMUnavailable

    def unavailable(**kwargs):
        raise LLMUnavailable("模型不可用")

    monkeypatch.setattr(llm_service, "plan_scene_operations", unavailable)

    response = demo_api_context.post(
        "/demo/agent-command",
        json={"instruction": "加一把餐椅", "scene": _scene_payload()},
    )
    assert response.status_code == 503
