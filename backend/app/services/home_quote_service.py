"""确定性分项估价；未知不按零元计入完整总价。"""

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json

from sqlalchemy import select

from app.db.models import CustomQuoteRule, HomeDesignQuote, Product
from app.services.aggregate_lock_service import lock_owned_task
from app.services.catalog_service import calculate_custom_quote, is_product_eligible
from app.services.custom_quote_evidence_service import build_evidence
from app.services.home_design_delivery import get_delivery


class HomeQuoteConflict(ValueError):
    pass


def digest(value):
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def response(row):
    snapshot = row.snapshot_json
    try:
        if not isinstance(snapshot, dict):
            raise ValueError("无有效快照")
        content = {
            key: value for key, value in snapshot.items() if key != "content_digest"
        }
        if (
            snapshot.get("content_digest") != digest(content)
            or snapshot.get("schema_version") != "home-quote/1.0"
            or snapshot.get("task_id") != row.task_id
            or snapshot.get("home_version") != row.home_version
        ):
            raise ValueError("快照与估价记录不一致")
    except (ValueError, TypeError) as exc:
        raise HomeQuoteConflict("估价快照损坏，请联系维护人员") from exc
    return {
        "id": row.id,
        "task_id": row.task_id,
        "home_version": row.home_version,
        "snapshot": snapshot,
    }


def read_quote(db, task_id, quote_id):
    row = db.scalar(
        select(HomeDesignQuote).where(
            HomeDesignQuote.task_id == task_id, HomeDesignQuote.id == quote_id
        )
    )
    if row is None:
        raise LookupError("估价快照不存在")
    return response(row)


def list_quotes(db, task_id, version, before, limit):
    query = select(HomeDesignQuote).where(
        HomeDesignQuote.task_id == task_id, HomeDesignQuote.home_version == version
    )
    if before is not None:
        query = query.where(HomeDesignQuote.id < before)
    rows = db.scalars(query.order_by(HomeDesignQuote.id.desc()).limit(limit + 1)).all()
    return {
        "items": [response(row) for row in rows[:limit]],
        "next_before_id": rows[limit - 1].id if len(rows) > limit else None,
    }


