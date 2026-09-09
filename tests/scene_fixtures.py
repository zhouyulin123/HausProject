from app.db.models import DesignScene, DesignSceneVersion


def attach_scene_versions(
    db,
    revision,
    *,
    room_id: str = "living",
    subject_id: str = "sofa-main",
    x: float = 0,
) -> None:
    for index, plan in enumerate(revision.plans):
        scene = DesignScene(plan_version_id=plan.id, current_version=1)
        db.add(scene)
        db.flush()
        suggestions = (plan.plan_json or {}).get("furnitureSuggestions") or []
        suggestion = suggestions[0] if suggestions else {}
        sku = suggestion.get("sku") or suggestion.get("id") or "SOFA-001"
        instance_id = subject_id if len(revision.plans) == 1 else f"{subject_id}-{index + 1}"
        db.add(
            DesignSceneVersion(
                scene_id=scene.id,
                version=1,
                scene_json={
                    "schemaVersion": "1.0",
                    "unit": "m",
                    "coordinateSystem": "right-handed-y-up",
                    "room": {
                        "id": room_id,
                        "name": "客厅",
                        "floorPolygon": [
                            {"x": -3, "z": -3},
                            {"x": 3, "z": -3},
                            {"x": 3, "z": 3},
                            {"x": -3, "z": 3},
                        ],
                        "ceilingHeight": 2.8,
                        "wallThickness": 0.12,
                    },
                    "openings": [],
                    "items": [
                        {
                            "instanceId": instance_id,
                            "sku": sku,
                            "category": "沙发",
                            "transform": {
                                "position": {"x": x, "y": 0.45, "z": 0},
                                "rotation": {"x": 0, "y": 0, "z": 0},
                                "scale": {"x": 1, "y": 1, "z": 1},
                            },
                            "dimensions": {"x": 2, "y": 0.9, "z": 1},
                        }
                    ],
                },
                validation_json={"valid": True, "errors": [], "warnings": []},
                source="auto_layout",
            )
        )
    db.flush()
