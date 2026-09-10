from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def frozen_catalog_suggestion(
    sku: str = "SOFA-001",
    *,
    unit_price: int = 10000,
    quantity: int = 1,
) -> dict[str, Any]:
    data_version = "catalog-data-v1"
    record_version = 1
    return {
        "id": sku,
        "sku": sku,
        "quantity": quantity,
        "unitPrice": unit_price,
        "dataVersion": data_version,
        "recordVersion": record_version,
        "catalogEligibility": {
            "schemaVersion": "1.1",
            "checkedAt": "2026-09-01T00:00:00+00:00",
            "sku": sku,
            "quantity": quantity,
            "unitPrice": unit_price,
            "dataVersion": data_version,
            "recordVersion": record_version,
            "policy": {
                "region": None,
                "allowDraft": False,
                "maxUnitPrice": 20000,
                "maxDimensionsMm": {},
            },
            "facts": {
                "isActive": True,
                "dataOrigin": "merchant_verified",
                "sourceName": "受控评测供应商目录",
                "sourceUrl": None,
                "sourceProductId": sku,
                "sourceRetrievedAt": "2026-08-31T22:00:00+00:00",
                "priceObservedAt": "2026-08-31T23:00:00+00:00",
                "verificationStatus": "verified",
                "verifiedAt": "2026-08-31T23:30:00+00:00",
                "verifiedBy": "eval-fixture:catalog-reviewer",
                "dataVersion": data_version,
                "availabilityStatus": "in_stock",
                "stockQuantity": max(10, quantity),
                "leadTimeDaysMin": None,
                "leadTimeDaysMax": None,
                "priceValidFrom": "2026-01-01T00:00:00+00:00",
                "priceValidTo": "2027-01-01T00:00:00+00:00",
                "regionCodes": ["*"],
                "dimensionsMm": {"width": 1000, "depth": 800, "height": 900},
            },
            "eligible": True,
            "reasonCodes": [],
        },
    }


def frozen_catalog_quote_line(suggestion: dict[str, Any]) -> dict[str, Any]:
    return {
        field: suggestion[field]
        for field in ("sku", "quantity", "unitPrice", "dataVersion", "recordVersion")
    }


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
        case.setdefault(
            "task_input",
            {
                "raw_user_input": "设计一个已脱敏的测试客厅",
                "confirmed_requirement": {"space_type": "客厅"},
                "space_type": "客厅",
                "style": None,
                "budget_min": None,
                "budget_max": None,
                "image_context": ["已脱敏空间事实"],
            },
        )
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
