import pytest

from app.schemas.scenes import (
    Opening,
    PositiveVector3,
    RoomGeometry,
    SceneDocument,
    SceneItem,
    Transform,
    Vector2XZ,
    Vector3,
)
from app.services.layout_evaluator import evaluate_layout


def _room() -> RoomGeometry:
    return RoomGeometry(
        id="living-room",
        name="客厅",
        floor_polygon=[
            Vector2XZ(x=-3, z=-2.5),
            Vector2XZ(x=3, z=-2.5),
            Vector2XZ(x=3, z=2.5),
            Vector2XZ(x=-3, z=2.5),
        ],
        ceiling_height=2.8,
    )


def _item(
    instance_id: str,
    category: str,
    w: float,
    h: float,
    d: float,
    x: float,
    z: float,
    rotation_y: float = 0.0,
) -> SceneItem:
    return SceneItem(
        instance_id=instance_id,
        sku=f"SKU-{instance_id}",
        category=category,
        dimensions=PositiveVector3(x=w, y=h, z=d),
        transform=Transform(
            position=Vector3(x=x, y=h / 2, z=z),
            rotation=Vector3(x=0, y=rotation_y, z=0),
            scale=PositiveVector3(x=1, y=1, z=1),
        ),
    )


def _scene(items: list[SceneItem], openings: list[Opening] | None = None) -> SceneDocument:
    return SceneDocument(
        schema_version="1.0",
        unit="m",
        coordinate_system="right-handed-y-up",
        room=_room(),
        openings=openings or [],
        items=items,
        camera=None,
    )


# 标准客厅三件套：沙发靠后墙、电视柜对面、茶几在前，间距合理
def _good_items() -> list[SceneItem]:
    sofa = _item("sofa", "沙发", 2.2, 0.85, 0.95, 0, -1.875)
    tv = _item("tv", "柜子", 1.6, 1.9, 0.4, 0, 2.15, rotation_y=3.1416)
    tea = _item("tea", "茶几", 1.0, 0.42, 0.55, 0, -0.725)
    return [sofa, tv, tea]


@pytest.mark.unit
def test_evaluate_layout_accepts_good_layout():
    score = evaluate_layout(_scene(_good_items()))

    assert score.valid
    assert score.total >= 90
    assert score.issues == []


@pytest.mark.unit
def test_evaluate_layout_penalizes_item_outside_room():
    items = _good_items()
    items.append(_item("outside", "边几", 0.5, 0.5, 0.4, 4.5, 4.5))
    score = evaluate_layout(_scene(items))

    assert not score.valid
    assert any(issue.code == "out_of_room" for issue in score.issues)


@pytest.mark.unit
def test_evaluate_layout_penalizes_collision():
    items = _good_items()
    # 把茶几放到沙发正中间制造碰撞
    items = [
        _item("sofa", "沙发", 2.2, 0.85, 0.95, 0, -1.875),
        _item("tea", "茶几", 1.0, 0.42, 0.55, 0, -1.875),
    ]
    score = evaluate_layout(_scene(items))

    assert not score.valid
    assert any(issue.code == "collision" for issue in score.issues)


@pytest.mark.unit
def test_evaluate_layout_penalizes_blocked_door():
    opening = Opening(
        id="door-1",
        type="door",
        wall_index=0,
        offset=1.0,
        width=0.9,
        height=2.1,
        sill_height=0,
    )
    # 沙发放在门正前方，占用门口净空区（wall_index 0 = 底边，offset 1.0 处）
    items = [_item("sofa", "沙发", 2.2, 0.85, 0.95, -1.5, -1.875)]
    score = evaluate_layout(_scene(items, [opening]))

    assert not score.valid
    assert any(issue.code == "blocks_door" for issue in score.issues)


@pytest.mark.unit
def test_evaluate_layout_penalizes_unreasonable_viewing_distance():
    items = [
        _item("sofa", "沙发", 2.2, 0.85, 0.95, 0, -1.875),
        # 电视柜几乎贴到沙发背后，观看距离过近
        _item("tv", "柜子", 1.6, 1.9, 0.4, 0, -1.0, rotation_y=3.1416),
    ]
    score = evaluate_layout(_scene(items))

    assert any(issue.code == "viewing_distance" for issue in score.issues)


@pytest.mark.unit
def test_evaluate_layout_penalizes_oversized_item():
    # 沙发宽 5.8m 塞进 6m 房间，挤占主通道
    items = [_item("huge", "沙发", 5.8, 0.85, 1.0, 0, -1.5)]
    score = evaluate_layout(_scene(items))

    assert any(issue.code == "oversized" for issue in score.issues)


@pytest.mark.unit
def test_evaluate_layout_ignores_rug_for_collision():
    items = [
        _item("sofa", "沙发", 2.2, 0.85, 0.95, 0, -1.875),
        # 地毯与沙发重叠不应报碰撞（非阻挡类别）
        _item("rug", "地毯", 2.0, 0.02, 2.9, 0, -0.8),
    ]
    score = evaluate_layout(_scene(items))

    assert not any(issue.code == "collision" for issue in score.issues)
