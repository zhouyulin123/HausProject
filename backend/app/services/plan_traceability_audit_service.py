"""对不可变方案快照执行可复现的商品与报价来源抽检。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import DesignPlanVersion, DesignRevision
from app.services.design_version_service import recalculate_quote_snapshot


@dataclass(frozen=True)
class PlanTraceabilityResult:
    plan_version_id: int
    task_id: int
    revision_version: int
    plan_key: str
    passed: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PlanTraceabilityAuditReport:
    seed: str
    requested_sample_size: int
    available_plan_count: int
    sampled_plan_count: int
    sample_shortfall: int
    passed: bool
    results: tuple[PlanTraceabilityResult, ...]


def _nonlegacy_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value.strip().lower() != "legacy"
    )


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _money(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _quantity(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
    )


def _line_identity(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("sku"),
        item.get("quantity"),
        item.get("unitPrice"),
        item.get("subtotal"),
        item.get("dataVersion"),
        item.get("recordVersion"),
    )


def _audit_plan(plan: DesignPlanVersion) -> PlanTraceabilityResult:
    reasons: list[str] = []
    snapshot = plan.quote_snapshot
    if snapshot is None:
        return PlanTraceabilityResult(
            plan_version_id=plan.id,
            task_id=plan.revision.task_id,
            revision_version=plan.revision.version,
            plan_key=plan.plan_key,
            passed=False,
            reason_codes=("quote_snapshot_missing",),
        )

    for field_name, value in (
        ("catalog_version", snapshot.catalog_version),
        ("price_version", snapshot.price_version),
        ("rule_version", snapshot.rule_version),
    ):
        if not _nonlegacy_text(value):
            reasons.append(f"{field_name}_missing")

    quote = snapshot.quote_json
    if not isinstance(quote, dict):
        reasons.append("quote_payload_invalid")
        quote = {}
    plan_payload = plan.plan_json if isinstance(plan.plan_json, dict) else {}
    if plan_payload.get("shopQuote") != quote:
        reasons.append("quote_payload_mismatch")

    line_items = quote.get("lineItems")
    if not isinstance(line_items, list):
        reasons.append("quote_line_items_invalid")
        line_items = []
    valid_lines: list[dict[str, Any]] = []
    line_subtotal_mismatch = False
    for raw_line in line_items:
        if not isinstance(raw_line, dict):
            reasons.append("quote_line_invalid")
            continue
        valid_lines.append(raw_line)
        if not _nonlegacy_text(raw_line.get("sku")):
            reasons.append("quote_line_sku_missing")
        if not _quantity(raw_line.get("quantity")):
            reasons.append("quote_line_quantity_invalid")
        if not _money(raw_line.get("unitPrice")):
            reasons.append("quote_line_price_invalid")
        if not _money(raw_line.get("subtotal")):
            reasons.append("quote_line_subtotal_invalid")
        elif _quantity(raw_line.get("quantity")) and _money(
            raw_line.get("unitPrice")
        ):
            expected = round(raw_line["unitPrice"] * raw_line["quantity"])
            if raw_line["subtotal"] != expected:
                line_subtotal_mismatch = True
                reasons.append("quote_line_subtotal_mismatch")
        if not _nonlegacy_text(raw_line.get("dataVersion")):
            reasons.append("quote_line_data_version_missing")
        if not _positive_int(raw_line.get("recordVersion")):
            reasons.append("quote_line_record_version_invalid")

    expected_versions = [
        {
            "sku": item.get("sku"),
            "dataVersion": item.get("dataVersion"),
            "recordVersion": item.get("recordVersion"),
        }
        for item in valid_lines
        if item.get("sku")
    ]
    if snapshot.sku_versions_json != expected_versions:
        reasons.append("sku_version_snapshot_mismatch")

    custom_lines = quote.get("customLineItems")
    if not isinstance(custom_lines, list):
        reasons.append("custom_quote_lines_invalid")
        custom_lines = []
    for raw_line in custom_lines:
        if not isinstance(raw_line, dict):
            reasons.append("custom_quote_line_invalid")
            continue
        if not _positive_int(raw_line.get("ruleId")):
            reasons.append("custom_rule_id_missing")
        if not _nonlegacy_text(raw_line.get("dataVersion")):
            reasons.append("custom_rule_data_version_missing")
        if not _positive_int(raw_line.get("recordVersion")):
            reasons.append("custom_rule_record_version_invalid")

    products = plan_payload.get("furnitureSuggestions")
    if not isinstance(products, list):
        reasons.append("product_snapshot_invalid")
        products = []
    product_lines: list[dict[str, Any]] = []
    for raw_product in products:
        if not isinstance(raw_product, dict):
            reasons.append("product_snapshot_item_invalid")
            continue
        product_lines.append(raw_product)
        if raw_product.get("dataStatus") != "verified":
            reasons.append("product_not_verified")
        if not _nonlegacy_text(raw_product.get("sourceName")):
            reasons.append("product_source_missing")
        if not _nonlegacy_text(raw_product.get("verifiedAt")):
            reasons.append("product_verification_time_missing")
        if not _nonlegacy_text(raw_product.get("dataVersion")):
            reasons.append("product_data_version_missing")
        if not _positive_int(raw_product.get("recordVersion")):
            reasons.append("product_record_version_invalid")

    if sorted(_line_identity(item) for item in valid_lines) != sorted(
        _line_identity(item) for item in product_lines
    ):
        reasons.append("product_quote_line_mismatch")

    recalculated = recalculate_quote_snapshot(snapshot)
    if line_subtotal_mismatch or not recalculated["consistent"]:
        reasons.append("quote_snapshot_inconsistent")

    normalized_reasons = tuple(dict.fromkeys(reasons))
    return PlanTraceabilityResult(
        plan_version_id=plan.id,
        task_id=plan.revision.task_id,
        revision_version=plan.revision.version,
        plan_key=plan.plan_key,
        passed=not normalized_reasons,
        reason_codes=normalized_reasons,
    )


def _sample_key(seed: str, plan_id: int) -> str:
    payload = f"{seed}:{plan_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def audit_plan_traceability(
    db: Session,
    *,
    sample_size: int = 20,
    seed: str,
) -> PlanTraceabilityAuditReport:
    """抽检所有完成方案，缺快照的记录不能被查询条件提前隐藏。"""
    if not 1 <= sample_size <= 100:
        raise ValueError("sample_size 必须在 1 到 100 之间")
    normalized_seed = seed.strip()
    if not normalized_seed:
        raise ValueError("seed 不能为空")

    candidates = list(
        db.scalars(
            select(DesignPlanVersion)
            .join(DesignRevision)
            .options(
                selectinload(DesignPlanVersion.quote_snapshot),
                selectinload(DesignPlanVersion.revision),
            )
            .where(DesignRevision.status == "completed")
            .order_by(DesignPlanVersion.id)
            .execution_options(populate_existing=True)
        ).unique()
    )
    sampled = sorted(
        candidates,
        key=lambda plan: (_sample_key(normalized_seed, plan.id), plan.id),
    )[:sample_size]
    results = tuple(_audit_plan(plan) for plan in sampled)
    shortfall = max(0, sample_size - len(sampled))
    return PlanTraceabilityAuditReport(
        seed=normalized_seed,
        requested_sample_size=sample_size,
        available_plan_count=len(candidates),
        sampled_plan_count=len(sampled),
        sample_shortfall=shortfall,
        passed=shortfall == 0 and all(result.passed for result in results),
        results=results,
    )
