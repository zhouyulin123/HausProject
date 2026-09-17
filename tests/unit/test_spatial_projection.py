"""共享墙反向投影以及不兼容结构不猜测。"""

import pytest
from app.schemas.spatial import SpatialDocument
from app.services.spatial_projection import project_room


def two_rooms():
    rooms = [
        {
            "id": "a",
            "name": "客厅",
            "height": 3,
            "polygon": [
                {"x": 0, "z": 0},
                {"x": 4, "z": 0},
                {"x": 4, "z": 3},
                {"x": 0, "z": 3},
            ],
        },
        {
            "id": "b",
            "name": "卧室",
            "height": 3,
            "polygon": [
                {"x": 4, "z": 0},
                {"x": 7, "z": 0},
                {"x": 7, "z": 3},
                {"x": 4, "z": 3},
            ],
        },
    ]
    walls = []
    for room in rooms:
        for i, start in enumerate(room["polygon"]):
            end = room["polygon"][(i + 1) % 4]
            shared = next(
                (w for w in walls if w["start"] == end and w["end"] == start), None
            )
            if shared:
                shared["room_ids"].append(room["id"])
            else:
                walls.append(
                    {
                        "id": f"{room['id']}{i}",
                        "start": start,
                        "end": end,
                        "room_ids": [room["id"]],
                        "height": 3,
                        "thickness": 0.12,
                    }
                )
    return {
        "schema_version": "spatial/1.0",
        "unit": "m",
        "scale_status": "confirmed",
        "rooms": rooms,
        "walls": walls,
        "openings": [
            {
                "id": "door",
                "wall_id": "a1",
                "type": "door",
                "offset": 0.4,
                "width": 0.8,
                "height": 2.1,
                "sill_height": 0,
            }
        ],
    }


def test_shared_wall_opening_reverses_offset_without_moving():
    document = SpatialDocument.model_validate(two_rooms())
    first = project_room(document, "a")
    second = project_room(document, "b")
    assert first.openings[0].offset == pytest.approx(0.4)
    assert second.openings[0].offset == pytest.approx(1.8)
    assert second.openings[0].wall_index == 3
    assert second.room.floor_polygon[0].x == 4


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(walls=d["walls"][1:]),
        lambda d: d["walls"][0].update(thickness=0.2),
        lambda d: d["walls"][0].update(height=2.5),
    ],
)
def test_incomplete_or_incompatible_structure_is_rejected(change):
    payload = two_rooms()
    change(payload)
    with pytest.raises(ValueError):
        project_room(SpatialDocument.model_validate(payload), "a")
