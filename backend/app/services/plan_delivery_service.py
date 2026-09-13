"""方案正式交付门禁：统一保护 PDF 与公开分享出口。"""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    CustomQuoteRule,
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    Product,
    QuoteSnapshot,
)
from app.services import (
    aggregate_lock_service,
    catalog_service,
    frozen_product_eligibility_service,
    generation_source_service,
    plan_traceability_audit_service,
)


@dataclass(frozen=True)
class PlanDeliveryFacts:
    quote_valid_until: datetime | None
    plan_snapshot: dict[str, Any]
    snapshot_digest: str
    delivery_mode: str = "commercial"


class PlanDeliveryBlocked(ValueError):
    code = "plan_delivery_blocked"
    message = "方案未通过正式交付门禁"

    def __init__(self, reason_codes: tuple[str, ...]) -> None:
        self.reason_codes = tuple(dict.fromkeys(reason_codes))
        super().__init__(self.message)

    def detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "reason_codes": list(self.reason_codes),
        }


def _for_update(db: Session, statement):
    if db.get_bind().dialect.name != "sqlite":
        return statement.with_for_update()
    return statement


def _referenced_catalog_keys(
    plan: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[int, ...]]:
    raw_products = plan.get("furnitureSuggestions")
    skus = tuple(
        sorted(
            {
                sku.strip().upper()
                for item in raw_products
                if isinstance(item, dict)
                and isinstance((sku := item.get("sku")), str)
                and sku.strip()
            }
        )
    ) if isinstance(raw_products, list) else ()

    raw_custom_lines = plan.get("customItems")
    rule_ids = tuple(
        sorted(
            {
                rule_id
                for item in raw_custom_lines
                if isinstance(item, dict)
                and isinstance((rule_id := item.get("ruleId")), int)
                and not isinstance(rule_id, bool)
                and rule_id > 0
            }
        )
    ) if isinstance(raw_custom_lines, list) else ()
    return skus, rule_ids


def lock_delivery_aggregate(
    db: Session,
    *,
    plan_version_id: int,
) -> DesignPlanVersion | None:
    """按统一顺序锁定交付聚合，并返回锁内重新加载的方案。"""
    task_id = db.scalar(
        select(DesignRevision.task_id)
        .join(
            DesignPlanVersion,
            DesignPlanVersion.revision_id == DesignRevision.id,
        )
        .where(DesignPlanVersion.id == plan_version_id)
    )
    if task_id is None or aggregate_lock_service.lock_task(db, task_id) is None:
        return None

    db.scalars(
        _for_update(
            db,
            select(DesignRevision)
            .where(DesignRevision.task_id == task_id)
            .order_by(DesignRevision.id)
            .execution_options(populate_existing=True),
        )
    ).all()
    plan_version = db.scalar(
        _for_update(
            db,
            select(DesignPlanVersion)
            .join(
                DesignRevision,
                DesignRevision.id == DesignPlanVersion.revision_id,
            )
            .where(
                DesignPlanVersion.id == plan_version_id,
                DesignRevision.task_id == task_id,
            )
            .execution_options(populate_existing=True),
        )
    )
    if plan_version is None:
        return None

    db.scalar(
        _for_update(
            db,
            select(QuoteSnapshot)
            .where(QuoteSnapshot.plan_version_id == plan_version_id)
            .execution_options(populate_existing=True),
        )
    )
    scene = db.scalar(
        _for_update(
            db,
            select(DesignScene)
            .where(DesignScene.plan_version_id == plan_version_id)
            .execution_options(populate_existing=True),
        )
    )
    if scene is not None:
        db.scalar(
            _for_update(
                db,
                select(DesignSceneVersion)
                .where(
                    DesignSceneVersion.scene_id == scene.id,
                    DesignSceneVersion.version == scene.current_version,
                )
                .execution_options(populate_existing=True),
            )
        )

    plan = plan_version.plan_json if isinstance(plan_version.plan_json, dict) else {}
    skus, rule_ids = _referenced_catalog_keys(plan)
    if skus:
        db.scalars(
            _for_update(
                db,
                select(Product)
                .where(Product.sku.in_(skus))
                .order_by(Product.id)
                .execution_options(populate_existing=True),
            )
        ).all()
    if rule_ids:
        db.scalars(
            _for_update(
                db,
                select(CustomQuoteRule)
                .where(CustomQuoteRule.id.in_(rule_ids))
                .order_by(CustomQuoteRule.id)
                .execution_options(populate_existing=True),
            )
        ).all()

    db.expire(plan_version, ["revision", "quote_snapshot", "scene"])
    return plan_version


