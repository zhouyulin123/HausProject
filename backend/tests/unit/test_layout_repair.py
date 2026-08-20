import pytest

from app.schemas.scenes import (
    PositiveVector3,
    RoomGeometry,
    SceneDocument,
    SceneItem,
    Transform,
    Vector2XZ,
    Vector3,
)
from app.services.layout_repair import repair_layout


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


def _scene(items: list[SceneItem]) -> SceneDocument:
    return SceneDocument(
        schema_version="1.0",
        unit="m",
        coordinate_system="right-handed-y-up",
        room=_room(),
        openings=[],
        items=items,
        camera=None,
    )


@pytest.mark.unit
def test_repair_clamps_out_of_bounds_item():
    scene = _scene([_item("sofa", "沙发", 2.2, 0.85, 0.95, 6.0, 6.0)])

    repaired, score = repair_layout(scene)

    assert not any(
        issue.code in {"out_of_room", "exceeds_room"} for issue in score.issues
    )
    assert repaired.items[0].transform.position.x < 3
    assert repaired.items[0].transform.position.z < 2.5


@pytest.mark.unit
def test_repair_separates_colliding_items():
    items = [
        _item("sofa-1", "沙发", 2.2, 0.85, 0.95, 0, -1.875),
        _item("sofa-2", "沙发", 2.2, 0.85, 0.95, 0, -1.875),
    ]
    scene = _scene(items)

    repaired, score = repair_layout(scene)

    assert not any(issue.code == "collision" for issue in score.issues)
    assert (
        repaired.items[0].transform.position.z
        != repaired.items[1].transform.position.z
        or repaired.items[0].transform.position.x
        != repaired.items[1].transform.position.x
    )


@pytest.mark.unit
def test_repair_adjusts_viewing_distance():
    items = [
        _item("sofa", "沙发", 2.2, 0.85, 0.95, 0, -1.875),
        _item("tv", "柜子", 1.6, 1.9, 0.4, 0, -1.0, rotation_y=3.1416),
    ]
    scene = _scene(items)

    repaired, score = repair_layout(scene)

    assert not any(
        issue.code == "viewing_distance" for issue in score.issues
    )
    tv = next(item for item in repaired.items if item.instance_id == "tv")
    sofa = next(item for item in repaired.items if item.instance_id == "sofa")
    assert abs(tv.transform.position.z - sofa.transform.position.z) >= 2.0


@pytest.mark.unit
def test_repair_keeps_good_layout_unchanged():
    items = [
        _item("sofa", "沙发", 2.2, 0.85, 0.95, 0, -1.875),
        _item("tv", "柜子", 1.6, 1.9, 0.4, 0, 2.15, rotation_y=3.1416),
        _item("tea", "茶几", 1.0, 0.42, 0.55, 0, -0.725),
    ]
    scene = _scene(items)

    repaired, score = repair_layout(scene)

    assert score.valid
    # 正确布局应保持不变（各家具位置一致）
    for original, fixed in zip(scene.items, repaired.items):
        assert original.transform.position.x == pytest.approx(
            fixed.transform.position.x
        )
        assert original.transform.position.z == pytest.approx(
            fixed.transform.position.z
        )
