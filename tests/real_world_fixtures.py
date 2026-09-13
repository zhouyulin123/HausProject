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
    data_version: str = "catalog-data-v1",
    record_version: int = 1,
) -> dict[str, Any]:
    return {
        "id": sku,
        "sku": sku,
        "quantity": quantity,
        "unitPrice": unit_price,
        "dataVersion": data_version,
        "recordVersion": record_version,
        "dataOrigin": "merchant_verified",
        "sourceName": "受控评测供应商目录",
        "sourceUrl": None,
        "verifiedAt": "2026-08-31T23:30:00+00:00",
        "dataStatus": "verified",
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
                "maxUnitPrice": max(20000, unit_price),
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
    line = {
        field: suggestion[field]
        for field in ("sku", "quantity", "unitPrice", "dataVersion", "recordVersion")
    }
    line["subtotal"] = suggestion["unitPrice"] * suggestion["quantity"]
    return line


def frozen_custom_quote() -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = {
        "schemaVersion": "1.0",
        "checkedAt": "2026-09-02T00:00:00+00:00",
        "region": None,
        "isActive": True,
        "ruleId": 7,
        "dataVersion": "custom-price-v4",
        "recordVersion": 4,
        "project": "定制衣柜",
        "grade": "E0 实木多层板",
        "pricingUnit": "㎡",
        "unitPrice": 1280,
        "ruleRegionCodes": ["*"],
        "requestedQuantity": 2.0,
        "billableQuantity": 3.0,
        "wasteRateBps": 500,
        "minimumQuantity": 3.0,
        "baseSubtotal": 3840,
        "installationFee": 300,
        "shippingFee": 200,
        "taxRateBps": 600,
        "taxAmount": 260,
        "subtotal": 4600,
    }
    common = {
        "ruleId": 7,
        "quantity": 2.0,
        "requestedQuantity": 2.0,
        "billableQuantity": 3.0,
        "wasteRateBps": 500,
        "minimumQuantity": 3.0,
        "baseSubtotal": 3840,
        "installationFee": 300,
        "shippingFee": 200,
        "taxRateBps": 600,
        "taxAmount": 260,
        "unitPrice": 1280,
        "subtotal": 4600,
        "dataVersion": "custom-price-v4",
        "recordVersion": 4,
        "customRuleEvidence": evidence,
    }
    custom_item = {
        **common,
        "project": "定制衣柜",
        "grade": "E0 实木多层板",
        "unit": "㎡",
        "note": "",
    }
    return custom_item, dict(common)


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
