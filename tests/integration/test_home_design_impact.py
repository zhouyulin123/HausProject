"""空间版本切换只预览，不猜测引用、不修改历史。"""

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.routes import home_design
from app.db.database import get_db
from app.schemas.spatial import SpatialDocument
from tests.integration.test_spatial_api import context as spatial_context, request  # noqa: F401
from tests.unit.test_home_design import document
from tests.integration.test_home_assets_independent import (
    assets_context,  # noqa: F401
    freeze,
    bound_document,  # noqa: F401
)


@pytest.fixture
def impact_context(spatial_context):  # noqa: F811
    spatial, factory, space_url, headers, stranger = spatial_context
    first = request()
    first["document"]["scale_status"] = "confirmed"
    assert spatial.put(space_url, headers=headers, json=first).status_code == 200
    app = FastAPI()
    app.include_router(home_design.router, prefix="/api/design/tasks")

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client, spatial, factory, space_url, headers, stranger, first["document"]


def target(context, value):
    _, spatial, _, space_url, headers, _, _ = context
    saved = spatial.put(
        space_url,
        headers=headers,
        json={
            "base_version": 1,
            "client_mutation_id": "space-2",
            "document": value,
        },
    )
    assert saved.status_code == 200, saved.text


def preview(context, value=None, version=2, headers=None):
    client, _, _, space_url, owner, _, _ = context
    return client.post(
        space_url.replace("/space", "/home-design/space-impact"),
        headers=headers or owner,
        json={"document": value or document(), "target_space_version": version},
    )


def test_preview_preserves_document_history_and_performs_no_writes(impact_context):
    ctx = impact_context
    client, spatial, factory, space_url, headers, _, source = ctx
    changed = deepcopy(source)
    changed["rooms"][0]["height"] = 2
    target(ctx, changed)
    value = document()
    value["objects"][0]["size"]["height"] = 2.5
    url = space_url.replace("/space", "/home-design")
    saved = client.put(
        url,
        headers=headers,
        json={
            "base_version": 0,
            "client_mutation_id": "home-1",
            "document": value,
        },
    ).json()
    statements = []
    engine = factory.kw["bind"]

    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.strip())

    event.listen(engine, "before_cursor_execute", record)
    try:
        result = preview(ctx, value)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    body = result.json()
    expected = deepcopy(saved["document"])
    expected["space_version"] = 2
    assert body["candidate_document"] == expected
    assert body["can_apply"] is True
    assert body["validation"]["valid"] is False
    assert "object_above_ceiling" in {i["code"] for i in body["validation"]["issues"]}
    assert body["changes"] == [
        {"entity_type": "room", "entity_id": "r1", "change": "modified"}
    ]
    # 共享会话鉴权允许更新 last_seen_at，不允许写入任何设计业务表。
    writes = [
        sql
        for sql in statements
        if sql.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}
    ]
    assert all(
        sql.upper().startswith("UPDATE ANONYMOUS_SESSIONS SET") for sql in writes
    )
    assert client.get(url + "/versions/1", headers=headers).json() == saved
    assert client.get(url, headers=headers).json() == saved
    assert (
        spatial.get(space_url + "/versions/1", headers=headers).json()["document"]
        == SpatialDocument.model_validate(source).model_dump(mode="json")
    )


