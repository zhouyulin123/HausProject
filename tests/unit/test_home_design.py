"""家装引用与几何约束。"""

from copy import deepcopy
import pytest
from pydantic import ValidationError

from app.schemas.home_design import HomeDesignDocument
from app.schemas.spatial import SpatialDocument
from app.services.home_design_validation import validate_design
from tests.unit.test_spatial_document import document as space_document


def document():
    return {
        "schema_version": "home-design/1.0",
        "space_version": 1,
        "surfaces": [],
        "objects": [
            {
                "id": "o1",
                "room_id": "r1",
                "name": "书桌",
                "category": "furniture",
                "position": {"x": 2, "y": 0, "z": 1.5},
                "size": {"width": 1, "height": 1, "depth": 1},
                "rotation": 0,
                "material": {"name": "木色", "color": "#aabbcc"},
            }
        ],
    }


def validate(value, space=None):
    base = space or space_document()
    base["scale_status"] = "confirmed"
    return validate_design(
        HomeDesignDocument.model_validate(value), SpatialDocument.model_validate(base)
    )


def test_valid_and_vertical_contact():
    value = document()
    upper = deepcopy(value["objects"][0])
    upper["id"] = "upper"
    upper["position"]["y"] = 1
    value["objects"].append(upper)
    assert validate(value).valid
    upper["position"]["y"] = 0.9
    assert [x.code for x in validate(value).issues] == ["object_collision"]


def test_rotated_box_boundary_and_ceiling():
    value = document()
    value["objects"][0]["position"]["x"] = 0.5
    value["objects"][0]["rotation"] = 45
    value["objects"][0]["position"]["y"] = 2
    assert {x.code for x in validate(value).issues} == {
        "object_outside_room",
        "object_above_ceiling",
    }


def test_concave_notch_crossing_is_outside_even_when_corners_inside():
    base = space_document()
    base["rooms"][0]["polygon"] = [
        {"x": x, "z": z}
        for x, z in [(0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (1, 1), (1, 4), (0, 4)]
    ]
    value = document()
    item = value["objects"][0]
    item["position"]["z"] = 2
    item["size"]["width"] = 3.5
    assert validate(value, base).issues[0].code == "object_outside_room"


@pytest.mark.parametrize("change", ["room", "wall", "duplicate", "color", "nan"])
def test_invalid_contract_and_references(change):
    value = document()
    if change == "room":
        value["objects"][0]["room_id"] = "missing"
    if change == "wall":
        value["surfaces"] = [
            {
                "id": "s",
                "room_id": "r1",
                "kind": "wall",
                "wall_id": "missing",
                "material": {"name": "白", "color": "#ffffff"},
            }
        ]
    if change == "duplicate":
        value["objects"] *= 2
    if change == "color":
        value["objects"][0]["material"]["color"] = "red"
    if change == "nan":
        value["objects"][0]["rotation"] = float("nan")
    with pytest.raises((ValueError, ValidationError)):
        validate(value)


def test_opening_obstruction_honors_vertical_range():
    space = space_document()
    space["walls"] = [
        {
            "id": "w",
            "room_ids": ["r1"],
            "start": {"x": 0, "z": 0},
            "end": {"x": 4, "z": 0},
            "height": 2.8,
            "thickness": 0.2,
        }
    ]
    space["openings"] = [
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
    value = document()
    value["objects"][0]["position"] = {"x": 1.5, "y": 0, "z": 0.5}
    assert "opening_obstructed" in {x.code for x in validate(value, space).issues}
    value["objects"][0]["position"]["y"] = 2
    assert "opening_obstructed" not in {x.code for x in validate(value, space).issues}


def test_extreme_valid_coordinates_report_outside_without_crashing():
    value = document()
    value["objects"][0]["position"]["x"] = 10000
    assert validate(value).issues[0].code == "object_outside_room"


def test_surface_identity_and_wall_reference_contract():
    value = document()
    surface = {
        "id": "floor",
        "room_id": "r1",
        "kind": "floor",
        "material": {"name": "灰", "color": "#ffffff"},
    }
    value["surfaces"] = [surface]
    assert validate(value).valid
    second = deepcopy(surface)
    second["id"] = "other-floor"
    value["surfaces"].append(second)
    with pytest.raises(ValueError):
        validate(value)


def test_surface_quote_rule_is_explicit_and_legacy_serialization_stays_unchanged():
    value = document()
    surface = {
        "id": "floor",
        "room_id": "r1",
        "kind": "floor",
        "material": {"name": "灰", "color": "#ffffff"},
    }
    value["surfaces"] = [surface]

    legacy = HomeDesignDocument.model_validate(value).model_dump(mode="json")
    assert "quote_rule_id" not in legacy["surfaces"][0]
    assert legacy["surfaces"][0]["material"] == surface["material"]

    value["surfaces"][0]["quote_rule_id"] = 17
    explicit = HomeDesignDocument.model_validate(value).model_dump(mode="json")
    assert explicit["surfaces"][0]["quote_rule_id"] == 17

    value["surfaces"][0]["quote_rule_id"] = True
    with pytest.raises(ValidationError):
        HomeDesignDocument.model_validate(value)
    value["surfaces"] = [surface]
    surface["wall_id"] = "wall"
    with pytest.raises(ValueError):
        validate(value)


@pytest.mark.parametrize(
    "x,y,z,height,expected",
    [
        (3, 0, 0.5, 1, True),
        (3, 0, 0.6, 1, False),
        (1.5, 0, 0.5, 1, False),
        (1.5, 2, 0.5, 0.2, True),
        (3, 2.6, 0.5, 0.2, False),
    ],
)
def test_wall_solids_respect_holes_contact_and_height(x, y, z, height, expected):
    space = space_document()
    space["walls"] = [
        {
            "id": "w",
            "room_ids": ["r1"],
            "start": {"x": 0, "z": 0},
            "end": {"x": 4, "z": 0},
            "height": 2.6,
            "thickness": 0.2,
        }
    ]
    space["openings"] = [
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
    value = document()
    value["objects"][0]["position"] = {"x": x, "y": y, "z": z}
    value["objects"][0]["size"]["height"] = height
    assert (
        "object_wall_collision" in {i.code for i in validate(value, space).issues}
    ) == expected


def test_dense_collisions_have_bounded_explicit_diagnostics():
    value = document()
    value["objects"] = [
        dict(deepcopy(value["objects"][0]), id=f"o{i}") for i in range(500)
    ]
    result = validate(value)
    assert not result.valid
    assert len(result.issues) == 201
    assert result.issues[-1].code == "validation_issue_limit"
    assert result.model_dump() == validate(value).model_dump()
    value["objects"][-1]["room_id"] = "missing"
    with pytest.raises(ValueError, match="房间不存在"):
        validate(value)
