"""影响比较不依赖名称匹配或数组顺序。"""

from app.schemas.spatial import SpatialDocument
from app.schemas.home_design import HomeDesignDocument
from app.services.home_design_impact_service import compare_spaces, reference_issues
from tests.unit.test_spatial_document import document
from tests.unit.test_home_design import document as home_document


def test_top_level_scale_source_and_image_reference_are_reported():
    source = SpatialDocument.model_validate(document())
    target = source.model_copy(deep=True)
    target.scale_status = "confirmed"
    target.source_image_id = 10
    target.image_reference = {"origin": {"x": 0, "z": 0}, "width": 4, "depth": 3}
    changes = compare_spaces(source, target)
    assert {c.entity_id for c in changes} == {
        "scale_status",
        "source_image_id",
        "image_reference",
    }
    assert all(c.entity_type == "space" and c.change == "modified" for c in changes)


def test_wall_and_opening_modifications_use_stable_ids():
    value = document()
    value["walls"] = [
        {
            "id": "w",
            "start": {"x": 0, "z": 0},
            "end": {"x": 4, "z": 0},
            "room_ids": ["r1"],
            "height": 2.8,
            "thickness": 0.2,
        }
    ]
    value["openings"] = [
        {
            "id": "d",
            "wall_id": "w",
            "type": "door",
            "offset": 1,
            "width": 1,
            "height": 2,
            "sill_height": 0,
        }
    ]
    source = SpatialDocument.model_validate(value)
    target = source.model_copy(deep=True)
    target.walls[0].thickness = 0.3
    target.openings[0].offset = 2
    assert [
        (c.entity_type, c.entity_id, c.change) for c in compare_spaces(source, target)
    ] == [("wall", "w", "modified"), ("opening", "d", "modified")]
    target.walls = []
    target.openings = []
    assert all(c.change == "removed" for c in compare_spaces(source, target))


def test_missing_surface_room_and_wall_each_reported():
    value = home_document()
    value["surfaces"] = [
        {
            "id": "s",
            "room_id": "missing",
            "kind": "wall",
            "wall_id": "gone",
            "material": {"name": "白", "color": "#ffffff"},
        }
    ]
    issues = reference_issues(
        HomeDesignDocument.model_validate(value),
        SpatialDocument.model_validate(document()),
    )
    assert {i.code for i in issues} == {"room_missing", "wall_missing"}
