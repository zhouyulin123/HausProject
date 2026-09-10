from copy import deepcopy

import pytest

from app.db.models import DesignPlanVersion, DesignSceneVersion, DesignTask
from app.schemas.open_geometry import OpenGeometryDesign, OpenGeometryVersion
from app.services.open_geometry_service import compile_open_geometry
pytestmark = pytest.mark.integration
pytest_plugins = ("tests.integration.test_scene_api",)


def _design(*, width_mm=1000, height_mm=1000, depth_mm=800):
    return OpenGeometryDesign.model_validate(
        {
            "schema_version": "furniture-open-geometry/1.0",
            "name": "开放几何测试椅",
            "description": "用于房间入场契约验证",
            "materials": [
                {
                    "id": "shell",
                    "name": "主体",
                    "base_color": "#AABBCC",
                    "roughness": 0.6,
                    "metallic": 0.0,
                }
            ],
            "parts": [
                {
                    "id": "seat_shell",
                    "name": "座椅主体",
                    "material_id": "shell",
                    "parent_id": None,
                    "position_mm": [200.0, height_mm / 2, 0.0],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "geometry": {
                        "type": "box",
                        "size_mm": [width_mm, height_mm, depth_mm],
                        "radius_mm": 20.0,
                    },
                }
            ],
        }
    )


def _install_open_geometry(factory, plan_version_id, *, design=None):
    selected = design or _design()
    model_spec = compile_open_geometry(selected)
    version = OpenGeometryVersion(
        version=1,
        source="llm",
        instruction="创建测试椅",
        design=selected,
        model_spec=model_spec,
    ).model_dump(mode="json")
    with factory() as db:
        plan = db.get(DesignPlanVersion, plan_version_id)
        task = db.get(DesignTask, plan.revision.task_id)
        root = deepcopy(task.agent_state_json or {})
        root["open_geometry_furniture"] = {
            "current_version": 1,
            "current": version,
            "history": [version],
        }
        task.agent_state_json = root
        db.commit()
        return task.id, model_spec


def _scene_payload():
    return {
        "schemaVersion": "1.0",
        "unit": "m",
        "coordinateSystem": "right-handed-y-up",
        "room": {
            "id": "living-room",
            "name": "客厅",
            "floorPolygon": [
                {"x": 0, "z": 0},
                {"x": 5, "z": 0},
                {"x": 5, "z": 4},
                {"x": 0, "z": 4},
            ],
            "ceilingHeight": 2.8,
            "wallThickness": 0.12,
        },
        "openings": [],
        "items": [],
    }


