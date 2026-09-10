"""商品资格、确定性替代与报价的单一事实源。"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import logging
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import CustomQuoteRule, Product
from app.services.product_asset_service import (
    approved_product_asset_url,
    product_asset_contract,
)
from app.services.product_eligibility import (
    PRODUCT_ELIGIBILITY_REASON_CODES,
    ProductDimensions,
    ProductEligibility,
    ProductEligibilityFacts,
    ProductEligibilityPolicy,
    evaluate_product_eligibility,
)


logger = logging.getLogger(__name__)
def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_product_eligible(
    product: Product,
    *,
    at: datetime | None = None,
    region: str | None = None,
    allow_draft: bool = False,
    max_unit_price: int | None = None,
    max_dimensions_mm: Mapping[str, int] | None = None,
    required_quantity: int | None = None,
) -> ProductEligibility:
    """把 ORM 商品适配为纯资格事实后执行统一规则。"""
    facts, policy = _product_eligibility_inputs(
        product,
        at=_as_utc(at) or datetime.now(timezone.utc),
        region=region,
        allow_draft=allow_draft,
        max_unit_price=max_unit_price,
        max_dimensions_mm=max_dimensions_mm,
        required_quantity=required_quantity,
    )
    return evaluate_product_eligibility(facts, policy)


def _dimensions(values: Mapping[str, int] | None) -> ProductDimensions | None:
    if not values:
        return None
    return ProductDimensions(
        width=values.get("width"),
        depth=values.get("depth"),
        height=values.get("height"),
    )


def _product_eligibility_inputs(
    product: Product,
    *,
    at: datetime,
    region: str | None,
    allow_draft: bool,
    max_unit_price: int | None,
    max_dimensions_mm: Mapping[str, int] | None,
    required_quantity: int | None,
) -> tuple[ProductEligibilityFacts, ProductEligibilityPolicy]:
    facts = ProductEligibilityFacts(
        is_active=bool(product.is_active),
        data_origin=product.data_origin,
        source_name=product.source_name,
        source_url=product.source_url,
        source_product_id=product.source_product_id,
        source_retrieved_at=_as_utc(product.source_retrieved_at),
        price_observed_at=_as_utc(product.price_observed_at),
        verification_status=product.verification_status,
        verified_at=_as_utc(product.verified_at),
        verified_by=product.verified_by,
        data_version=product.data_version,
        availability_status=product.availability_status,
        stock_quantity=product.stock_quantity,
        lead_time_days_min=product.lead_time_days_min,
        lead_time_days_max=product.lead_time_days_max,
        price_valid_from=_as_utc(product.price_valid_from),
        price_valid_to=_as_utc(product.price_valid_to),
        region_codes=tuple(
            str(code).strip().upper()
            for code in (product.region_codes or [])
            if str(code).strip()
        ),
        dimensions_mm=ProductDimensions(
            width=product.model_width_mm,
            depth=product.model_depth_mm,
            height=product.model_height_mm,
        ),
        unit_price=product.price,
    )
    policy = ProductEligibilityPolicy(
        checked_at=at,
        region=region.strip().upper() if region else None,
        allow_draft=allow_draft,
        max_unit_price=max_unit_price,
        max_dimensions_mm=_dimensions(max_dimensions_mm),
        required_quantity=required_quantity,
    )
    return facts, policy


def _eligibility_snapshot(
    product: Product,
    *,
    checked_at: datetime,
    region: str | None,
    allow_draft: bool,
    max_unit_price: int | None,
    max_dimensions_mm: Mapping[str, int] | None,
    required_quantity: int,
) -> dict[str, Any]:
    """冻结资格判断的完整输入，供离线证据独立复算。"""
    facts, policy = _product_eligibility_inputs(
        product,
        at=checked_at,
        region=region,
        allow_draft=allow_draft,
        max_unit_price=max_unit_price,
        max_dimensions_mm=max_dimensions_mm,
        required_quantity=required_quantity,
    )
    decision = evaluate_product_eligibility(facts, policy)
    maximums = policy.max_dimensions_mm
    normalized_dimensions = (
        {
            key: value
            for key, value in {
                "width": maximums.width,
                "depth": maximums.depth,
                "height": maximums.height,
            }.items()
            if value is not None
        }
        if maximums is not None
        else {}
    )
    return {
        "schemaVersion": "1.1",
        "checkedAt": policy.checked_at.isoformat(),
        "sku": product.sku,
        "quantity": required_quantity,
        "unitPrice": facts.unit_price,
        "dataVersion": product.data_version,
        "recordVersion": product.record_version,
        "policy": {
            "region": policy.region,
            "allowDraft": policy.allow_draft,
            "maxUnitPrice": policy.max_unit_price,
            "maxDimensionsMm": normalized_dimensions,
        },
        "facts": {
            "isActive": facts.is_active,
            "dataOrigin": facts.data_origin,
            "sourceName": facts.source_name,
            "sourceUrl": facts.source_url,
            "sourceProductId": facts.source_product_id,
            "sourceRetrievedAt": (
                facts.source_retrieved_at.isoformat()
                if facts.source_retrieved_at is not None
                else None
            ),
            "priceObservedAt": (
                facts.price_observed_at.isoformat()
                if facts.price_observed_at is not None
                else None
            ),
            "verificationStatus": facts.verification_status,
            "verifiedAt": (
                facts.verified_at.isoformat()
                if facts.verified_at is not None
                else None
            ),
            "verifiedBy": facts.verified_by,
            "dataVersion": facts.data_version,
            "availabilityStatus": facts.availability_status,
            "stockQuantity": facts.stock_quantity,
            "leadTimeDaysMin": facts.lead_time_days_min,
            "leadTimeDaysMax": facts.lead_time_days_max,
            "priceValidFrom": (
                facts.price_valid_from.isoformat()
                if facts.price_valid_from is not None
                else None
            ),
            "priceValidTo": (
                facts.price_valid_to.isoformat()
                if facts.price_valid_to is not None
                else None
            ),
            "regionCodes": sorted(set(facts.region_codes)),
            "dimensionsMm": {
                "width": facts.dimensions_mm.width,
                "depth": facts.dimensions_mm.depth,
                "height": facts.dimensions_mm.height,
            },
        },
        "eligible": decision.eligible,
        "reasonCodes": list(decision.reason_codes),
    }


def eligible_products(
    db: Session,
    *,
    at: datetime | None = None,
    region: str | None = None,
    allow_draft: bool = False,
    max_unit_price: int | None = None,
    max_dimensions_mm: Mapping[str, int] | None = None,
    required_quantity: int | None = None,
) -> list[Product]:
    products = db.scalars(
        select(Product)
        .where(Product.is_active.is_(True))
        .options(selectinload(Product.assets))
        .execution_options(populate_existing=True)
    ).all()
    return [
        product for product in products
        if is_product_eligible(
            product,
            at=at,
            region=region,
            allow_draft=allow_draft,
            max_unit_price=max_unit_price,
            max_dimensions_mm=max_dimensions_mm,
            required_quantity=required_quantity,
        ).eligible
    ]


def _status_counts(products: list[Product], attribute: str, fallback: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for product in products:
        value = str(getattr(product, attribute, None) or fallback).strip() or fallback
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def build_catalog_readiness_summary(
    db: Session,
    *,
    region: str,
    at: datetime | None = None,
) -> dict[str, Any]:
    """按线上统一门禁汇总目录就绪度，不修改任何商品事实。"""
    checked_at = _as_utc(at) or datetime.now(timezone.utc)
    normalized_region = region.strip().upper()
    if not normalized_region:
        raise ValueError("region must not be empty")

    products = list(db.scalars(select(Product).order_by(Product.id.asc())).all())
    reason_code_counts = {
        code: 0 for code in PRODUCT_ELIGIBILITY_REASON_CODES
    }
    eligible_total = 0
    for product in products:
        decision = is_product_eligible(
            product,
            at=checked_at,
            region=normalized_region,
        )
        if decision.eligible:
            eligible_total += 1
        for reason_code in decision.reason_codes:
            reason_code_counts.setdefault(reason_code, 0)
            reason_code_counts[reason_code] += 1

    total = len(products)
    active_total = sum(bool(product.is_active) for product in products)
    return {
        "checked_at": checked_at,
        "region": normalized_region,
        "total": total,
        "active_total": active_total,
        "inactive_total": total - active_total,
        "eligible_total": eligible_total,
        "ineligible_total": total - eligible_total,
        "verification_status_counts": _status_counts(
            products, "verification_status", "draft"
        ),
        "availability_status_counts": _status_counts(
            products, "availability_status", "unknown"
        ),
        "data_origin_counts": _status_counts(products, "data_origin", "unknown"),
        "reason_code_counts": reason_code_counts,
    }


def _explicit_preferences(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return list(
        dict.fromkeys(
            str(item).strip()
            for item in values
            if isinstance(item, str) and item.strip()
        )
    )


def rank_products_by_preferences(
    products: list[Product],
    *,
    preferred_styles: Any = None,
    preferred_materials: Any = None,
) -> list[tuple[Product, list[dict[str, str]]]]:
    """仅按显式偏好确定性排序，不产生推测性的相似度分数。"""
    styles = _explicit_preferences(preferred_styles)
    materials = _explicit_preferences(preferred_materials)

    def exact_match(value: Any, preferences: list[str]) -> int | None:
        normalized = str(value or "").strip().casefold()
        return next(
            (
                index
                for index, preference in enumerate(preferences)
                if normalized == preference.casefold()
            ),
            None,
        )

    def contained_match(value: Any, preferences: list[str]) -> int | None:
        normalized = "".join(str(value or "").split()).casefold()
        return next(
            (
                index
                for index, preference in enumerate(preferences)
                if "".join(preference.split()).casefold() in normalized
            ),
            None,
        )

    ranked: list[
        tuple[tuple[int, int, int, int, int, int, int], Product, list[dict[str, str]]]
    ] = []
    for product in products:
        style_index = exact_match(product.style, styles)
        material_index = contained_match(product.material, materials)
        reasons: list[dict[str, str]] = []
        if style_index is not None:
            reasons.append(
                {
                    "code": "style_preference_match",
                    "preference": styles[style_index],
                    "value": product.style or "",
                }
            )
        if material_index is not None:
            reasons.append(
                {
                    "code": "material_preference_match",
                    "preference": materials[material_index],
                    "value": product.material or "",
                }
            )
        match_count = int(style_index is not None) + int(material_index is not None)
        sort_key = (
            -match_count,
            int(style_index is None),
            style_index if style_index is not None else len(styles),
            int(material_index is None),
            material_index if material_index is not None else len(materials),
            product.price,
            product.id or 0,
        )
        ranked.append((sort_key, product, reasons))
    ranked.sort(key=lambda item: item[0])
    return [(product, reasons) for _, product, reasons in ranked]


def _rule_available_in_region(
    rule: CustomQuoteRule,
    region: str | None,
) -> bool:
    codes = {
        str(code).strip().upper()
        for code in (rule.region_codes or [])
        if str(code).strip()
    }
    if not codes or "*" in codes:
        return True
    return region is not None and region.strip().upper() in codes


def active_custom_quote_rules(
    db: Session,
    *,
    region: str | None = None,
) -> List[CustomQuoteRule]:
    rules = db.scalars(
        select(CustomQuoteRule).where(CustomQuoteRule.is_active.is_(True))
    ).all()
    return [rule for rule in rules if _rule_available_in_region(rule, region)]


def _version_hash(prefix: str, payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:16]}"


def _catalog_version(products: list[Product]) -> str:
    payload = [
        (product.sku, product.data_version, product.record_version)
        for product in sorted(products, key=lambda item: item.sku or "")
    ]
    return _version_hash("catalog", payload)


def _rule_version(rules: list[CustomQuoteRule]) -> str:
    payload = [
        (
            rule.id,
            rule.project_name,
            rule.material_grade,
            rule.unit_price,
            sorted(rule.region_codes or []),
            rule.waste_rate_bps,
            rule.minimum_quantity,
            rule.installation_fee,
            rule.shipping_fee,
            rule.tax_rate_bps,
            rule.data_version,
            rule.record_version,
            str(rule.updated_at or rule.created_at),
        )
        for rule in sorted(rules, key=lambda item: item.id or 0)
    ]
    return _version_hash("rules", payload)


def calculate_custom_quote(
    rule: CustomQuoteRule,
    requested_quantity: Decimal | float | int,
    *,
    currency_quantum: Decimal = Decimal("1"),
) -> dict[str, Any]:
    """按规则费用因子计算单行报价，供方案与定制家具共用。"""
    requested = Decimal(str(requested_quantity))
    waste_multiplier = Decimal("1") + (
        Decimal(rule.waste_rate_bps or 0) / Decimal("10000")
    )
    billable = max(
        requested * waste_multiplier,
        Decimal(str(rule.minimum_quantity or 0)),
    )
    base_subtotal = (Decimal(rule.unit_price) * billable).quantize(
        currency_quantum,
        rounding=ROUND_HALF_UP,
    )
    installation_fee = int(rule.installation_fee or 0)
    shipping_fee = int(rule.shipping_fee or 0)
    pre_tax_subtotal = base_subtotal + installation_fee + shipping_fee
    tax_amount = (
        Decimal(pre_tax_subtotal)
        * Decimal(rule.tax_rate_bps or 0)
        / Decimal("10000")
    ).quantize(currency_quantum, rounding=ROUND_HALF_UP)
    return {
        "requestedQuantity": requested.quantize(Decimal("0.001")),
        "billableQuantity": billable.quantize(Decimal("0.001")),
        "wasteRateBps": int(rule.waste_rate_bps or 0),
        "minimumQuantity": float(rule.minimum_quantity or 0),
        "baseSubtotal": base_subtotal,
        "installationFee": installation_fee,
        "shippingFee": shipping_fee,
        "taxRateBps": int(rule.tax_rate_bps or 0),
        "taxAmount": tax_amount,
        "subtotal": pre_tax_subtotal + tax_amount,
    }


def build_catalog_context(
    db: Session,
    *,
    at: datetime | None = None,
    region: str | None = None,
    allow_draft: bool = False,
    max_unit_price: int | None = None,
    max_dimensions_mm: Mapping[str, int] | None = None,
) -> str:
    """只把通过统一资格门禁的商品暴露给模型。"""
    products = eligible_products(
        db,
        at=at,
        region=region,
        allow_draft=allow_draft,
        max_unit_price=max_unit_price,
        max_dimensions_mm=max_dimensions_mm,
    )
    lines = ["【本店成品家具库】格式: sku|名称|类别|空间|风格|材质|价格(元)|尺寸"]
    for product in products:
        price = (
            f"{product.price}-{product.price_max}"
            if product.price_max
            else str(product.price)
        )
        lines.append(
            f"{product.sku}|{product.name}|{product.category}|{product.room}|"
            f"{product.style}|{product.material}|{price}|{product.size}"
        )
    lines.extend(["", "【本店定制项目价目表】格式: 项目|材料档位|单价(元)|计价单位"])
    for rule in active_custom_quote_rules(db, region=region):
        lines.append(
            f"{rule.project_name}|{rule.material_grade}|{rule.unit_price}|"
            f"{rule.pricing_unit}|损耗{rule.waste_rate_bps / 100:.2f}%|"
            f"最低{rule.minimum_quantity:g}|安装{rule.installation_fee}|"
            f"运输{rule.shipping_fee}|税率{rule.tax_rate_bps / 100:.2f}%"
        )
    return "\n".join(lines)


def _product_price_text(product: Product) -> str:
    return (
        f"¥{product.price:,} - {product.price_max:,}"
        if product.price_max
        else f"¥{product.price:,}"
    )


def find_product_alternatives(
    db: Session,
    source: Product,
    *,
    at: datetime | None = None,
    region: str | None = None,
    max_unit_price: int | None = None,
    max_dimensions_mm: Mapping[str, int] | None = None,
    required_quantity: int | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """按显式替代、同类/空间、价格接近度稳定排序，不使用 LLM。"""
    explicit = {sku: index for index, sku in enumerate(source.alternative_skus or [])}
    candidates = []
    for product in eligible_products(
        db,
        at=at,
        region=region,
        max_unit_price=max_unit_price,
        max_dimensions_mm=max_dimensions_mm,
        required_quantity=required_quantity,
    ):
        if product.id == source.id or product.sku == source.sku:
            continue
        same_category = product.category == source.category
        same_room = product.room == source.room
        is_explicit = product.sku in explicit
        if not (is_explicit or same_category or same_room):
            continue
        reasons = []
        if is_explicit:
            reasons.append("explicit_alternative")
        if same_category:
            reasons.append("same_category")
        if same_room:
            reasons.append("same_room")
        if product.price <= source.price:
            reasons.append("price_not_higher")
        reasons.append(
            "dimensions_fit" if max_dimensions_mm else "dimensions_known"
        )
        if required_quantity is not None:
            reasons.append("stock_sufficient")
        sort_key = (
            0 if is_explicit else 1,
            explicit.get(product.sku, 9999),
            -(int(same_category) + int(same_room)),
            abs(product.price - source.price),
            product.sku or "",
        )
        candidates.append(
            (sort_key, {"sku": product.sku, "product": product, "reason_codes": reasons})
        )
    return [item for _, item in sorted(candidates, key=lambda entry: entry[0])[:limit]]


def _match_rule(
    rules: List[CustomQuoteRule], project: str, grade: Optional[str]
) -> tuple[Optional[CustomQuoteRule], str | None, list[int]]:
    matches = [
        rule
        for rule in rules
        if project
        and grade
        and rule.project_name == project
        and rule.material_grade == grade
    ]
    matching_ids = [rule.id for rule in matches if rule.id is not None]
    if len(matches) == 1:
        return matches[0], None, matching_ids
    if len(matches) > 1:
        return None, "custom_quote_rule_ambiguous", matching_ids
    return None, "custom_quote_rule_missing", []


def _normalize_furniture_quantity(value: Any) -> int:
    try:
        return max(1, min(10, int(value)))
    except (TypeError, ValueError):
        return 1


def verify_and_enrich_plans(
    db: Session,
    plans: List[Dict[str, Any]],
    *,
    at: datetime | None = None,
    region: str | None = None,
    allow_draft: bool = False,
    budget_max: int | None = None,
    max_dimensions_mm: Mapping[str, int] | None = None,
    allow_empty_furniture: bool = False,
) -> None:
    """统一校验 SKU、确定性替代、回填价格并生成版本化报价。"""
    current = _as_utc(at) or datetime.now(timezone.utc)
    all_products = db.scalars(
        select(Product)
        .where(Product.is_active.is_(True))
        .options(selectinload(Product.assets))
        .execution_options(populate_existing=True)
    ).all()
    by_sku = {product.sku: product for product in all_products if product.sku}
    products = eligible_products(
        db,
        at=current,
        region=region,
        allow_draft=allow_draft,
        max_unit_price=budget_max,
        max_dimensions_mm=max_dimensions_mm,
    )
    eligible_by_sku = {product.sku: product for product in products if product.sku}
    rules = active_custom_quote_rules(db, region=region)
    catalog_version = _catalog_version(products)
    rule_version = _rule_version(rules)

    for plan in plans:
        raw_items = plan.get("furnitureSuggestions") or []
        hard_errors: list[str] = []
        if not raw_items and not allow_empty_furniture:
            hard_errors.append("missing_product_sku")
        resolved_items: list[
            tuple[dict[str, Any], Product, str | None, list[str], int]
        ] = []
        rejected: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                rejected.append({"sku": None, "reason_codes": ["invalid_item"]})
                hard_errors.append("invalid_sku")
                continue
            requested_sku = item.get("sku") or item.get("id")
            if not requested_sku:
                rejected.append(
                    {"sku": None, "reason_codes": ["missing_product_sku"]}
                )
                hard_errors.append("missing_product_sku")
                continue
            quantity = _normalize_furniture_quantity(item.get("quantity", 1))
            product = eligible_by_sku.get(requested_sku)
            source = by_sku.get(requested_sku)
            if product is not None and not is_product_eligible(
                product,
                at=current,
                region=region,
                allow_draft=allow_draft,
                max_unit_price=budget_max,
                max_dimensions_mm=max_dimensions_mm,
                required_quantity=quantity,
            ).eligible:
                product = None
            replaced_sku = None
            replacement_reasons: list[str] = []
            if product is None:
                if source is not None:
                    alternatives = find_product_alternatives(
                        db,
                        source,
                        at=current,
                        region=region,
                        max_unit_price=budget_max,
                        max_dimensions_mm=max_dimensions_mm,
                        required_quantity=quantity,
                        limit=1,
                    )
                    if alternatives:
                        replacement = alternatives[0]
                        product = replacement["product"]
                        replaced_sku = requested_sku
                        replacement_reasons = replacement["reason_codes"]
                if product is None:
                    reasons = (
                        is_product_eligible(
                            source,
                            at=current,
                            region=region,
                            allow_draft=allow_draft,
                            max_unit_price=budget_max,
                            max_dimensions_mm=max_dimensions_mm,
                            required_quantity=quantity,
                        ).reason_codes
                        if source is not None
                        else ("sku_not_found",)
                    )
                    rejected.append({"sku": requested_sku, "reason_codes": list(reasons)})
                    hard_errors.append(
                        "insufficient_stock"
                        if "insufficient_stock" in reasons
                        else "invalid_sku"
                    )
                    continue
            resolved_items.append(
                (item, product, replaced_sku, replacement_reasons, quantity)
            )

        enriched = []
        line_items = []
        furniture_total = 0
        for (
            item,
            product,
            replaced_sku,
            replacement_reasons,
            quantity,
        ) in resolved_items:
            subtotal = product.price * quantity
            if budget_max is not None and furniture_total + subtotal > budget_max:
                remaining_budget = max(0, budget_max - furniture_total)
                alternatives = find_product_alternatives(
                    db,
                    product,
                    at=current,
                    region=region,
                    max_unit_price=remaining_budget // quantity,
                    max_dimensions_mm=max_dimensions_mm,
                    required_quantity=quantity,
                    limit=1,
                )
                if not alternatives:
                    rejected.append(
                        {
                            "sku": product.sku,
                            "reason_codes": ["budget_exceeded"],
                        }
                    )
                    hard_errors.append("budget_exceeded")
                    continue
                replacement = alternatives[0]
                original_sku = replaced_sku or product.sku
                product = replacement["product"]
                replaced_sku = original_sku
                replacement_reasons = list(
                    dict.fromkeys(
                        [
                            *replacement_reasons,
                            *replacement["reason_codes"],
                            "budget_fit",
                        ]
                    )
                )
                subtotal = product.price * quantity
            furniture_total += subtotal
            line_item = {
                "sku": product.sku,
                "quantity": quantity,
                "unitPrice": product.price,
                "subtotal": subtotal,
                "dataVersion": product.data_version,
                "recordVersion": product.record_version,
            }
            line_items.append(line_item)
            asset_contract = product_asset_contract(product)
            enriched_item = {
                "id": product.sku,
                "sku": product.sku,
                "name": product.name,
                "category": product.category,
                "room": product.room,
                "style": product.style,
                "material": product.material,
                "priceRange": _product_price_text(product),
                "sizeSuggestion": product.size or "",
                "reason": item.get("reason") or product.selling_point or "",
                "alternative": product.alternative or "",
                "alternativeSkus": list(product.alternative_skus or []),
                "imageUrl": approved_product_asset_url(product, "image"),
                "modelUrl": asset_contract["approved_model_url"],
                "modelStatus": product.model_status,
                "modelDimensionsMm": {
                    "width": product.model_width_mm,
                    "height": product.model_height_mm,
                    "depth": product.model_depth_mm,
                },
                "modelSpecJson": product.model_spec_json,
                "assetMode": asset_contract["asset_mode"],
                "fallbackReason": asset_contract["fallback_reason"],
                "assetReview": asset_contract["asset_review"],
                "dataOrigin": product.data_origin,
                "sourceName": product.source_name,
                "sourceUrl": product.source_url,
                "verifiedAt": (
                    product.verified_at.isoformat() if product.verified_at else None
                ),
                "dataStatus": (
                    "verified" if product.verification_status == "verified" else "draft"
                ),
                "quantity": quantity,
                "unitPrice": product.price,
                "subtotal": subtotal,
                "dataVersion": product.data_version,
                "recordVersion": product.record_version,
                "catalogEligibility": _eligibility_snapshot(
                    product,
                    checked_at=current,
                    region=region,
                    allow_draft=allow_draft,
                    max_unit_price=budget_max,
                    max_dimensions_mm=max_dimensions_mm,
                    required_quantity=quantity,
                ),
            }
            if replaced_sku:
                enriched_item["replacedSku"] = replaced_sku
                enriched_item["replacementReasonCodes"] = replacement_reasons
            enriched.append(enriched_item)
        plan["furnitureSuggestions"] = enriched

        custom_items = []
        custom_lines = []
        custom_rule_errors: list[dict[str, Any]] = []
        custom_total = 0
        raw_customs = plan.get("customItems") or []
        for item in raw_customs:
            if not isinstance(item, dict):
                hard_errors.append("custom_quote_rule_missing")
                custom_rule_errors.append({
                    "project": None,
                    "grade": None,
                    "reason_code": "custom_quote_rule_missing",
                    "matching_rule_ids": [],
                })
                continue
            project = str(item.get("project") or "").strip()
            grade = str(item.get("grade") or "").strip()
            rule, rule_error, matching_rule_ids = _match_rule(
                rules,
                project,
                grade,
            )
            if rule is None:
                code = rule_error or "custom_quote_rule_missing"
                hard_errors.append(code)
                custom_rule_errors.append({
                    "project": project or None,
                    "grade": grade or None,
                    "reason_code": code,
                    "matching_rule_ids": matching_rule_ids,
                })
                continue
            try:
                quantity = max(0.5, min(60.0, float(item.get("quantity", 1))))
            except (TypeError, ValueError):
                quantity = 1.0
            calculation = calculate_custom_quote(rule, quantity)
            subtotal = int(calculation["subtotal"])
            calculation_snapshot = {
                "requestedQuantity": float(calculation["requestedQuantity"]),
                "billableQuantity": float(calculation["billableQuantity"]),
                "wasteRateBps": calculation["wasteRateBps"],
                "minimumQuantity": calculation["minimumQuantity"],
                "baseSubtotal": int(calculation["baseSubtotal"]),
                "installationFee": calculation["installationFee"],
                "shippingFee": calculation["shippingFee"],
                "taxRateBps": calculation["taxRateBps"],
                "taxAmount": int(calculation["taxAmount"]),
                "subtotal": subtotal,
            }
            custom_total += subtotal
            custom_items.append(
                {
                    "project": rule.project_name,
                    "grade": rule.material_grade,
                    "unit": rule.pricing_unit,
                    "unitPrice": rule.unit_price,
                    "quantity": round(quantity, 1),
                    **calculation_snapshot,
                    "subtotal": subtotal,
                    "note": item.get("note") or rule.description or "",
                    "ruleId": rule.id,
                    "dataVersion": rule.data_version,
                    "recordVersion": rule.record_version,
                }
            )
            custom_lines.append(
                {
                    "ruleId": rule.id,
                    "quantity": round(quantity, 3),
                    **calculation_snapshot,
                    "unitPrice": rule.unit_price,
                    "subtotal": subtotal,
                    "dataVersion": rule.data_version,
                    "recordVersion": rule.record_version,
                }
            )
        plan["customItems"] = custom_items
        price_version = _version_hash(
            "prices",
            [
                (
                    line["sku"], line["unitPrice"],
                    line["dataVersion"], line["recordVersion"],
                )
                for line in line_items
            ],
        )
        hard_errors = list(dict.fromkeys(hard_errors))
        plan["catalogValidation"] = {
            "rejected": rejected,
            "customRuleErrors": custom_rule_errors,
            "hardErrors": hard_errors,
            "quoteStatus": "blocked" if hard_errors else "priced",
        }
        if hard_errors:
            plan.pop("shopQuote", None)
            continue
        plan["shopQuote"] = {
            "furnitureTotal": furniture_total,
            "customTotal": custom_total,
            "total": furniture_total + custom_total,
            "catalogVersion": catalog_version,
            "priceVersion": price_version,
            "ruleVersion": rule_version,
            "pricedAt": current.isoformat(),
            "lineItems": line_items,
            "customLineItems": custom_lines,
        }