def _price_lines(db, source_lines, *, region, at):
    quantity = Counter(
        line["asset"]["source_id"]
        for line in source_lines
        if (line.get("asset") or {}).get("kind") == "product"
    )
    products = {
        product.id: product
        for product in db.scalars(
            select(Product)
            .where(Product.id.in_(sorted(quantity)))
            .order_by(Product.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    }
    rule_ids = {
        line["quote_rule_id"]
        for line in source_lines
        if line.get("entity_type") == "surface"
        and line.get("quote_rule_id") is not None
    }
    rules = {
        rule.id: rule
        for rule in db.scalars(
            select(CustomQuoteRule)
            .where(CustomQuoteRule.id.in_(sorted(rule_ids)))
            .order_by(CustomQuoteRule.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    }
    lines = []
    for source in source_lines:
        line = {
            key: source[key]
            for key in (
                "entity_type",
                "id",
                "room_id",
                "room_name",
                "name",
                "unit",
                "quantity",
            )
        }
        asset = source.get("asset")
        price, reasons = None, ["no_verified_price_binding"]
        total_price = None
        rule_evidence = None
        rule_evidence_digest = None
        source_id = asset.get("source_id") if asset else None
        source_version = asset.get("source_version") if asset else None
        source_data_version = None
        if source["entity_type"] == "surface":
            reasons = []
            rule_id = source.get("quote_rule_id")
            if source.get("quantity") is None:
                reasons.append(
                    "surface_scale_unconfirmed"
                    if source.get("quantity_status") == "pending_scale"
                    else "surface_quantity_unavailable"
                )
            if rule_id is None:
                reasons.append("quote_rule_required")
            elif region is None:
                reasons.append("region_required")
            else:
                rule = rules.get(rule_id)
                if rule is None:
                    reasons.append("quote_rule_missing")
                elif not rule.is_active:
                    reasons.append("quote_rule_inactive")
                elif (
                    not isinstance(rule.data_version, str)
                    or not rule.data_version.strip()
                    or not isinstance(rule.record_version, int)
                    or isinstance(rule.record_version, bool)
                    or rule.record_version < 1
                ):
                    reasons.append("quote_rule_version_invalid")
                elif rule.pricing_unit not in {"㎡", "m2", "m²"}:
                    reasons.append("quote_rule_unit_unsupported")
                elif rule.unit_price <= 0:
                    reasons.append("quote_rule_price_invalid")
                elif (
                    not isinstance(rule.project_name, str)
                    or not rule.project_name.strip()
                    or not isinstance(rule.material_grade, str)
                    or not rule.material_grade.strip()
                ):
                    reasons.append("quote_rule_metadata_invalid")
                else:
                    raw_region_codes = rule.region_codes or []
                    valid_region_codes = isinstance(raw_region_codes, list) and all(
                        isinstance(code, str)
                        and bool(code.strip())
                        and code == code.strip().upper()
                        for code in raw_region_codes
                    )
                    region_codes = set(raw_region_codes) if valid_region_codes else set()
                    if not valid_region_codes:
                        reasons.append("quote_rule_region_invalid")
                    elif (
                        region_codes
                        and "*" not in region_codes
                        and region not in region_codes
                    ):
                        reasons.append("quote_rule_region_mismatch")
                if not reasons and source.get("quantity") is not None:
                    calculation = calculate_custom_quote(
                        rule,
                        Decimal(str(source["quantity"])),
                    )
                    rule_evidence = build_evidence(
                        rule,
                        calculation,
                        checked_at=at,
                        region=region,
                    )
                    price = rule.unit_price
                    total_price = int(calculation["subtotal"])
                    rule_evidence_digest = digest(rule_evidence)
                    source_id = rule.id
                    source_version = rule.record_version
                    source_data_version = rule.data_version
        elif region is None:
            reasons = ["region_required"]
        elif asset and asset["kind"] == "product":
            product = products.get(asset["source_id"])
            if product is None:
                reasons = ["product_missing"]
            elif product.record_version != asset["source_version"]:
                reasons = ["product_version_changed"]
            else:
                eligibility = is_product_eligible(
                    product,
                    at=at,
                    region=region,
                    required_quantity=quantity[product.id],
                    allow_development=False,
                )
                reasons = list(eligibility.reason_codes)
                if not isinstance(product.price, int) or product.price <= 0:
                    reasons.append("price_invalid")
                if product.price_max is not None and product.price_max != product.price:
                    reasons.append("price_requires_selection")
                if not reasons:
                    price = product.price
                    total_price = price
        line.update(
            unit_price=price,
            total_price=total_price,
            price_status="quoted" if price is not None else "pending_quote",
            reasons=reasons,
            asset_digest=asset.get("content_digest") if asset else None,
            source_id=source_id,
            source_version=source_version,
            source_data_version=source_data_version,
            rule_evidence=rule_evidence,
            rule_evidence_digest=rule_evidence_digest,
        )
        lines.append(line)
    return lines


def preview_delivery(db, delivery, *, region, budget_max, at=None):
    """对尚未保存的候选交付即时估价；未知价格不会折算为零元总价。"""
    lines = _price_lines(
        db,
        delivery["lines"],
        region=region,
        at=at or datetime.now(timezone.utc),
    )
    pending = sum(line["unit_price"] is None for line in lines)
    subtotal = sum(line["total_price"] or 0 for line in lines)
    total = subtotal if lines and not pending and region is not None else None
    if region is None or (total is not None and budget_max is None):
        status = "unknown"
    elif pending or not lines:
        status = "incomplete"
    else:
        status = "within" if total <= budget_max else "over"
    return {
        "region": region,
        "currency": "CNY",
        "known_subtotal": subtotal,
        "pending_count": pending,
        "total_price": total,
        "budget_max": budget_max,
        "budget_status": status,
        "limitations": [
            "仅核算候选方案中已通过商业资格校验的冻结商品与显式绑定规则的材料，未知价格不按零元处理。",
            "材料规则费用按表面报价行独立计算；未绑定材料、定制及未列项目仍待报价。",
        ],
    }


def create_quote(db, *, task_id, session_id, payload):
    if lock_owned_task(db, session_id=session_id, task_id=task_id) is None:
        raise LookupError("设计任务不存在")
    request_digest = digest(payload.model_dump())
    row = db.scalar(
        select(HomeDesignQuote)
        .where(
            HomeDesignQuote.task_id == task_id,
            HomeDesignQuote.client_mutation_id == payload.client_mutation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row:
        if row.request_digest != request_digest:
            raise HomeQuoteConflict("同一请求标识不能用于不同估价条件")
        result = response(row)
        db.commit()
        return result
    ids = db.scalars(
        select(HomeDesignQuote.id)
        .where(HomeDesignQuote.task_id == task_id)
        .with_for_update()
    ).all()
    if len(ids) >= 100:
        raise HomeQuoteConflict("当前设计已达到 100 份估价快照上限")
    delivery = get_delivery(db, task_id, payload.home_version)
    now = datetime.now(timezone.utc)
    lines = _price_lines(db, delivery["lines"], region=payload.region, at=now)
    pending = sum(line["unit_price"] is None for line in lines)
    subtotal = sum(line["total_price"] or 0 for line in lines)
    snapshot = {
        "schema_version": "home-quote/1.0",
        "rule_version": "catalog-material-eligibility/home-quote/1.1",
        "task_id": task_id,
        "validation": delivery["validation"],
        "scale_status": delivery["space"]["scale_status"],
        "home_version": payload.home_version,
        "space_version": delivery["space_version"],
        "delivery_digest": delivery["content_digest"],
        "region": payload.region,
        "created_at": now.isoformat(),
        "currency": "CNY",
        "lines": lines,
        "known_subtotal": subtotal,
        "pending_count": pending,
        "total_price": subtotal if lines and not pending else None,
        "limitations": [
            "仅为已列设计要素的商品与显式绑定材料规则价格快照，不是整屋工程总价或采购承诺。",
            "材料规则包含的损耗、最低量、安装、运输及税费按冻结证据计算；未绑定材料、定制及未列项目仍待报价。",
            "同一材料规则绑定多个表面时，每个表面作为独立报价行，最低量、安装费和运输费逐行计算；当前规则不表达整屋合并计费。",
        ],
    }
    snapshot["content_digest"] = digest(snapshot)
    row = HomeDesignQuote(
        task_id=task_id,
        home_version=payload.home_version,
        client_mutation_id=payload.client_mutation_id,
        request_digest=request_digest,
        snapshot_json=snapshot,
    )
    db.add(row)
    db.flush()
    result = response(row)
    db.commit()
    return result
