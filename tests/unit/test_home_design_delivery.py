"""整屋概念交付的确定性计量边界。"""

from copy import deepcopy

import pytest

from app.schemas.home_design import HomeDesignDocument
from app.schemas.spatial import SpatialDocument
from app.services.home_design_delivery import (
    build_delivery,
    compare_deliveries,
    _surface_area,
)
from tests.unit.test_home_design import document
from tests.unit.test_spatial_document import document as spatial_document


def documents():
    space = spatial_document()
    space["scale_status"] = "confirmed"
    home = document()
    home["surfaces"] = [
        {
            "id": "floor",
            "room_id": "r1",
            "kind": "floor",
            "material": {"name": "地砖", "color": "#eeeeee"},
        }
    ]
    return HomeDesignDocument.model_validate(home), SpatialDocument.model_validate(
        space
    )


def build(home, space, version=1):
    return build_delivery(task_id=1, version=version, document=home, space=space)


def test_quantities_are_not_prices_and_digest_is_stable():
    home, space = documents()
    result = build(home, space)
    lines = {line["id"]: line for line in result["lines"]}
    assert lines["floor"]["quantity"] == 12
    assert lines["floor"]["unit"] == "m2"
    assert "quote_rule_id" not in lines["floor"]
    assert lines["o1"]["quantity"] == 1
    assert all(
        line["unit_price"] is None and line["total_price"] is None
        for line in result["lines"]
    )
    assert result["total_price"] is None
    assert result["purpose"] == "concept_review"
    assert result["content_digest"] == build(home, space)["content_digest"]
    assert result["limitations"]


def test_delivery_only_exposes_an_explicit_surface_quote_rule():
    home, space = documents()
    home.surfaces[0].quote_rule_id = 23

    line = build(home, space)["lines"][0]

    assert line["quote_rule_id"] == 23


def test_unconfirmed_scale_keeps_area_unknown_but_counts_objects():
    home, space = documents()
    space.scale_status = "unconfirmed"
    result = build(home, space)
    assert result["lines"][0]["quantity"] is None
    assert result["lines"][0]["quantity_status"] == "pending_scale"
    assert result["lines"][1]["quantity"] == 1
    assert not result["validation"]["valid"]


def test_wall_area_subtracts_openings_and_shared_sides_are_separate():
    home, space = documents()
    raw = space.model_dump()
    raw["rooms"].append(
        {
            "id": "r2",
            "name": "次卧",
            "height": 2.8,
            "polygon": [
                {"x": x, "z": z} for x, z in [(0, -3), (4, -3), (4, 0), (0, 0)]
            ],
        }
    )
    raw["walls"] = [
        {
            "id": "w",
            "room_ids": ["r1", "r2"],
            "start": {"x": 0, "z": 0},
            "end": {"x": 4, "z": 0},
            "height": 2.8,
            "thickness": 0.2,
        }
    ]
    raw["openings"] = [
        {
            "id": "door",
            "wall_id": "w",
            "type": "door",
            "offset": 1,
            "width": 1,
            "height": 2,
            "sill_height": 0,
        }
    ]
    value = home.model_dump()
    value["surfaces"] = [
        {
            "id": room_id,
            "room_id": room_id,
            "kind": "wall",
            "wall_id": "w",
            "material": {"name": "涂料", "color": "#ffffff"},
        }
        for room_id in ("r1", "r2")
    ]
    result = build(
        HomeDesignDocument.model_validate(value), SpatialDocument.model_validate(raw)
    )
    assert [
        line["quantity"] for line in result["lines"] if line["entity_type"] == "surface"
    ] == [9.2, 9.2]


def test_space_only_change_appears_in_comparison_and_old_snapshot_stays_same():
    home, space = documents()
    before = build(home, space)
    changed = deepcopy(space)
    changed.rooms[0].polygon[1].x = 5
    changed.rooms[0].polygon[2].x = 5
    home.space_version = 2
    after = build(home, changed, 2)
    result = compare_deliveries(before, after)
    assert result["space_changed"]
    assert result["changes"][0]["id"] == "floor"
    assert "quantity" in result["changes"][0]["changed_fields"]
    assert before["lines"][0]["quantity"] == 12
    assert after["lines"][0]["quantity"] == 15