def test_concave_room_is_revalidated_without_moving_objects(impact_context):
    changed = deepcopy(impact_context[-1])
    changed["rooms"][0]["polygon"] = [
        {"x": x, "z": z}
        for x, z in [(0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (1, 1), (1, 4), (0, 4)]
    ]
    target(impact_context, changed)
    value = document()
    value["objects"][0]["size"]["width"] = 3.5
    value["objects"][0]["position"]["z"] = 2
    result = preview(impact_context, value).json()
    assert result["can_apply"]
    assert "object_outside_room" in {i["code"] for i in result["validation"]["issues"]}
    assert (
        result["candidate_document"]["objects"][0]["position"]
        == value["objects"][0]["position"]
    )


def test_removed_room_blocks_until_user_explicitly_rebinds(impact_context):
    changed = deepcopy(impact_context[-1])
    changed["rooms"][0]["id"] = "new-room"
    target(impact_context, changed)
    result = preview(impact_context).json()
    assert not result["can_apply"] and result["validation"] is None
    assert result["reference_issues"][0]["entity_id"] == "o1"
    assert {c["change"] for c in result["changes"]} == {"added", "removed"}
    value = document()
    value["objects"][0]["room_id"] = "new-room"
    assert preview(impact_context, value).json()["can_apply"]


@pytest.mark.parametrize("kind", ["missing", "wrong_room"])
def test_wall_reference_is_not_guessed(impact_context, kind):
    changed = deepcopy(impact_context[-1])
    if kind == "wrong_room":
        room = deepcopy(changed["rooms"][0])
        room["id"] = "r2"
        room["polygon"] = [{"x": p["x"] + 10, "z": p["z"]} for p in room["polygon"]]
        changed["rooms"].append(room)
        changed["walls"] = [
            {
                "id": "w1",
                "start": room["polygon"][0],
                "end": room["polygon"][1],
                "room_ids": ["r2"],
                "height": 2,
                "thickness": 0.2,
            }
        ]
    target(impact_context, changed)
    value = document()
    value["surfaces"] = [
        {
            "id": "s1",
            "room_id": "r1",
            "kind": "wall",
            "wall_id": "w1",
            "material": {"name": "白", "color": "#ffffff"},
        }
    ]
    result = preview(impact_context, value).json()
    assert not result["can_apply"] and result["validation"] is None
    assert result["reference_issues"][0]["entity_type"] == "surface"


@pytest.mark.parametrize("version", [1, 0, True, "2", 99])
def test_invalid_target_versions(impact_context, version):
    target(impact_context, deepcopy(impact_context[-1]))
    result = preview(impact_context, version=version)
    assert result.status_code == (404 if version == 99 else 422)


def test_unconfirmed_and_foreign_task_are_rejected(impact_context):
    changed = deepcopy(impact_context[-1])
    changed["scale_status"] = "unconfirmed"
    target(impact_context, changed)
    assert preview(impact_context).status_code == 422
    denied = preview(impact_context, headers={"X-Session-Id": impact_context[5]})
    assert denied.status_code == 404
    assert denied.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("field", ["size", "material", "height"])
def test_impact_cannot_bypass_frozen_asset_binding(assets_context, field):  # noqa: F811
    from app.db.models import DesignSpaceVersion

    client, factory, url, headers, _, source_id, _ = assets_context
    asset = freeze(client, url, headers, source_id).json()
    with factory() as db:
        source = db.query(DesignSpaceVersion).one()
        changed = deepcopy(source.document_json)
        changed["scale_status"] = "confirmed"
        db.add(
            DesignSpaceVersion(
                task_id=source.task_id,
                version=2,
                document_json=changed,
                client_mutation_id="second",
                mutation_digest="test",
            )
        )
        db.commit()
    value = bound_document(asset)
    item = value["objects"][0]
    if field == "size":
        item["size"]["width"] += 0.1
    elif field == "material":
        item["material"]["name"] = "伪造材质"
    else:
        item["position"]["y"] = 0.1
    response = client.post(
        url + "/space-impact",
        headers=headers,
        json={"document": value, "target_space_version": 2},
    )
    assert response.status_code == 422, response.text
    assert client.get(url, headers=headers).json()["version"] == 0


def test_changed_opening_is_compared_and_revalidated(impact_context):
    changed = deepcopy(impact_context[-1])
    changed["walls"] = [
        {
            "id": "w1",
            "start": {"x": 0, "z": 0},
            "end": {"x": 4, "z": 0},
            "room_ids": ["r1"],
            "height": 2.8,
            "thickness": 0.2,
        }
    ]
    changed["openings"] = [
        {
            "id": "door",
            "wall_id": "w1",
            "type": "door",
            "offset": 1,
            "width": 2,
            "height": 2.2,
            "sill_height": 0,
        }
    ]
    target(impact_context, changed)
    value = document()
    value["objects"][0]["position"]["z"] = 0.5
    result = preview(impact_context, value).json()
    assert {c["entity_type"] for c in result["changes"]} == {"wall", "opening"}
    assert "opening_obstructed" in {i["code"] for i in result["validation"]["issues"]}


def test_missing_source_and_empty_target_fail_closed(impact_context):
    from app.db.models import DesignSpaceVersion

    target(impact_context, deepcopy(impact_context[-1]))
    value = document()
    value["space_version"] = 99
    assert preview(impact_context, value).status_code == 404
    with impact_context[2]() as db:
        row = db.query(DesignSpaceVersion).filter_by(version=2).one()
        changed = deepcopy(row.document_json)
        changed["rooms"] = []
        row.document_json = changed
        db.commit()
    assert preview(impact_context).status_code == 422
