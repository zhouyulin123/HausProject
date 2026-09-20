"""概念交付接口的隔离权限与版本一致性测试。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes import home_design, home_design_delivery
from app.db.database import get_db
from app.db.models import HomeDesignVersion
from tests.integration.test_spatial_api import context as spatial_context, request  # noqa: F401
from tests.unit.test_home_design import document


@pytest.fixture
def delivery_context(spatial_context):  # noqa: F811
    spatial, factory, space_url, headers, stranger = spatial_context
    body = request()
    body["document"]["scale_status"] = "confirmed"
    assert spatial.put(space_url, headers=headers, json=body).status_code == 200
    app = FastAPI()
    app.include_router(home_design.router, prefix="/api/design/tasks")
    app.include_router(home_design_delivery.router, prefix="/api/design/tasks")

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    url = space_url.replace("/space", "/home-design")
    with TestClient(app) as client:
        assert (
            client.put(
                url,
                headers=headers,
                json={
                    "base_version": 0,
                    "client_mutation_id": "first",
                    "document": document(),
                },
            ).status_code
            == 200
        )
        yield client, url, headers, stranger, spatial, space_url, factory


def test_delivery_and_comparison_enforce_ownership_and_parameter_bounds(
    delivery_context,
):
    client, url, headers, stranger, *_ = delivery_context
    for suffix in ("/versions/1/delivery", "/compare?from_version=1&to_version=1"):
        assert (
            client.get(url + suffix, headers={"X-Session-Id": stranger}).status_code
            == 404
        )
        assert client.get(url + suffix).status_code == 422
        response = client.get(url + suffix, headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
    assert client.get(url + "/versions/0/delivery", headers=headers).status_code == 422
    assert (
        client.get(
            url + "/compare?from_version=0&to_version=1", headers=headers
        ).status_code
        == 422
    )
    assert (
        client.get(url + "/versions/999/delivery", headers=headers).status_code == 404
    )
    assert (
        client.get(
            url + "/compare?from_version=1&to_version=999", headers=headers
        ).status_code
        == 404
    )


def test_export_stays_bound_to_old_space_and_never_writes(delivery_context):
    client, url, headers, _, spatial, space_url, _ = delivery_context
    old = client.get(url + "/versions/1/delivery", headers=headers).json()
    body = request(1, "higher")
    body["document"]["scale_status"] = "confirmed"
    body["document"]["rooms"][0]["height"] = 3
    assert spatial.put(space_url, headers=headers, json=body).status_code == 200
    assert client.get(url + "/versions/1/delivery", headers=headers).json() == old
    assert client.get(url, headers=headers).json()["version"] == 1
    assert len(client.get(url + "/versions", headers=headers).json()["versions"]) == 1
    updated = document()
    updated["space_version"] = 2
    updated["objects"][0]["name"] = "新名字"
    assert (
        client.put(
            url,
            headers=headers,
            json={
                "base_version": 1,
                "client_mutation_id": "second",
                "document": updated,
            },
        ).status_code
        == 200
    )
    diff = client.get(
        url + "/compare?from_version=1&to_version=2", headers=headers
    ).json()
    assert diff["space_changed"]
    assert diff["changes"][0]["changed_fields"] == ["name"]


def test_missing_bound_space_and_corrupt_saved_json_fail_closed(delivery_context):
    client, url, headers, _, _, _, factory = delivery_context
    with factory() as db:
        row = db.scalar(select(HomeDesignVersion))
        value = dict(row.document_json)
        value["space_version"] = 999
        row.document_json = value
        db.commit()
    assert client.get(url + "/versions/1/delivery", headers=headers).status_code == 404
    with factory() as db:
        row = db.scalar(select(HomeDesignVersion))
        row.document_json = {"invalid": True}
        db.commit()
    result = client.get(url + "/versions/1/delivery", headers=headers)
    assert result.status_code == 422
    assert result.json()["detail"]["code"] == "home_delivery_invalid"
