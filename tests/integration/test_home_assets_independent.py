"""独立验收冻结家具不会随来源更新漂移，也不能跨任务引用。"""

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.main import api_router
from app.db.database import get_db
from app.db.models import DesignTask, Product
from app.services.anonymous_session_service import attach_task
from app.services.furniture_model_rules import compile_lounge_chair_rule
from tests.integration.test_spatial_api import context as spatial_context, request  # noqa: F401
from tests.unit.test_furniture_model_rules import _lounge_chair_spec
from tests.unit.test_home_design import document


@pytest.fixture
def assets_context(spatial_context):  # noqa: F811
    spatial, factory, space_url, headers, stranger = spatial_context
    assert spatial.put(space_url, headers=headers, json=request()).status_code == 200
    spec = _lounge_chair_spec()
    spec["确定性建模规则"] = compile_lounge_chair_rule(spec)
    with factory() as db:
        product = Product(name="独立验收椅", sku="INDEPENDENT-CHAIR", price=100,
                          data_origin="public_reference", model_spec_json=spec)
        db.add(product)
        other = DesignTask(status="waiting_input")
        db.add(other)
        db.flush()
        attach_task(db, session_id=headers["X-Session-Id"], task_id=other.id)
        db.commit()
        source_id, other_id = product.id, other.id
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, factory, space_url.replace("/space", "/home-design"), headers, stranger, source_id, other_id


def freeze(client, url, headers, source_id, key="freeze", version=1):
    return client.post(url + "/assets", headers=headers, json={
        "client_mutation_id": key, "kind": "product", "source_id": source_id,
        "source_version": version,
    })


def bound_document(asset):
    value = document()
    value["objects"][0].update(asset_id=asset["id"], size=asset["size"], material=asset["material"])
    return value


def test_source_change_does_not_change_frozen_asset_or_replay(assets_context):
    client, factory, url, headers, _, source_id, _ = assets_context
    first = freeze(client, url, headers, source_id)
    assert first.status_code in (200, 201), first.text
    asset = first.json()
    value = bound_document(asset)
    saved = client.put(url, headers=headers, json={"base_version": 0, "client_mutation_id": "save", "document": value})
    assert saved.status_code == 200, saved.text
    delivery = client.get(url + "/versions/1/delivery", headers=headers)
    assert delivery.status_code == 200, delivery.text
    with factory() as db:
        product = db.get(Product, source_id)
        product.name = "商品后来改名"
        product.model_spec_json = {"broken": True}
        product.record_version = 2
        product.is_active = False
        db.commit()
    assert freeze(client, url, headers, source_id).json() == asset
    assert client.get(url + f"/assets/{asset['id']}", headers=headers).json() == asset
    assert client.get(url + "/versions/1/delivery", headers=headers).json() == delivery.json()
    assert client.get(url + "/versions/1", headers=headers).json() == saved.json()


def test_asset_permission_and_size_tampering_fail_closed(assets_context):
    client, _, url, headers, stranger, source_id, other_id = assets_context
    first = freeze(client, url, headers, source_id)
    assert first.status_code in (200, 201), first.text
    asset = first.json()
    suffix = f"/assets/{asset['id']}"
    assert client.get(url + suffix, headers={"X-Session-ID": stranger}).status_code == 404
    assert client.get(f"/api/design/tasks/{other_id}/home-design" + suffix, headers=headers).status_code == 404
    value = bound_document(asset)
    value["objects"][0]["size"] = deepcopy(value["objects"][0]["size"])
    value["objects"][0]["size"]["width"] += 0.5
    result = client.put(url, headers=headers, json={"base_version": 0, "client_mutation_id": "tamper", "document": value})
    assert result.status_code == 422, result.text
    assert client.get(url, headers=headers).json()["version"] == 0


def test_freeze_rejects_client_model_snapshot(assets_context):
    client, _, url, headers, _, source_id, _ = assets_context
    result = client.post(url + "/assets", headers=headers, json={
        "client_mutation_id": "forged", "kind": "product", "source_id": source_id,
        "source_version": 1, "model_spec": {"伪造": True},
    })
    assert result.status_code == 422, result.text


@pytest.mark.parametrize("installation", [{"kind": "ceiling"}, {"kind": "wall", "wall_id": "missing"}])
def test_frozen_floor_asset_cannot_change_installation(assets_context, installation):
    client, _, url, headers, _, source_id, _ = assets_context
    asset = freeze(client, url, headers, source_id).json()
    value = bound_document(asset)
    value["objects"][0]["installation"] = installation
    result = client.put(url, headers=headers, json={
        "base_version": 0, "client_mutation_id": "mount-change", "document": value,
    })
    assert result.status_code == 422, result.text
    assert client.get(url, headers=headers).json()["version"] == 0


@pytest.mark.parametrize("broken", ["empty_materials", "empty_parts", "unknown_generator"])
def test_bad_catalog_model_is_unavailable_not_success_or_server_error(assets_context, broken):
    client, factory, url, headers, _, source_id, _ = assets_context
    with factory() as db:
        product = db.get(Product, source_id)
        spec = deepcopy(product.model_spec_json)
        rule = spec["确定性建模规则"]
        if broken == "empty_materials":
            rule["材质槽"] = []
            rule["部件"] = []
        elif broken == "empty_parts":
            rule["部件"] = []
        else:
            rule["生成器"] = "unknown_renderer"
        product.model_spec_json = spec
        db.commit()
    with TestClient(client.app, raise_server_exceptions=False) as checked:
        options = checked.get(url + "/asset-options?kind=product", headers=headers)
        assert options.status_code == 200, options.text
        option = next(item for item in options.json()["items"] if item["source_id"] == source_id)
        assert not option["available"]
        result = freeze(checked, url, headers, source_id)
        assert result.status_code == 422, result.text
