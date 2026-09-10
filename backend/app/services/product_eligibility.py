"""线上目录与冻结证据共用的纯商品资格规则。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


VERIFICATION_STATUSES = frozenset({"draft", "verified", "rejected", "expired"})
AVAILABILITY_STATUSES = frozenset(
    {"in_stock", "low_stock", "out_of_stock", "preorder", "unknown"}
)
PRODUCT_ELIGIBILITY_REASON_CODES = (
    "inactive",
    "public_reference",
    "provenance_unverified",
    "source_name_missing",
    "source_reference_missing",
    "source_retrieved_at_missing",
    "source_retrieved_at_future",
    "price_observed_at_missing",
    "price_observed_at_future",
    "verification_required",
    "verification_rejected",
    "verification_expired",
    "verification_invalid",
    "verified_at_missing",
    "verified_at_future",
    "verified_by_missing",
    "data_version_unverified",
    "out_of_stock",
    "availability_unknown",
    "lead_time_unknown",
    "availability_invalid",
    "insufficient_stock",
    "price_validity_unknown",
    "price_not_started",
    "price_expired",
    "region_unknown",
    "region_required",
    "region_unavailable",
    "dimensions_missing",
    "dimensions_exceeded",
    "budget_exceeded",
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
    source_name: str | None
    source_url: str | None
    source_product_id: str | None
    source_retrieved_at: datetime | None
    price_observed_at: datetime | None
    verification_status: str | None
    verified_at: datetime | None
    verified_by: str | None
    data_version: str | None
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
    elif facts.data_origin not in {"merchant", "merchant_verified"} and not (
        policy.allow_draft and facts.data_origin == "merchant_draft"
    ):
        reasons.append("provenance_unverified")

    if not (facts.source_name or "").strip():
        reasons.append("source_name_missing")
    if not (facts.source_url or "").strip() and not (
        facts.source_product_id or ""
    ).strip():
        reasons.append("source_reference_missing")
    if facts.source_retrieved_at is None:
        reasons.append("source_retrieved_at_missing")
    elif facts.source_retrieved_at > policy.checked_at:
        reasons.append("source_retrieved_at_future")
    if facts.price_observed_at is None:
        reasons.append("price_observed_at_missing")
    elif facts.price_observed_at > policy.checked_at:
        reasons.append("price_observed_at_future")

    verification = facts.verification_status or "draft"
    if verification == "draft" and not policy.allow_draft:
        reasons.append("verification_required")
    elif verification == "rejected":
        reasons.append("verification_rejected")
    elif verification == "expired":
        reasons.append("verification_expired")
    elif verification not in VERIFICATION_STATUSES:
        reasons.append("verification_invalid")
    data_version = (facts.data_version or "").strip()
    is_allowed_draft = verification == "draft" and policy.allow_draft
    if is_allowed_draft:
        if not data_version:
            reasons.append("data_version_unverified")
    else:
        if facts.verified_at is None:
            reasons.append("verified_at_missing")
        elif facts.verified_at > policy.checked_at:
            reasons.append("verified_at_future")
        if not (facts.verified_by or "").strip():
            reasons.append("verified_by_missing")
        if not data_version or data_version.casefold().startswith("draft"):
            reasons.append("data_version_unverified")

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

    if not facts.region_codes:
        reasons.append("region_unknown")
    elif "*" not in facts.region_codes and policy.region is None:
        reasons.append("region_required")
    elif (
        policy.region
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
