"""线上目录与冻结证据共用的纯商品资格规则。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


VERIFICATION_STATUSES = frozenset({"draft", "verified", "rejected", "expired"})
AVAILABILITY_STATUSES = frozenset(
    {"in_stock", "low_stock", "out_of_stock", "preorder", "unknown"}
)


@dataclass(frozen=True)
class ProductDimensions:
    width: int | None
    depth: int | None
    height: int | None


@dataclass(frozen=True)
class ProductEligibilityFacts:
    is_active: bool
    data_origin: str | None
    verification_status: str | None
    availability_status: str | None
    stock_quantity: int | None
    lead_time_days_min: int | None
    lead_time_days_max: int | None
    price_valid_from: datetime | None
    price_valid_to: datetime | None
    region_codes: tuple[str, ...]
    dimensions_mm: ProductDimensions
    unit_price: int


@dataclass(frozen=True)
class ProductEligibilityPolicy:
    checked_at: datetime
    region: str | None
    allow_draft: bool
    max_unit_price: int | None
    max_dimensions_mm: ProductDimensions | None
    required_quantity: int | None


@dataclass(frozen=True)
class ProductEligibility:
    eligible: bool
    reason_codes: tuple[str, ...]

    def __bool__(self) -> bool:
        return self.eligible


def _positive_integer(value: int | None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def evaluate_product_eligibility(
    facts: ProductEligibilityFacts,
    policy: ProductEligibilityPolicy,
) -> ProductEligibility:
    """仅根据显式事实与策略计算资格，不读取数据库或环境状态。"""
    reasons: list[str] = []
    if not facts.is_active:
        reasons.append("inactive")
    if facts.data_origin == "public_reference":
        reasons.append("public_reference")

    verification = facts.verification_status or "draft"
    if verification == "draft" and not policy.allow_draft:
        reasons.append("verification_required")
    elif verification == "rejected":
        reasons.append("verification_rejected")
    elif verification == "expired":
        reasons.append("verification_expired")
    elif verification not in VERIFICATION_STATUSES:
        reasons.append("verification_invalid")

    availability = facts.availability_status or "unknown"
    if availability == "out_of_stock":
        reasons.append("out_of_stock")
    elif availability == "unknown":
        reasons.append("availability_unknown")
    elif availability in {"in_stock", "low_stock"} and (
        facts.stock_quantity is None or facts.stock_quantity <= 0
    ):
        reasons.append("out_of_stock")
    elif availability == "preorder" and (
        not _positive_integer(facts.lead_time_days_min)
        or not _positive_integer(facts.lead_time_days_max)
        or facts.lead_time_days_min > facts.lead_time_days_max
    ):
        reasons.append("lead_time_unknown")
    elif availability not in AVAILABILITY_STATUSES:
        reasons.append("availability_invalid")
    if policy.required_quantity is not None and (
        facts.stock_quantity is None
        or facts.stock_quantity < policy.required_quantity
    ):
        reasons.append("insufficient_stock")

    if facts.price_valid_from is None or facts.price_valid_to is None:
        reasons.append("price_validity_unknown")
    else:
        if policy.checked_at < facts.price_valid_from:
            reasons.append("price_not_started")
        if policy.checked_at > facts.price_valid_to:
            reasons.append("price_expired")

    if facts.region_codes and "*" not in facts.region_codes and policy.region is None:
        reasons.append("region_required")
    elif (
        policy.region
        and facts.region_codes
        and policy.region not in facts.region_codes
        and "*" not in facts.region_codes
    ):
        reasons.append("region_unavailable")

    dimensions = facts.dimensions_mm
    if any(
        not _positive_integer(value)
        for value in (dimensions.width, dimensions.depth, dimensions.height)
    ):
        reasons.append("dimensions_missing")
    elif policy.max_dimensions_mm is not None and any(
        limit is not None and value > limit
        for value, limit in (
            (dimensions.width, policy.max_dimensions_mm.width),
            (dimensions.depth, policy.max_dimensions_mm.depth),
            (dimensions.height, policy.max_dimensions_mm.height),
        )
    ):
        reasons.append("dimensions_exceeded")

    if policy.max_unit_price is not None and facts.unit_price > policy.max_unit_price:
        reasons.append("budget_exceeded")
    reason_codes = tuple(dict.fromkeys(reasons))
    return ProductEligibility(not reason_codes, reason_codes)
