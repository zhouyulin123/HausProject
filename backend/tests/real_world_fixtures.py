from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def write_v2_manifest(
    root: Path,
    *,
    filename: str,
    dataset_version: str,
    cases: list[dict[str, Any]],
) -> Path:
    annotation_dir = root / "annotations"
    annotation_dir.mkdir(exist_ok=True)
    enriched_cases: list[dict[str, Any]] = []
    for raw_case in cases:
        case = dict(raw_case)
        if case.get("annotation_status") == "ready":
            asset_path = root / str(case["asset_path"])
            asset_digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
            annotation = {
                "schema_version": "1.0",
                "annotation_type": "real_world_case_annotation",
                "case_id": case["id"],
                "label_version": case["label_version"],
                "source_asset_sha256": asset_digest,
                "requirements": [{"field": "space_type", "value": "客厅"}],
                "space_facts": [
                    {
                        "fact_path": "rooms.living.width_m",
                        "value": 4.2,
                        "confidence": 1.0,
                        "requires_confirmation": False,
                    }
                ],
                "allowed_skus": ["SOFA-001"],
                "budget": {"currency": "CNY", "min": 10000, "max": 20000},
                "layout_hard_constraints": [
                    {
                        "constraint_id": "inside-room",
                        "type": "inside_room",
                        "room_id": "living",
                        "subject_id": "sofa-main",
                        "related_id": None,
                        "operator": "eq",
                        "value": True,
                        "unit": "boolean",
                    }
                ],
                "style_tags": ["现代"],
            }
            annotation_path = annotation_dir / f"{case['id']}.json"
            annotation_path.write_text(
                json.dumps(annotation, ensure_ascii=False),
                encoding="utf-8",
            )
            case["annotation_path"] = annotation_path.relative_to(root).as_posix()
            case["annotation_sha256"] = hashlib.sha256(
                annotation_path.read_bytes()
            ).hexdigest()
        enriched_cases.append(case)

    manifest = root / filename
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "dataset_version": dataset_version,
                "cases": enriched_cases,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest
