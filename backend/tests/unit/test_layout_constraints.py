import pytest

from app.schemas.scenes import SceneDocument
from evals.annotations import LayoutHardConstraint
from evals.layout_constraints import evaluate_layout_constraint


def _scene() -> SceneDocument:
    return SceneDocument.model_validate(
        {
            "schemaVersion": "1.0",
            "unit": "m",
            "coordinateSystem": "right-handed-y-up",
            "room": {
                "id": "living",
                "name": "客厅",
                "floorPolygon": [
                    {"x": -3, "z": -3},
                    {"x": 3, "z": -3},
                    {"x": 3, "z": 3},
                    {"x": -3, "z": 3},
                ],
                "ceilingHeight": 2.8,
            },
            "openings": [],
            "items": [],
        }
    )


@pytest.mark.parametrize("constraint_type", ["walkway_width", "maximum_occupancy"])
def test_legacy_unrepresented_constraints_are_readable_but_never_evidence(
    constraint_type,
):
    constraint = LayoutHardConstraint.model_validate(
        {
            "constraint_id": "legacy-constraint",
            "type": constraint_type,
            "room_id": "living",
            "subject_id": "legacy-subject",
            "related_id": None,
            "operator": "gte",
            "value": 800,
            "unit": "mm",
        }
    )

    evidence = evaluate_layout_constraint(_scene(), constraint)

    assert evidence.status == "no_evidence"
    assert evidence.reason_code == "constraint_not_represented"
