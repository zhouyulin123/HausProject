"""冻结商品资格证据的确定性复算。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.schemas.product_eligibility import FrozenProductEligibilitySnapshot
from app.services.product_eligibility import (
    ProductDimensions,
    ProductEligibilityPolicy,
    ProductEligibilityFacts,
    evaluate_product_eligibility,
)


@dataclass(frozen=True, slots=True)
class FrozenEligibilityVerification:
    price_valid_to: datetime


@dataclass(frozen=True, slots=True)
class FrozenEligibilityPolicyExpectation:
    region: str | None
    max_unit_price: int | None
    max_dimensions_mm: dict[str, int] | None
    allow_development: bool = False


class FrozenEligibilityError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _dimensions(value) -> ProductDimensions:
    return ProductDimensions(
        width=value.width,
        depth=value.depth,
        height=value.height,
    )


def verify_suggestion(
    suggestion: dict[str, Any],
    *,
    expected_policy: FrozenEligibilityPolicyExpectation | None = None,
    allow_development: bool = False,
) -> FrozenEligibilityVerification:
    raw = suggestion.get("catalogEligibility")
    if not isinstance(raw, dict):
        raise FrozenEligibilityError("product_eligibility_missing")
    try:
        snapshot = FrozenProductEligibilitySnapshot.model_validate(raw)
    except ValidationError as exc:
        raise FrozenEligibilityError("product_eligibility_invalid") from exc

    identity = {
        "sku": snapshot.sku,
        "quantity": snapshot.quantity,
        "unitPrice": snapshot.unit_price,
        "dataVersion": snapshot.data_version,
        "recordVersion": snapshot.record_version,
    }
    if any(suggestion.get(field) != value for field, value in identity.items()):
        raise FrozenEligibilityError("product_eligibility_mismatch")
    if snapshot.facts.data_version != snapshot.data_version:
        raise FrozenEligibilityError("product_eligibility_mismatch")

    facts = snapshot.facts
    policy = snapshot.policy
    if (policy.allow_development or facts.data_origin == "development_fixture") and not allow_development:
        raise FrozenEligibilityError("development_product_not_allowed")
    expected_outer_facts = {
        "dataOrigin": facts.data_origin,
        "sourceName": facts.source_name,
        "sourceUrl": facts.source_url,
        "verifiedAt": (
            facts.verified_at.isoformat() if facts.verified_at is not None else None
        ),
        "dataStatus": (
            "verified" if facts.verification_status == "verified" else "draft"
        ),
    }
    if any(
        suggestion.get(field) != value for field, value in expected_outer_facts.items()
    ):
        raise FrozenEligibilityError("product_eligibility_facts_mismatch")
    if expected_policy is not None:
        policy_dimensions = {
            key: value
            for key, value in {
                "width": policy.max_dimensions_mm.width,
                "depth": policy.max_dimensions_mm.depth,
                "height": policy.max_dimensions_mm.height,
            }.items()
            if value is not None
        } or None
        if (
            policy.allow_draft
            or (policy.allow_development and not expected_policy.allow_development)
            or policy.region != expected_policy.region
            or policy_dimensions != expected_policy.max_dimensions_mm
            or (
                expected_policy.max_unit_price is not None
                and (
                    policy.max_unit_price is None
                    or policy.max_unit_price > expected_policy.max_unit_price
                )
            )
        ):
            raise FrozenEligibilityError("product_eligibility_policy_mismatch")
    decision = evaluate_product_eligibility(
        ProductEligibilityFacts(
            is_active=facts.is_active,
            data_origin=facts.data_origin,
            source_name=facts.source_name,
            source_url=facts.source_url,
            source_product_id=facts.source_product_id,
            source_retrieved_at=facts.source_retrieved_at,
            price_observed_at=facts.price_observed_at,
            verification_status=facts.verification_status,
            verified_at=facts.verified_at,
            verified_by=facts.verified_by,
            data_version=facts.data_version,
            availability_status=facts.availability_status,
            stock_quantity=facts.stock_quantity,
            lead_time_days_min=facts.lead_time_days_min,
            lead_time_days_max=facts.lead_time_days_max,
            price_valid_from=facts.price_valid_from,
            price_valid_to=facts.price_valid_to,
            region_codes=tuple(facts.region_codes),
            dimensions_mm=_dimensions(facts.dimensions_mm),
            unit_price=snapshot.unit_price,
        ),
        ProductEligibilityPolicy(
            checked_at=snapshot.checked_at,
            region=policy.region,
            allow_draft=policy.allow_draft,
            max_unit_price=policy.max_unit_price,
            max_dimensions_mm=(
                _dimensions(policy.max_dimensions_mm)
                if any(
                    value is not None
                    for value in (
                        policy.max_dimensions_mm.width,
                        policy.max_dimensions_mm.depth,
                        policy.max_dimensions_mm.height,
                    )
                )
                else None
            ),
            required_quantity=snapshot.quantity,
            allow_development=policy.allow_development,
        ),
    )
    if not decision.eligible:
        raise FrozenEligibilityError(decision.reason_codes[0])
    if snapshot.eligible != decision.eligible or snapshot.reason_codes != list(
        decision.reason_codes
    ):
        raise FrozenEligibilityError("product_eligibility_inconsistent")
    if facts.price_valid_to is None:
        raise FrozenEligibilityError("price_validity_unknown")
    return FrozenEligibilityVerification(price_valid_to=facts.price_valid_to)