def test_missing_surface_reference_fails_not_estimates():
    home, space = documents()
    home.surfaces[0].room_id = "missing"
    with pytest.raises(ValueError):
        build(home, space)


def test_wall_metering_clips_partial_boundary_and_openings():
    home, space = documents()
    raw = space.model_dump()
    raw["walls"] = [
        {
            "id": "w",
            "room_ids": ["r1"],
            "start": {"x": 0, "z": 0},
            "end": {"x": 4, "z": 0},
            "height": 2.8,
            "thickness": 0.2,
        }
    ]
    raw["openings"] = [
        {
            "id": "window",
            "wall_id": "w",
            "type": "window",
            "offset": 1.5,
            "width": 1,
            "height": 1,
            "sill_height": 1.5,
        }
    ]
    space = SpatialDocument.model_validate(raw)
    value = home.model_dump()
    value["surfaces"][0].update(kind="wall", wall_id="w")
    home = HomeDesignDocument.model_validate(value)
    # 直接验证计量边界：现有空间准入禁止部分邻接，不放宽空间契约。
    space.rooms[0].polygon[1].x = 2
    space.rooms[0].polygon[2].x = 2
    space.rooms[0].height = 2
    assert _surface_area(home.surfaces[0], space) == pytest.approx(3.75)
    space.rooms[0].polygon = [
        point.model_copy(update={"z": point.z + 10}) for point in space.rooms[0].polygon
    ]
    assert _surface_area(home.surfaces[0], space) is None


def test_comparison_handles_add_remove_and_same_ids_across_entity_types():
    home, space = documents()
    home.surfaces[0].id = "o1"
    before = build(home, space)
    home.objects[0].id = "new-object"
    home.surfaces[0].material.color = "#ff0000"
    after = build(home, space, 2)
    diff = compare_deliveries(before, after)
    assert {
        (item["entity_type"], item["id"], item["change"]) for item in diff["changes"]
    } == {
        ("surface", "o1", "modified"),
        ("object", "o1", "removed"),
        ("object", "new-object", "added"),
    }
    assert compare_deliveries(before, before)["changes"] == []


def test_concave_area_and_empty_design_are_not_full_home_quote():
    home, space = documents()
    raw = space.model_dump()
    raw["rooms"][0]["polygon"] = [
        {"x": x, "z": z} for x, z in [(0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3)]
    ]
    space = SpatialDocument.model_validate(raw)
    home.objects = []
    home.surfaces[0].kind = "ceiling"
    assert build(home, space)["lines"][0]["quantity"] == 6
    home.surfaces = []
    result = build(home, space)
    assert result["total_price"] is None
    assert result["gaps"][0]["code"] == "no_design_elements"


def test_space_change_can_alter_validation_without_object_edits():
    home, space = documents()
    home.objects[0].size.height = 2.5
    before = build(home, space)
    space.rooms[0].height = 2.2
    home.space_version = 2
    after = build(home, space, 2)
    diff = compare_deliveries(before, after)
    assert diff["validation_changed"]
    assert diff["before_validation"]["valid"]
    assert not diff["after_validation"]["valid"]


def test_point_changes_are_compared_without_becoming_procurement_items():
    from app.schemas.home_design import DesignPoint

    home, space = documents()
    before = build(home, space)
    home.points = [DesignPoint(id="socket", name="插座", room_id=home.objects[0].room_id,
        kind="socket", position={"x": 1, "y": 0.3, "z": 1}, confirmed=False)]
    after = build(home, space, 2)
    added = compare_deliveries(before, after)["changes"]
    assert len(added) == 1
    assert added[0]["entity_type"] == "point"
    assert added[0]["change"] == "added"
    assert added[0]["after_line"] is None
    assert len(before["lines"]) == len(after["lines"])
    home.points[0].confirmed = True
    modified = compare_deliveries(after, build(home, space, 3))["changes"]
    assert modified[0]["changed_fields"] == ["confirmed"]
