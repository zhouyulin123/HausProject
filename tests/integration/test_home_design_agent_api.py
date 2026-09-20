"""不调用真实模型的整屋建议持久化与并发验证。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import home_design_agent
from app.db.database import get_db
from app.db.models import DesignTask, HomeDesignAsset, Product
from app.schemas.home_design_agent import HomeDesignAgentPlan
from app.services import llm_service
from app.services.home_design_asset_service import _digest as asset_digest
from tests.integration.test_home_design_api import context as home_context, payload  # noqa: F401
from tests.integration.test_spatial_api import context as spatial_context  # noqa: F401


@pytest.fixture
def context(home_context, spatial_context, monkeypatch):  # noqa: F811
    home, home_url, headers, stranger, spatial, space_url = home_context
    from tests.integration.test_spatial_api import request

    confirmed = request(1, "confirmed")
    confirmed["document"]["scale_status"] = "confirmed"
    assert spatial.put(space_url, headers=headers, json=confirmed).status_code == 200
    saved = payload()
    saved["document"]["space_version"] = 2
    assert home.put(home_url, headers=headers, json=saved).status_code == 200
    factory = spatial_context[1]
    app = FastAPI()
    app.include_router(home_design_agent.router, prefix="/api/design/tasks")

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    calls = []

    def planner(**kwargs):
        calls.append(kwargs)
        return HomeDesignAgentPlan.model_validate(
            {
                "outcome": "proposal",
                "message": "建议移动书桌",
                "operations": [
                    {
                        "type": "patch_object",
                        "id": "o1",
                        "changes": {"position": {"x": 2.5, "y": 0, "z": 1.5}},
                    }
                ],
            }
        )

    monkeypatch.setattr(llm_service, "plan_home_design", planner)
    with TestClient(app) as client:
        yield (
            client,
            home_url + "/agent-turns",
            headers,
            stranger,
            calls,
            home,
            home_url,
            factory,
        )


def turn(key="one"):
    return {
        "client_turn_id": key,
        "base_version": 1,
        "space_version": 2,
        "message": "书桌右移半米",
    }


@pytest.mark.integration
def test_agent_context_includes_only_normalized_confirmed_requirements(context):
    client, url, headers, _, calls, _, _, factory = context
    task_id = int(url.split("/")[4])
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.confirmed_requirement_json = {
            "spaceType": "客厅",
            "styles": ["现代简约"],
            "budgetRange": "8-15 万",
            "untrusted_extra": "不得进入模型上下文",
        }
        db.commit()

    response = client.post(url, headers=headers, json=turn("confirmed-context"))

    assert response.status_code == 200
    facts = calls[-1]["context"]["confirmed_requirements"]
    assert facts["space_type"] == "客厅"
    assert facts["style"] == "现代简约"
    assert facts["budget_min"] == 80_000
    assert facts["budget_max"] == 150_000
    assert "untrusted_extra" not in facts


def add_frozen_asset(factory, task_id, *, commercial=False):
    with factory() as db:
        now = datetime.now(timezone.utc)
        product = Product(
            name="冻结单椅来源",
            price=680,
            price_max=680,
            is_active=True,
            record_version=1,
            data_origin="merchant" if commercial else "public_reference",
        )
        if commercial:
            product.source_name = "测试授权目录"
            product.source_product_id = "chair-fixture"
            product.source_retrieved_at = now - timedelta(days=1)
            product.price_observed_at = now - timedelta(days=1)
            product.verification_status = "verified"
            product.verified_at = now - timedelta(hours=1)
            product.verified_by = "reviewer"
            product.data_version = "v1"
            product.availability_status = "in_stock"
            product.stock_quantity = 5
            product.region_codes = ["CN-SH"]
            product.price_valid_from = now - timedelta(days=1)
            product.price_valid_to = now + timedelta(days=1)
            product.model_width_mm = 500
            product.model_height_mm = 800
            product.model_depth_mm = 500
        db.add(product)
        db.flush()
        snapshot = {
            "kind": "product",
            "source_id": product.id,
            "source_version": 1,
            "name": "冻结单椅",
            "size": {"width": 0.5, "height": 0.8, "depth": 0.5},
            "material": {"name": "羊毛", "color": "#eeeeee"},
            "model_spec": {"secret_geometry": "must-not-reach-model"},
            "source_summary": {"verification_status": "verified"},
        }
        asset = HomeDesignAsset(
            task_id=task_id,
            client_mutation_id="agent-fixture",
            request_digest="0" * 64,
            snapshot_json=snapshot,
            content_digest=asset_digest(snapshot),
        )
        db.add(asset)
        db.commit()
        return asset.id, product.id


def test_proposal_replay_history_permissions_and_no_implicit_save(context):
    client, url, headers, stranger, calls, home, home_url, _ = context
    result = client.post(url, headers=headers, json=turn())
    assert result.status_code == 200, result.text
    assert result.json()["outcome"] == "proposal"
    assert result.json()["candidate_document"]["objects"][0]["position"]["x"] == 2.5
    assert home.get(home_url, headers=headers).json()["version"] == 1
    assert client.post(url, headers=headers, json=turn()).json() == result.json()
    assert len(calls) == 1
    assert calls[0]["context"]["document"]["space_version"] == 2
    assert (
        client.get(url, headers=headers).json()["turns"][0]["response"] == result.json()
    )
    for method in [client.get, client.post]:
        kw = {"json": turn()} if method == client.post else {}
        assert method(url, headers={"X-Session-Id": stranger}, **kw).status_code == 404


def test_running_same_key_does_not_repeat_model_call(context, monkeypatch):
    client, url, headers, _, calls, _, _, _ = context
    original = llm_service.plan_home_design
    started, finish = Event(), Event()

    def blocked(**kw):
        started.set()
        assert finish.wait(10)
        return original(**kw)

    monkeypatch.setattr(llm_service, "plan_home_design", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, url, headers=headers, json=turn())
        assert started.wait(10)
        try:
            replay = client.post(url, headers=headers, json=turn())
            assert replay.status_code == 409
            assert replay.json()["detail"]["code"] == "home_agent_running"
        finally:
            finish.set()
        assert first.result().status_code == 200
    assert len(calls) == 1


def test_version_change_during_model_call_discards_candidate(context, monkeypatch):
    client, url, headers, _, _, home, home_url, _ = context
    original = llm_service.plan_home_design

    def changed(**kw):
        updated = payload(1, "manual")
        updated["document"]["space_version"] = 2
        assert home.put(home_url, headers=headers, json=updated).status_code == 200
        return original(**kw)

    monkeypatch.setattr(llm_service, "plan_home_design", changed)
    result = client.post(url, headers=headers, json=turn())
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "home_agent_version_conflict"
    assert client.get(url, headers=headers).json()["turns"][0]["status"] == "failed"


def test_invalid_and_provider_failure_are_not_success(context, monkeypatch):
    client, url, headers, _, _, _, _, _ = context
    monkeypatch.setattr(llm_service, "plan_home_design", lambda **kw: {"unknown": True})
    result = client.post(url, headers=headers, json=turn())
    assert result.status_code == 200
    assert result.json()["outcome"] == "invalid"
    assert result.json()["candidate_document"] is None

    def unavailable(**kw):
        raise llm_service.LLMUnavailable("sensitive provider details")

    monkeypatch.setattr(llm_service, "plan_home_design", unavailable)
    failed = client.post(url, headers=headers, json=turn("failed"))
    assert failed.status_code == 503
    assert "sensitive" not in failed.text
    assert (
        client.post(url, headers=headers, json=turn("failed")).json() == failed.json()
    )


def test_agent_adds_only_allowed_frozen_asset_and_returns_budget_evidence(
    context, monkeypatch
):
    client, url, headers, _, calls, home, home_url, factory = context
    task_id = int(home_url.split("/")[-2])
    asset_id, _ = add_frozen_asset(factory, task_id, commercial=True)

    def planner(**kwargs):
        calls.append(kwargs)
        context_value = kwargs["context"]
        assert context_value["available_assets"] == [
            {
                "asset_id": asset_id,
                "kind": "product",
                "name": "冻结单椅",
                "size": {"width": 0.5, "height": 0.8, "depth": 0.5},
                "material": {"name": "羊毛", "color": "#eeeeee"},
                "source_id": context_value["available_assets"][0]["source_id"],
                "source_version": 1,
                "content_digest": context_value["available_assets"][0]["content_digest"],
            }
        ]
        assert "model_spec" not in str(context_value["available_assets"])
        return {
            "outcome": "proposal",
            "message": "放入一把价格9999元的椅子",
            "operations": [
                {
                    "type": "add_asset_object",
                    "id": "chair-2",
                    "asset_id": asset_id,
                    "room_id": "r1",
                    "position": {"x": 0.5, "y": 0, "z": 0.5},
                    "rotation": 0,
                }
            ],
        }

    monkeypatch.setattr(llm_service, "plan_home_design", planner)
    body = {
        **turn("asset-proposal"),
        "region": "CN-SH",
        "budget_max": 1000,
        "allowed_asset_ids": [asset_id],
    }
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    added = result["candidate_document"]["objects"][-1]
    assert added["asset_id"] == asset_id
    assert added["name"] == "冻结单椅"
    assert added["size"] == {"width": 0.5, "height": 0.8, "depth": 0.5}
    assert added["material"] == {"name": "羊毛", "color": "#eeeeee"}
    assert added["installation"] == {"kind": "floor", "wall_id": None}
    assert result["message"] != "放入一把价格9999元的椅子"
    assert result["budget_preview"]["known_subtotal"] == 680
    assert result["budget_preview"]["pending_count"] == 1
    assert result["budget_preview"]["total_price"] is None
    assert result["budget_preview"]["budget_status"] == "incomplete"
    assert result["evidence"]["asset_refs"][0]["asset_id"] == asset_id
    assert home.get(home_url, headers=headers).json()["version"] == 1
    assert len(calls) == 1


def test_unknown_or_unallowed_asset_fails_without_model_call(context, monkeypatch):
    client, url, headers, _, calls, _, home_url, factory = context
    task_id = int(home_url.split("/")[-2])
    asset_id, _ = add_frozen_asset(factory, task_id)
    for key, allowed in (("unknown", [99999]), ("not-allowed", [])):
        if key == "not-allowed":
            monkeypatch.setattr(
                llm_service,
                "plan_home_design",
                lambda **kw: {
                    "outcome": "proposal",
                    "message": "新增",
                    "operations": [
                        {
                            "type": "add_asset_object",
                            "id": "bad",
                            "asset_id": asset_id,
                            "room_id": "r1",
                            "position": {"x": 0.5, "y": 0, "z": 0.5},
                            "rotation": 0,
                        }
                    ],
                },
            )
        result = client.post(
            url,
            headers=headers,
            json={**turn(key), "allowed_asset_ids": allowed},
        )
        assert result.status_code == (422 if key == "unknown" else 200)
        if key == "not-allowed":
            assert result.json()["outcome"] == "invalid"
    assert not calls


@pytest.mark.parametrize(
    "region,budget_max,expected_status,expected_total",
    [
        ("CN-SH", 700, "within", 680),
        ("CN-SH", 600, "over", 680),
        (None, 700, "unknown", None),
    ],
)
def test_candidate_budget_status_uses_only_server_price(
    context, monkeypatch, region, budget_max, expected_status, expected_total
):
    client, url, headers, _, _, _, home_url, factory = context
    task_id = int(home_url.split("/")[-2])
    asset_id, _ = add_frozen_asset(factory, task_id, commercial=True)
    monkeypatch.setattr(
        llm_service,
        "plan_home_design",
        lambda **kw: {
            "outcome": "proposal",
            "message": "候选",
            "operations": [
                {"type": "remove_object", "id": "o1"},
                {
                    "type": "add_asset_object",
                    "id": "chair-only",
                    "asset_id": asset_id,
                    "room_id": "r1",
                    "position": {"x": 0.5, "y": 0, "z": 0.5},
                    "rotation": 0,
                },
            ],
        },
    )
    request = {
        **turn(f"budget-{region}-{budget_max}"),
        "budget_max": budget_max,
        "allowed_asset_ids": [asset_id],
    }
    if region is not None:
        request["region"] = region
    result = client.post(url, headers=headers, json=request)
    assert result.status_code == 200, result.text
    preview = result.json()["budget_preview"]
    assert preview["budget_status"] == expected_status
    assert preview["total_price"] == expected_total
    if region is None:
        assert preview["known_subtotal"] == 0
        assert preview["pending_count"] == 1


def test_product_change_during_model_call_discards_candidate(context, monkeypatch):
    client, url, headers, _, _, _, home_url, factory = context
    task_id = int(home_url.split("/")[-2])
    asset_id, product_id = add_frozen_asset(factory, task_id, commercial=True)

    def planner(**kwargs):
        with factory() as db:
            db.get(Product, product_id).price = 700
            db.commit()
        return {
            "outcome": "proposal",
            "message": "候选",
            "operations": [
                {
                    "type": "add_asset_object",
                    "id": "chair-2",
                    "asset_id": asset_id,
                    "room_id": "r1",
                    "position": {"x": 0.5, "y": 0, "z": 0.5},
                    "rotation": 0,
                }
            ],
        }

    monkeypatch.setattr(llm_service, "plan_home_design", planner)
    response = client.post(
        url,
        headers=headers,
        json={
            **turn("price-drift"),
            "region": "CN-SH",
            "allowed_asset_ids": [asset_id],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "home_agent_version_conflict"


def test_clarification_echoes_budget_scope_without_price(context, monkeypatch):
    client, url, headers, _, _, _, _, _ = context
    monkeypatch.setattr(
        llm_service,
        "plan_home_design",
        lambda **kw: {
            "outcome": "clarify",
            "message": "请确认放在哪个房间",
            "operations": [],
        },
    )
    response = client.post(
        url,
        headers=headers,
        json={
            **turn("clarify-budget"),
            "region": "CN-SH",
            "budget_max": 2000,
        },
    )
    assert response.status_code == 200
    preview = response.json()["budget_preview"]
    assert preview == {
        "region": "CN-SH",
        "currency": "CNY",
        "known_subtotal": 0,
        "pending_count": 0,
        "total_price": None,
        "budget_max": 2000,
        "budget_status": "unknown",
        "limitations": ["尚无通过确定性校验的候选，未计算价格。"],
    }
