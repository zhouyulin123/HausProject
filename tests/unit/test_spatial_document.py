"""整屋几何与拓扑契约，独立于既有单房间场景。"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.spatial import SpatialDocument


def room(room_id="r1", points=None):
    return {
        "id": room_id,
        "name": "房间",
        "height": 2.8,
        "polygon": [
            {"x": x, "z": z} for x, z in (points or [(0, 0), (4, 0), (4, 3), (0, 3)])
        ],
    }


def document():
    return {
        "schema_version": "spatial/1.0",
        "unit": "m",
        "scale_status": "unconfirmed",
        "source_image_id": None,
        "rooms": [room()],
        "walls": [],
        "openings": [],
    }


@pytest.mark.parametrize(
    "points",
    [
        [(4, 0), (8, 0), (8, 3), (4, 3)],
        [(4, 3), (8, 3), (8, 6), (4, 6)],
        [(5, 0), (9, 0), (9, 3), (5, 3)],
    ],
)
def test_boundary_contact_and_disjoint_rooms_are_allowed(points):
    payload = document()
    payload["rooms"].append(room("r2", points))
    assert len(SpatialDocument.model_validate(payload).rooms) == 2


def test_concave_polygon_with_room_in_notch_is_allowed():
    payload = document()
    payload["rooms"] = [
        room(points=[(0, 0), (5, 0), (5, 1), (1, 1), (1, 5), (0, 5)]),
        room("r2", [(2, 2), (4, 2), (4, 4), (2, 4)]),
    ]
    SpatialDocument.model_validate(payload)


@pytest.mark.parametrize(
    "points",
    [
        [(1, 1), (3, 1), (3, 2), (1, 2)],
        [(0, 0), (4, 0), (4, 3), (0, 3)],
        [(2, 0), (6, 0), (6, 3), (2, 3)],
        [(2, -2), (3, -2), (3, 5), (2, 5)],
        [(4, 1), (2, 0), (2, 2)],
    ],
)
def test_interior_overlap_is_rejected(points):
    payload = document()
    payload["rooms"].append(room("r2", points))
    with pytest.raises(ValidationError):
        SpatialDocument.model_validate(payload)


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (4, 3), (4, 0), (0, 3)],
        [(0, 0), (4, 0), (4, 0), (0, 3)],
        [(0, 0), (4, 0), (2, 0), (2, 3), (0, 3)],
        [(0, 0), (1, 0), (2, 0)],
        [(0, 0), (float("inf"), 0), (0, 3)],
    ],
)
def test_invalid_room_polygon_is_rejected(points):
    payload = document()
    payload["rooms"] = [room(points=points)]
    with pytest.raises(ValidationError):
        SpatialDocument.model_validate(payload)


def wall_document():
    payload = document()
    payload["walls"] = [
        {
            "id": "w1",
            "start": {"x": 0, "z": 0},
            "end": {"x": 4, "z": 0},
            "room_ids": ["r1"],
            "height": 2.8,
            "thickness": 0.12,
        }
    ]
    payload["openings"] = [
        {
            "id": "o1",
            "wall_id": "w1",
            "type": "door",
            "offset": 0.5,
            "width": 0.9,
            "height": 2.1,
            "sill_height": 0,
        }
    ]
    return payload


def test_valid_wall_opening_and_shared_wall():
    payload = wall_document()
    payload["rooms"].append(room("r2", [(0, -3), (4, -3), (4, 0), (0, 0)]))
    payload["walls"][0]["room_ids"].append("r2")
    SpatialDocument.model_validate(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["rooms"].append(deepcopy(d["rooms"][0])),
        lambda d: d.update(rooms=[]),
        lambda d: d["walls"][0].update(room_ids=["missing"]),
        lambda d: d["walls"][0].update(room_ids=["r1", "r1"]),
        lambda d: d["walls"][0].update(end={"x": 0, "z": 0}),
        lambda d: d["walls"][0].update(end={"x": 4, "z": 2}),
        lambda d: d["walls"][0].update(height=3.5),
        lambda d: d["walls"].append(deepcopy(d["walls"][0])),
        lambda d: d["openings"][0].update(wall_id="missing"),
        lambda d: d["openings"][0].update(offset=3.5),
        lambda d: d["openings"][0].update(height=3),
        lambda d: d["openings"].append({**d["openings"][0], "id": "o2"}),
        lambda d: d["openings"].append(deepcopy(d["openings"][0])),
    ],
)
def test_invalid_topology_is_rejected(mutate):
    payload = wall_document()
    mutate(payload)
    with pytest.raises(ValidationError):
        SpatialDocument.model_validate(payload)


def test_openings_may_touch_or_be_vertically_separate():
    payload = wall_document()
    payload["openings"] += [
        {**payload["openings"][0], "id": "o2", "offset": 1.4},
        {
            **payload["openings"][0],
            "id": "o3",
            "type": "window",
            "sill_height": 2.1,
            "height": 0.5,
        },
    ]
    SpatialDocument.model_validate(payload)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("angle", [0, 0.37, 1.57])
def test_concave_rooms_rotated_and_reversed_preserve_overlap_result(reverse, angle):
    from math import cos, sin

    def transform(points):
        result = [
            (x * cos(angle) - z * sin(angle), x * sin(angle) + z * cos(angle))
            for x, z in points
        ]
        return result[::-1] if reverse else result

    payload = document()
    payload["rooms"] = [
        room(points=transform([(0, 0), (5, 0), (5, 1), (1, 1), (1, 5), (0, 5)])),
        room("r2", transform([(1, 1), (4, 1), (4, 4), (1, 4)])),
    ]
    SpatialDocument.model_validate(payload)
    payload["rooms"][1] = room(
        "r2", transform([(0.5, 0.5), (4, 0.5), (4, 4), (0.5, 4)])
    )
    with pytest.raises(ValidationError):
        SpatialDocument.model_validate(payload)


def test_subdivided_collinear_boundary_is_supported():
    payload = wall_document()
    payload["rooms"][0]["polygon"].insert(1, {"x": 2, "z": 0})
    SpatialDocument.model_validate(payload)


def test_duplicate_geometric_walls_with_different_ids_are_rejected():
    payload = wall_document()
    payload["walls"].append({**payload["walls"][0], "id": "w2"})
    with pytest.raises(ValidationError):
        SpatialDocument.model_validate(payload)


@pytest.mark.parametrize(
    "field,value", [("height", 0), ("height", float("nan")), ("name", "  ")]
)
def test_room_fields_are_bounded(field, value):
    payload = document()
    payload["rooms"][0][field] = value
    with pytest.raises(ValidationError):
        SpatialDocument.model_validate(payload)


def test_room_and_collection_limits_are_enforced():
    payload = document()
    payload["rooms"] *= 51
    with pytest.raises(ValidationError):
        SpatialDocument.model_validate(payload)


def test_narrow_crossing_is_not_lost_by_orientation_product_tolerance():
    payload = document()
    payload["rooms"] = [
        room(points=[(0, 0), (0.004, 0), (0.004, 0.003), (0, 0.003)]),
        room("r2", [(-0.001, 0.0001), (0.005, -0.0002), (0.005, -0.001)]),
    ]
    with pytest.raises(ValidationError):
        SpatialDocument.model_validate(payload)


def test_small_self_crossing_polygon_with_nonzero_signed_area_is_rejected():
    payload = document()
    payload["rooms"] = [room(points=[(0, 0), (0.006, 0.004), (0.006, 0), (0, 0.006)])]
    with pytest.raises(ValidationError):
        SpatialDocument.model_validate(payload)
