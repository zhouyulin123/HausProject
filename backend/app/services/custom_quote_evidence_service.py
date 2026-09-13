"""定制报价冻结证据的生成与确定性复算。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from typing import Any, Mapping

from pydantic import ValidationError

from app.db.models import CustomQuoteRule
from app.schemas.custom_quote_evidence import CustomRuleEvidence


class CustomRuleEvidenceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class VerifiedCustomRuleEvidence:
    rule_id: int
    data_version: str
    record_version: int
    project: str
    grade: str
    pricing_unit: str
    requested_quantity: float
    unit_price: int
    subtotal: int


def build_evidence(
    rule: CustomQuoteRule,
    calculation: Mapping[str, Any],
    *,
    checked_at: datetime,
    region: str | None,
) -> dict[str, Any]:
    payload = {
        "schemaVersion": "1.0",
        "checkedAt": checked_at.isoformat(),
        "region": region,
        "isActive": bool(rule.is_active),
        "ruleId": rule.id,
        "dataVersion": rule.data_version,
        "recordVersion": rule.record_version,
        "project": rule.project_name,
        "grade": rule.material_grade,
        "pricingUnit": rule.pricing_unit,
        "unitPrice": rule.unit_price,
        "ruleRegionCodes": sorted(set(rule.region_codes or [])),
        "requestedQuantity": float(calculation["requestedQuantity"]),
        "billableQuantity": float(calculation["billableQuantity"]),
        "wasteRateBps": int(calculation["wasteRateBps"]),
        "minimumQuantity": float(calculation["minimumQuantity"]),
        "baseSubtotal": int(calculation["baseSubtotal"]),
        "installationFee": int(calculation["installationFee"]),
        "shippingFee": int(calculation["shippingFee"]),
        "taxRateBps": int(calculation["taxRateBps"]),
        "taxAmount": int(calculation["taxAmount"]),
        "subtotal": int(calculation["subtotal"]),
    }
    return CustomRuleEvidence.model_validate(payload).model_dump(
        by_alias=True,
        mode="json",
    )


def verify_evidence(
    raw: Any,
    *,
    expected_region: str | None,
    expected_priced_at: datetime | str | None = None,
) -> VerifiedCustomRuleEvidence:
    if not isinstance(raw, dict):
        raise CustomRuleEvidenceError("custom_rule_evidence_missing")
    try:
        evidence = CustomRuleEvidence.model_validate(raw)
    except ValidationError as exc:
        raise CustomRuleEvidenceError("custom_rule_evidence_invalid") from exc
    numeric = (
        evidence.requested_quantity,
        evidence.billable_quantity,
        evidence.minimum_quantity,
    )
    if not all(isfinite(value) for value in numeric):
        raise CustomRuleEvidenceError("custom_rule_evidence_invalid")
    if not evidence.is_active:
        raise CustomRuleEvidenceError("custom_rule_inactive")
    if evidence.region != expected_region:
        raise CustomRuleEvidenceError("custom_rule_policy_mismatch")
    if expected_priced_at is not None:
        if isinstance(expected_priced_at, str):
            try:
                priced_at = datetime.fromisoformat(
                    expected_priced_at.replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise CustomRuleEvidenceError("custom_rule_policy_mismatch") from exc
        else:
            priced_at = expected_priced_at
        if priced_at.tzinfo is None or evidence.checked_at != priced_at:
            raise CustomRuleEvidenceError("custom_rule_policy_mismatch")
    if evidence.region is not None and (
        "*" not in evidence.rule_region_codes
        and evidence.region not in evidence.rule_region_codes
    ):
        raise CustomRuleEvidenceError("custom_rule_policy_mismatch")

    requested = Decimal(str(evidence.requested_quantity))
    waste_multiplier = Decimal("1") + (
        Decimal(evidence.waste_rate_bps) / Decimal("10000")
    )
    billable = max(
        requested * waste_multiplier,
        Decimal(str(evidence.minimum_quantity)),
    ).quantize(Decimal("0.001"))
    base_subtotal = (Decimal(evidence.unit_price) * billable).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    pre_tax = base_subtotal + evidence.installation_fee + evidence.shipping_fee
    tax_amount = (pre_tax * Decimal(evidence.tax_rate_bps) / Decimal("10000")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    subtotal = int(pre_tax + tax_amount)
    if (
        evidence.billable_quantity != float(billable)
        or evidence.base_subtotal != int(base_subtotal)
        or evidence.tax_amount != int(tax_amount)
        or evidence.subtotal != subtotal
    ):
        raise CustomRuleEvidenceError("custom_rule_evidence_inconsistent")
    return VerifiedCustomRuleEvidence(
        rule_id=evidence.rule_id,
        data_version=evidence.data_version,
        record_version=evidence.record_version,
        project=evidence.project,
        grade=evidence.grade,
        pricing_unit=evidence.pricing_unit,
        requested_quantity=evidence.requested_quantity,
        unit_price=evidence.unit_price,
        subtotal=subtotal,
    )
