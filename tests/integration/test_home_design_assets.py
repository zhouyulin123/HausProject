"""冻结资产权限、幂等与绑定约束。"""
# ruff: noqa: F811

from tests.integration.test_home_design_api import context  # noqa: F401
from tests.integration.test_spatial_api import context as spatial_context  # noqa: F401
from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.db.models import Product, DesignTask, HomeDesignAsset
from app.core.config import settings


@pytest.fixture
def product(spatial_context):
    _, factory, _, _, _ = spatial_context
    rule = json.loads(
        (
            Path(__file__).resolve().parents[2] / "backend/furniture_model_rules.json"
        ).read_text(encoding="utf-8")
    )["模型目录"][0]["确定性规则"]
    with factory() as db:
        row = Product(
            name="测试沙发",
            price=100,
            is_active=True,
            data_origin="merchant",
            record_version=1,
            model_spec_json={"确定性建模规则": rule},
        )
        db.add(row)
        db.commit()
        return row.id


def create_payload(product):
    return dict(
        client_mutation_id="freeze1",
        kind="product",
        source_id=product,
        source_version=1,
    )


def test_asset_options_are_private_and_not_model_payload(context):
    client, url, headers, stranger, _, _ = context
    result = client.get(url + "/asset-options?kind=product", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json() == {"items": [], "next_after_id": None}
    assert result.headers["cache-control"] == "no-store"
    assert (
        client.get(
            url + "/asset-options?kind=product", headers={"X-Session-Id": stranger}
        ).status_code
        == 404
    )


def test_unknown_asset_rejected(context):
    from tests.integration.test_home_design_api import payload

    client, url, headers, _, _, _ = context
    data = payload()
    data["document"]["objects"][0]["asset_id"] = 999
    assert client.put(url, headers=headers, json=data).status_code == 422


def test_freeze_replay_binding_and_delivery(context, spatial_context, product):
    from tests.integration.test_home_design_api import payload
    from app.services.home_design_delivery import get_delivery

    client, url, headers, stranger, _, _ = context
    factory = spatial_context[1]
    body = create_payload(product)
    result = client.post(url + "/assets", headers=headers, json=body)
    assert result.status_code == 200, result.text
    asset = result.json()
    assert asset["size"]["width"] == 2.38
    assert (
        client.get(
            url + f"/assets/{asset['id']}", headers={"X-Session-Id": stranger}
        ).status_code
        == 404
    )
    with factory() as db:
        source = db.get(Product, product)
        source.name, source.record_version, source.is_active = "已修改", 2, False
        db.commit()
    assert client.post(url + "/assets", headers=headers, json=body).json() == asset
    assert client.get(url + f"/assets/{asset['id']}", headers=headers).json() == asset
    assert (
        client.post(
            url + "/assets", headers=headers, json={**body, "source_version": 2}
        ).status_code
        == 409
    )
    saved = payload()
    item = saved["document"]["objects"][0]
    item.update(asset_id=asset["id"], size=asset["size"], material=asset["material"])
    invalid = deepcopy(saved)
    invalid["document"]["objects"][0]["size"]["width"] += 1
    assert client.put(url, headers=headers, json=invalid).status_code == 422
    assert (
        client.post(
            url + "/validate", headers=headers, json=invalid["document"]
        ).status_code
        == 422
    )
    assert client.put(url, headers=headers, json=saved).status_code == 200
    with factory() as db:
        delivery = get_delivery(db, asset["task_id"], 1)
        assert delivery["assets"] == [asset]
        assert delivery["lines"][0]["asset"]["source_version"] == 1
        assert delivery["total_price"] is None


@pytest.mark.parametrize(
    "mode", ["version", "fixture", "ceiling", "oversized", "invalid"]
)
def test_unavailable_sources_fail_closed(
    context, spatial_context, product, monkeypatch, mode
):
    client, url, headers, _, _, _ = context
    with spatial_context[1]() as db:
        row = db.get(Product, product)
        spec = deepcopy(row.model_spec_json)
        if mode == "version":
            row.record_version = 2
        elif mode == "fixture":
            row.data_origin = "development_fixture"
            monkeypatch.setattr(settings, "development_catalog_enabled", False)
        elif mode == "ceiling":
            spec["确定性建模规则"]["安装规则"]["基准"] = "ceiling"
        elif mode == "oversized":
            spec["padding"] = "x" * 1_000_001
        else:
            spec["确定性建模规则"]["规则状态"] = "missing"
        row.model_spec_json = spec
        db.commit()
    response = client.post(
        url + "/assets", headers=headers, json=create_payload(product)
    )
    assert response.status_code == (409 if mode == "version" else 422), response.text
    options = client.get(url + "/asset-options?kind=product", headers=headers).json()
    assert "model_spec" not in options["items"][0]
    if mode != "version":
        assert options["items"][0]["available"] is False


def test_open_geometry_current_only_and_frozen_history(context, spatial_context):
    from app.schemas.open_geometry import OpenGeometryDesign
    from app.services.open_geometry_service import compile_open_geometry
    from tests.unit.test_open_geometry_service import chair_design

    client, url, headers, _, _, _ = context
    task_id = int(url.split("/")[4])
    design = OpenGeometryDesign.model_validate(chair_design())
    version = dict(
        version=1,
        source="llm",
        instruction="测试",
        design=design.model_dump(mode="json"),
        model_spec=compile_open_geometry(design),
    )
    with spatial_context[1]() as db:
        task = db.get(DesignTask, task_id)
        task.agent_state_json = {
            "open_geometry_furniture": {
                "current_version": 1,
                "current": version,
                "history": [version],
            }
        }
        db.commit()
    options = client.get(
        url + "/asset-options?kind=open_geometry", headers=headers
    ).json()
    assert options["items"][0]["available"], options
    body = dict(
        client_mutation_id="open1",
        kind="open_geometry",
        source_id=task_id,
        source_version=1,
    )
    result = client.post(url + "/assets", headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert (
        client.post(
            url + "/assets",
            headers=headers,
            json={**body, "client_mutation_id": "other", "source_id": 9999},
        ).status_code
        == 422
    )
    with spatial_context[1]() as db:
        db.get(DesignTask, task_id).agent_state_json = {}
        db.commit()
    assert (
        client.post(url + "/assets", headers=headers, json=body).json() == result.json()
    )


def test_asset_limit_and_corruption(context, spatial_context, product):
    client, url, headers, _, _, _ = context
    body = create_payload(product)
    asset = client.post(url + "/assets", headers=headers, json=body).json()
    with spatial_context[1]() as db:
        original = db.get(HomeDesignAsset, asset["id"])
        for index in range(199):
            db.add(
                HomeDesignAsset(
                    task_id=asset["task_id"],
                    client_mutation_id=f"fill-{index}",
                    request_digest="0" * 64,
                    snapshot_json=original.snapshot_json,
                    content_digest=original.content_digest,
                )
            )
        db.commit()
    assert (
        client.post(
            url + "/assets",
            headers=headers,
            json={**body, "client_mutation_id": "over-limit"},
        ).status_code
        == 409
    )
    assert client.post(url + "/assets", headers=headers, json=body).json() == asset
    with spatial_context[1]() as db:
        db.get(HomeDesignAsset, asset["id"]).content_digest = "0" * 64
        db.commit()
    assert (
        client.get(url + f"/assets/{asset['id']}", headers=headers).status_code == 409
    )
