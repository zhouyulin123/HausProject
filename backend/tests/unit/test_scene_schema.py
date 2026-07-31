import pytest
from pydantic import ValidationError

from app.schemas.scenes import SceneDocument


def _valid_scene() -> dict:
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
        "openings": [
            {
                "id": "door-1",
                "type": "door",
                "wallIndex": 0,
                "offset": 0.5,
                "width": 0.9,
                "height": 2.1,
                "sillHeight": 0,
            }
        ],
        "items": [
            {
                "instanceId": "sofa-main",
                "sku": "SOFA-001",
                "transform": {
                    "position": {"x": 2.5, "y": 0, "z": 3.2},
                    "rotation": {"x": 0, "y": 3.1416, "z": 0},
                    "scale": {"x": 1, "y": 1, "z": 1},
                },
            }
        ],
    }


@pytest.mark.unit
def test_scene_document_accepts_canonical_web_3d_payload():
    scene = SceneDocument.model_validate(_valid_scene())

    payload = scene.model_dump(by_alias=True, mode="json")

    assert payload["schemaVersion"] == "1.0"
    assert payload["coordinateSystem"] == "right-handed-y-up"
    assert payload["room"]["floorPolygon"][2] == {"x": 5.0, "z": 4.0}
    assert payload["items"][0]["instanceId"] == "sofa-main"


@pytest.mark.unit
def test_scene_document_rejects_degenerate_floor_polygon():
    payload = _valid_scene()
    payload["room"]["floorPolygon"] = [
        {"x": 0, "z": 0},
        {"x": 1, "z": 1},
        {"x": 2, "z": 2},
    ]

    with pytest.raises(ValidationError, match="有效面积"):
        SceneDocument.model_validate(payload)


@pytest.mark.unit
def test_scene_document_rejects_duplicate_instance_ids():
    payload = _valid_scene()
    payload["items"].append(
        {
            **payload["items"][0],
            "sku": "TABLE-001",
        }
    )

    with pytest.raises(ValidationError, match="instanceId"):
        SceneDocument.model_validate(payload)


@pytest.mark.unit
def test_scene_document_rejects_opening_for_unknown_wall():
    payload = _valid_scene()
    payload["openings"][0]["wallIndex"] = 4

    with pytest.raises(ValidationError, match="wallIndex"):
        SceneDocument.model_validate(payload)