def _snapshot_payload(plan_version: DesignPlanVersion) -> dict[str, Any]:
    revision = plan_version.revision
    quote = plan_version.quote_snapshot
    return {
        "plan_version_id": plan_version.id,
        "plan_key": plan_version.plan_key,
        "plan_json": plan_version.plan_json,
        "revision": {
            "id": revision.id,
            "version": revision.version,
            "status": revision.status,
            "generator": revision.generator,
            "requirement_snapshot": revision.requirement_snapshot,
            "workflow_trace_snapshot": revision.workflow_trace_snapshot,
        },
        "quote": (
            {
                "currency": quote.currency,
                "furniture_total": quote.furniture_total,
                "custom_total": quote.custom_total,
                "grand_total": quote.grand_total,
                "quote_json": quote.quote_json,
                "catalog_version": quote.catalog_version,
                "price_version": quote.price_version,
                "rule_version": quote.rule_version,
                "sku_versions_json": quote.sku_versions_json,
            }
            if quote is not None
            else None
        ),
    }


def _snapshot_digest(plan_version: DesignPlanVersion) -> str:
    canonical = json.dumps(
        _snapshot_payload(plan_version),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{sha256(canonical).hexdigest()}"


def assert_snapshot_unchanged(
    plan_version: DesignPlanVersion,
    facts: PlanDeliveryFacts,
) -> None:
    if _snapshot_digest(plan_version) != facts.snapshot_digest:
        raise PlanDeliveryBlocked(("delivery_snapshot_changed",))


def _identity(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("sku"),
        item.get("quantity"),
        item.get("unitPrice"),
        item.get("subtotal"),
        item.get("dataVersion"),
        item.get("recordVersion"),
    )


def _quote_valid_until(
    plan_version: DesignPlanVersion,
    *,
    allow_development: bool = False,
) -> tuple[datetime | None, tuple[str, ...]]:
    snapshot = plan_version.quote_snapshot
    plan = plan_version.plan_json
    if snapshot is None or not isinstance(plan, dict):
        return None, ()
    quote = snapshot.quote_json
    if not isinstance(quote, dict):
        return None, ()
    quote_lines = quote.get("lineItems")
    products = plan.get("furnitureSuggestions")
    if not isinstance(quote_lines, list) or not isinstance(products, list):
        return None, ()
    if not quote_lines:
        return None, ()

    remaining = [item for item in products if isinstance(item, dict)]
    expirations: list[datetime] = []
    reasons: list[str] = []
    for raw_line in quote_lines:
        if not isinstance(raw_line, dict):
            continue
        line_identity = _identity(raw_line)
        matching_index = next(
            (
                index
                for index, product in enumerate(remaining)
                if _identity(product) == line_identity
            ),
            None,
        )
        if matching_index is None:
            continue
        product = remaining.pop(matching_index)
        try:
            verification = frozen_product_eligibility_service.verify_suggestion(
                product, allow_development=allow_development
            )
        except frozen_product_eligibility_service.FrozenEligibilityError as exc:
            reasons.append(exc.code)
        else:
            expirations.append(verification.price_valid_to)
    return (
        min(expirations) if expirations else None,
        tuple(dict.fromkeys(reasons)),
    )


def require_deliverable(
    plan_version: DesignPlanVersion,
    *,
    now: datetime | None = None,
) -> PlanDeliveryFacts:
    """失败关闭地校验交付资格，并返回可证明的冻结交付事实。"""
    reasons: list[str] = []
    revision = plan_version.revision
    allow_development = catalog_service.development_catalog_enabled()
    if revision is None or revision.status != "completed":
        reasons.append("revision_not_completed")
    source_reason = generation_source_service.validate_source_chain(revision)
    if source_reason is not None:
        reasons.append(source_reason)
    try:
        traceability = plan_traceability_audit_service.audit_plan_snapshot(
            plan_version, allow_development=allow_development
        )
    except (AttributeError, TypeError, ValueError):
        reasons.append("delivery_snapshot_invalid")
    else:
        reasons.extend(traceability.reason_codes)

    valid_until, eligibility_reasons = _quote_valid_until(
        plan_version, allow_development=allow_development
    )
    reasons.extend(eligibility_reasons)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if valid_until is not None and valid_until <= current:
        reasons.append("quote_expired")
    if reasons:
        raise PlanDeliveryBlocked(tuple(reasons))
    return PlanDeliveryFacts(
        quote_valid_until=valid_until,
        plan_snapshot=deepcopy(plan_version.plan_json),
        snapshot_digest=_snapshot_digest(plan_version),
        delivery_mode=(
            "development_preview"
            if any(
                isinstance(product, dict)
                and product.get("dataOrigin") == "development_fixture"
                for product in (plan_version.plan_json.get("furnitureSuggestions") or [])
            )
            else "commercial"
        ),
    )
