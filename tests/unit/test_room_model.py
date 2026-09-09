import pytest
from pydantic import ValidationError

from app.schemas.room_model import RoomModel
from app.services.room_model_service import (
    apply_calibration,
    room_model_from_analysis,
    room_model_to_scene,
)


def _valid_room_model() -> dict:
    return {
        "schemaVersion": "1.0",
        "imageKind": "floor_plan",
        "spaceType": "客厅",
        "roomCount": "三室两厅",
        "rooms": [
            {
                "id": "living-room",
                "name": "客厅",
                "floorPolygon": [
                    {"x": 0.0, "z": 0.0},
                    {"x": 1.0, "z": 0.0},
                    {"x": 1.0, "z": 0.8},
                    {"x": 0.0, "z": 0.8},
                ],
                "ceilingHeight": None,
                "confidence": 0.85,
            }
        ],
        "walls": [
            {
                "roomId": "living-room",
                "wallIndex": 0,
                "loadBearing": None,
                "confidence": 0.6,
            }
        ],
        "doors": [
            {
                "id": "door-1",
                "roomId": "living-room",
                "type": "door",
                "wallIndex": 0,
                "offset": 0.4,
                "width": 0.12,
                "height": 2.1,
                "sillHeight": 0,
                "confidence": 0.7,
            }
        ],
        "windows": [
            {
                "id": "win-1",
                "roomId": "living-room",
                "type": "window",
                "wallIndex": 2,
                "offset": 0.3,
                "width": 0.35,
                "height": 1.5,
                "sillHeight": 0.9,
                "confidence": 0.7,
            }
        ],
        "fixedObstacles": [],
        "existingFurniture": [
            {
                "name": "布艺沙发",
                "category": "沙发",
                "roomId": "living-room",
                "confidence": 0.6,
            }
        ],
        "scale": {
            "source": "default",
            "referenceWallLength": None,
            "referenceRoomId": None,
            "referenceWallIndex": None,
            "confidence": 0.3,
        },
        "confidence": 0.7,
        "requiresConfirmation": ["roomDimensions", "doorWidth"],
        "analysisNotes": ["客厅采光良好", "动线清晰"],
        "suggestions": ["建议增加收纳"],
    }


@pytest.mark.unit
def test_room_model_accepts_canonical_payload():
    model = RoomModel.model_validate(_valid_room_model())

    assert model.rooms[0].name == "客厅"
    assert model.doors[0].type == "door"
    assert model.windows[0].sill_height == 0.9
    assert model.image_kind == "floor_plan"
    assert model.space_type == "客厅"


@pytest.mark.unit
def test_room_model_rejects_unknown_room_reference():
    payload = _valid_room_model()
    payload["doors"][0]["roomId"] = "bedroom"

    with pytest.raises(ValidationError, match="不存在的房间"):
        RoomModel.model_validate(payload)


@pytest.mark.unit
def test_room_model_rejects_opening_out_of_wall_range():
    payload = _valid_room_model()
    payload["doors"][0]["wallIndex"] = 4

    with pytest.raises(ValidationError, match="超出房间墙体范围"):
        RoomModel.model_validate(payload)


@pytest.mark.unit
def test_room_model_to_scene_maps_polygon_to_centered_meters():
    model = RoomModel.model_validate(_valid_room_model())
    scene = room_model_to_scene(model, dimensions=(4.6, 5.6))

    assert scene.room.id == "living-room"
    assert scene.room.floor_polygon[0].x == pytest.approx(-2.3)
    assert scene.room.floor_polygon[2].x == pytest.approx(2.3)
    assert scene.room.floor_polygon[2].z == pytest.approx(2.8)
    # 未校准时层高兜底 2.8
    assert scene.room.ceiling_height == pytest.approx(2.8)


@pytest.mark.unit
def test_room_model_to_scene_maps_openings():
    model = RoomModel.model_validate(_valid_room_model())
    scene = room_model_to_scene(model, dimensions=(4.6, 5.6))

    door = next(o for o in scene.openings if o.type == "door")
    window = next(o for o in scene.openings if o.type == "window")

    # 门在 wall_index 0（底边，墙长 4.6m）：offset/width 由归一化换算
    assert door.wall_index == 0
    assert door.offset == pytest.approx(0.4 * 4.6)
    assert door.width == pytest.approx(0.12 * 4.6)
    # 窗在 wall_index 2（顶边），保留窗台高度
    assert window.wall_index == 2
    assert window.width == pytest.approx(0.35 * 4.6)
    assert window.sill_height == pytest.approx(0.9)


@pytest.mark.unit
def test_room_model_to_scene_uses_default_size_when_no_dimensions():
    model = RoomModel.model_validate(_valid_room_model())
    scene = room_model_to_scene(model)

    # 客厅默认 4.6×5.6
    assert scene.room.floor_polygon[0].x == pytest.approx(-2.3)
    assert scene.room.floor_polygon[2].z == pytest.approx(2.8)


@pytest.mark.unit
def test_room_model_to_scene_emits_empty_items():
    model = RoomModel.model_validate(_valid_room_model())
    scene = room_model_to_scene(model)

    assert scene.items == []
    assert scene.camera is not None


@pytest.mark.unit
def test_room_model_from_analysis_roundtrip():
    analysis = {"room_model": _valid_room_model(), "findings": ["x"]}
    model = room_model_from_analysis(analysis)

    assert model is not None
    assert model.rooms[0].name == "客厅"

    assert room_model_from_analysis({"findings": []}) is None
    assert room_model_from_analysis({}) is None
    assert room_model_from_analysis({"room_model": {"bad": 1}}) is None


@pytest.mark.unit
def test_room_model_to_scene_prefers_room_dimensions():
    payload = _valid_room_model()
    payload["rooms"][0]["widthM"] = 4.0
    payload["rooms"][0]["depthM"] = 5.0
    model = RoomModel.model_validate(payload)

    scene = room_model_to_scene(model)

    assert scene.room.floor_polygon[0].x == pytest.approx(-2.0)
    assert scene.room.floor_polygon[2].z == pytest.approx(2.5)


@pytest.mark.unit
def test_apply_calibration_sets_dimensions_and_marks_user_scale():
    model = RoomModel.model_validate(_valid_room_model())
    calibrated = apply_calibration(
        model,
        width_m=4.0,
        depth_m=5.0,
        ceiling_height=3.0,
    )

    assert calibrated.rooms[0].width_m == 4.0
    assert calibrated.rooms[0].depth_m == 5.0
    assert calibrated.rooms[0].ceiling_height == 3.0
    assert calibrated.scale.source == "user"
    assert calibrated.scale.confidence == 1.0
    # 尺寸相关项被移除，门窗宽度仍保留待确认
    assert "roomDimensions" not in calibrated.requires_confirmation
    assert "doorWidth" in calibrated.requires_confirmation