def _create_scene(client, owner_id, plan_version_id, *, payload=None):
    response = client.post(
        f"/api/design/plan-versions/{plan_version_id}/scene",
        headers={"X-Session-ID": owner_id},
        json={"scene": payload or _scene_payload()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _placement(*, base=1, mutation="open-place-001", version=1, x=1.2, z=1.0):
    return {
        "baseVersion": base,
        "clientMutationId": mutation,
        "openGeometryVersion": version,
        "position": {"x": x, "z": z},
        "rotationY": 0,
    }


def test_open_geometry_current_version_enters_room_as_frozen_idempotent_snapshot(
    scene_api_context,
):
    client, owner_id, stranger_id, plan_version_id = scene_api_context
    created = _create_scene(client, owner_id, plan_version_id)
    task_id, model_spec = _install_open_geometry(
        client.app.state.scene_db_factory,
        plan_version_id,
    )
    url = f"/api/design/scenes/{created['id']}/open-geometry-items"
    request = _placement()

    foreign = client.post(
        url,
        headers={"X-Session-ID": stranger_id},
        json=request,
    )
    added = client.post(url, headers={"X-Session-ID": owner_id}, json=request)
    replayed = client.post(url, headers={"X-Session-ID": owner_id}, json=request)

    assert foreign.status_code == 404
    assert added.status_code == replayed.status_code == 200
    assert added.json()["current_version"] == replayed.json()["current_version"] == 2
    assert added.json()["scene"]["schemaVersion"] == "1.1"
    item = next(
        value
        for value in added.json()["scene"]["items"]
        if value["sourceType"] == "open_geometry_draft"
    )
    assert item["instanceId"].startswith("open-geometry-")
    assert item["dimensions"] == {"x": 1.0, "y": 1.0, "z": 0.8}
    assert item["transform"]["position"]["y"] == 0.5
    assert item["openGeometryRef"]["taskId"] == task_id
    assert item["openGeometryRef"]["planVersionId"] == plan_version_id
    assert item["openGeometryRef"]["openGeometryVersion"] == 1
    assert item["openGeometryRef"]["introducedSceneVersion"] == 2
    assert item["openGeometryModelSpec"] == model_spec

    conflict = client.post(
        url,
        headers={"X-Session-ID": owner_id},
        json={**request, "position": {"x": 2.0, "z": 1.0}},
    )
    stale = client.post(
        url,
        headers={"X-Session-ID": owner_id},
        json=_placement(base=1, mutation="open-place-002", x=2.0),
    )
    assert conflict.status_code == stale.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "idempotency_conflict",
        "message": "client_mutation_id 已用于不同场景变更",
        "currentVersion": 2,
    }
    assert stale.json()["detail"] == {
        "code": "scene_version_conflict",
        "message": "场景已经更新到版本 2，请刷新后重试",
        "currentVersion": 2,
    }

    forged = added.json()["scene"]
    open_item = next(
        value for value in forged["items"] if value["sourceType"] == "open_geometry_draft"
    )
    open_item["openGeometryModelSpec"]["家具名称"] = "伪造模型"
    rejected = client.put(
        f"/api/design/scenes/{created['id']}",
        headers={"X-Session-ID": owner_id},
        json={"base_version": 2, "scene": forged},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "open_geometry_scene_binding_invalid"


def test_open_geometry_scene_only_accepts_current_version(scene_api_context):
    client, owner_id, _, plan_version_id = scene_api_context
    created = _create_scene(client, owner_id, plan_version_id)
    _install_open_geometry(client.app.state.scene_db_factory, plan_version_id)

    response = client.post(
        f"/api/design/scenes/{created['id']}/open-geometry-items",
        headers={"X-Session-ID": owner_id},
        json=_placement(version=2),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "open_geometry_scene_binding_invalid"
    restored = client.get(
        f"/api/design/scenes/{created['id']}",
        headers={"X-Session-ID": owner_id},
    )
    assert restored.json()["current_version"] == 1


def test_scene_create_rejects_client_forged_open_geometry_snapshot(
    scene_api_context,
):
    client, owner_id, _, plan_version_id = scene_api_context
    design = _design()
    model_spec = compile_open_geometry(design)
    payload = _scene_payload()
    payload["schemaVersion"] = "1.1"
    payload["items"] = [
        {
            "instanceId": "forged-open-1",
            "sku": model_spec["确定性建模规则"]["模型ID"],
            "category": "开放几何家具",
            "sourceType": "open_geometry_draft",
            "assetMode": "parametric",
            "dimensions": {"x": 1, "y": 1, "z": 0.8},
            "transform": {
                "position": {"x": 1, "y": 0.5, "z": 1},
                "rotation": {"x": 0, "y": 0, "z": 0},
                "scale": {"x": 1, "y": 1, "z": 1},
            },
            "openGeometryRef": {
                "taskId": 999,
                "planVersionId": plan_version_id,
                "introducedSceneVersion": 1,
                "openGeometryVersion": 1,
                "modelId": model_spec["确定性建模规则"]["模型ID"],
                "specDigest": "sha256:" + "0" * 64,
            },
            "openGeometryModelSpec": model_spec,
        }
    ]

    response = client.post(
        f"/api/design/plan-versions/{plan_version_id}/scene",
        headers={"X-Session-ID": owner_id},
        json={"scene": payload},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == (
        "open_geometry_scene_binding_invalid"
    )


@pytest.mark.parametrize(
    ("case", "design", "scene_changes", "position", "expected_code"),
    [
        ("boundary", _design(), {}, {"x": 0.2, "z": 2.0}, "item_exceeds_room"),
        (
            "collision",
            _design(),
            {"existing_open_geometry": True},
            {"x": 2.5, "z": 2.0},
            "item_collision",
        ),
        (
            "door",
            _design(),
            {
                "openings": [
                    {
                        "id": "door-main",
                        "type": "door",
                        "wallIndex": 0,
                        "offset": 2,
                        "width": 1,
                        "height": 2.1,
                        "sillHeight": 0,
                    }
                ]
            },
            {"x": 2.5, "z": 0.45},
            "door_clearance_blocked",
        ),
        (
            "ceiling",
            _design(height_mm=3000),
            {},
            {"x": 1.2, "z": 1.0},
            "item_exceeds_ceiling",
        ),
    ],
)
def test_open_geometry_placement_hard_constraints_roll_back_scene_version(
    scene_api_context,
    case,
    design,
    scene_changes,
    position,
    expected_code,
):
    client, owner_id, _, plan_version_id = scene_api_context
    payload = _scene_payload()
    if "openings" in scene_changes:
        payload["openings"] = scene_changes["openings"]
    created = _create_scene(client, owner_id, plan_version_id, payload=payload)
    _install_open_geometry(
        client.app.state.scene_db_factory,
        plan_version_id,
        design=design,
    )
    base_version = 1
    if scene_changes.get("existing_open_geometry"):
        first = client.post(
            f"/api/design/scenes/{created['id']}/open-geometry-items",
            headers={"X-Session-ID": owner_id},
            json=_placement(
                mutation="open-collision-existing-001",
                x=position["x"],
                z=position["z"],
            ),
        )
        assert first.status_code == 200, first.text
        base_version = 2

    response = client.post(
        f"/api/design/scenes/{created['id']}/open-geometry-items",
        headers={"X-Session-ID": owner_id},
        json=_placement(
            base=base_version,
            x=position["x"],
            z=position["z"],
            mutation=f"open-{case}-001",
        ),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "scene_hard_constraint_violation"
    assert expected_code in {
        issue["code"] for issue in response.json()["detail"]["issues"]
    }
    with client.app.state.scene_db_factory() as db:
        versions = db.query(DesignSceneVersion).filter(
            DesignSceneVersion.scene_id == created["id"]
        ).all()
        assert [version.version for version in versions] == list(
            range(1, base_version + 1)
        )


def test_blender_render_fails_closed_for_open_geometry_scene(scene_api_context):
    client, owner_id, _, plan_version_id = scene_api_context
    created = _create_scene(client, owner_id, plan_version_id)
    _install_open_geometry(client.app.state.scene_db_factory, plan_version_id)
    added = client.post(
        f"/api/design/scenes/{created['id']}/open-geometry-items",
        headers={"X-Session-ID": owner_id},
        json=_placement(),
    )
    assert added.status_code == 200, added.text

    for profile in ("preview", "final"):
        response = client.post(
            f"/api/design/scenes/{created['id']}/render-jobs",
            headers={"X-Session-ID": owner_id},
            json={"baseVersion": 2, "profile": profile},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == (
            "open_geometry_render_unsupported"
        )


def test_open_geometry_snapshot_can_be_reintroduced_from_scene_history(
    scene_api_context,
):
    client, owner_id, _, plan_version_id = scene_api_context
    headers = {"X-Session-ID": owner_id}
    created = _create_scene(client, owner_id, plan_version_id)
    _install_open_geometry(client.app.state.scene_db_factory, plan_version_id)
    added = client.post(
        f"/api/design/scenes/{created['id']}/open-geometry-items",
        headers=headers,
        json=_placement(),
    )
    version_two_scene = deepcopy(added.json()["scene"])
    deleted_scene = deepcopy(version_two_scene)
    deleted_scene["items"] = []
    deleted = client.put(
        f"/api/design/scenes/{created['id']}",
        headers=headers,
        json={"base_version": 2, "scene": deleted_scene},
    )
    assert deleted.status_code == 200

    restored = client.put(
        f"/api/design/scenes/{created['id']}",
        headers=headers,
        json={"base_version": 3, "scene": version_two_scene},
    )

    assert restored.status_code == 200, restored.text
    assert restored.json()["current_version"] == 4
    assert restored.json()["scene"]["items"][0]["openGeometryRef"][
        "introducedSceneVersion"
    ] == 2


def test_unrelated_historical_warning_does_not_block_new_open_geometry_item(
    scene_api_context,
):
    client, owner_id, _, plan_version_id = scene_api_context
    headers = {"X-Session-ID": owner_id}
    created = _create_scene(client, owner_id, plan_version_id)
    _install_open_geometry(client.app.state.scene_db_factory, plan_version_id)
    first = client.post(
        f"/api/design/scenes/{created['id']}/open-geometry-items",
        headers=headers,
        json=_placement(x=1, z=1),
    )
    warning_scene = deepcopy(first.json()["scene"])
    warning_scene["items"][0]["transform"]["position"]["x"] = 6
    moved_outside = client.put(
        f"/api/design/scenes/{created['id']}",
        headers=headers,
        json={"base_version": 2, "scene": warning_scene},
    )
    assert moved_outside.status_code == 200
    assert "item_exceeds_room" in {
        issue["code"] for issue in moved_outside.json()["validation"]["warnings"]
    }

    second = client.post(
        f"/api/design/scenes/{created['id']}/open-geometry-items",
        headers=headers,
        json=_placement(
            base=3,
            mutation="open-place-second-001",
            x=3,
            z=2,
        ),
    )

    assert second.status_code == 200, second.text
    assert second.json()["current_version"] == 4
