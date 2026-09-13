"""为既有活动家具补齐可逆的开发假设，不生成商业审核记录。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import Product
from compile_active_catalog import ACTIVE_DRAFT_SPECS

VERSION = "development-catalog-v1"
FIELDS = (
    "data_origin", "source_name", "source_url", "source_product_id",
    "source_retrieved_at", "price_observed_at", "price_note", "source_metadata",
    "verification_status", "availability_status", "region_codes", "stock_quantity",
    "lead_time_days_min", "lead_time_days_max", "price_valid_from", "price_valid_to",
    "verified_at", "verified_by", "data_version", "alternative_skus",
    "model_width_mm", "model_depth_mm", "model_height_mm", "size",
)
DATES = {"source_retrieved_at", "price_observed_at", "price_valid_from",
         "price_valid_to", "verified_at"}


def _require_development() -> None:
    if settings.app_env != "development":
        raise ValueError("仅允许在开发环境补充或恢复开发数据")


def supplement_development_catalog(db: Session, *, at: datetime | None = None) -> dict:
    _require_development()
    current = at or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("开发数据时间必须带时区")
    products = list(db.scalars(select(Product).where(
        Product.is_active.is_(True), Product.sku.in_(ACTIVE_DRAFT_SPECS),
    ).order_by(Product.id).with_for_update()))
    updated = 0
    for product in products:
        metadata = deepcopy(product.source_metadata or {})
        if "development_fixture" in metadata:
            continue
        # 不覆盖已核验、已驳回或来源已被业务人员维护的商品。
        if product.verification_status != "draft" or product.data_origin not in {
            "merchant_draft", "unknown", "demo",
        }:
            continue
        if not product.price or product.price < 0:
            raise ValueError(f"商品 {product.sku} 缺少有效参考价格")
        original = {field: deepcopy(getattr(product, field)) for field in FIELDS}
        for field in DATES:
            if original[field] is not None:
                original[field] = original[field].isoformat()
        for field, value in ACTIVE_DRAFT_SPECS[product.sku].items():
            if not getattr(product, field):
                setattr(product, field, value)
        product.data_origin = "development_fixture"
        product.source_name = "内部开发样本（非厂家核验）"
        product.source_product_id = product.sku
        product.source_retrieved_at = current
        product.price_observed_at = current
        product.price_note = "开发参考价；库存、交期和地区为模拟值，不作为销售承诺。"
        product.availability_status = "in_stock"
        product.stock_quantity = 50
        product.region_codes = ["CN"]
        product.lead_time_days_min = 3
        product.lead_time_days_max = 10
        product.price_valid_from = current
        product.price_valid_to = current + timedelta(days=180)
        product.verified_at = None
        product.verified_by = None
        product.data_version = VERSION
        product.alternative_skus = sorted(
            other.sku for other in products
            if other.id != product.id and other.category == product.category
            and other.room == product.room
        )
        product.record_version = (product.record_version or 1) + 1
        metadata["development_fixture"] = {
            "version": VERSION, "created_at": current.isoformat(),
            "assumptions": {"stock_quantity": 50, "region_codes": ["CN"],
                            "lead_time_days": [3, 10], "validity_days": 180},
            "price_basis": "保留原有内部参考价",
            "dimensions_basis": "保留原尺寸，缺失时使用现有确定性模型尺寸",
            "original": original, "applied_record_version": product.record_version,
        }
        product.source_metadata = metadata
        updated += 1
    db.flush()
    return {"updated": updated, "target_count": len(products), "version": VERSION}


def restore_development_catalog(db: Session) -> dict:
    _require_development()
    restored = 0
    for product in db.scalars(select(Product).where(
        Product.data_origin == "development_fixture",
    ).with_for_update()):
        fixture = (product.source_metadata or {}).get("development_fixture")
        if not fixture or fixture.get("version") != VERSION:
            continue
        if product.record_version != fixture["applied_record_version"]:
            raise ValueError(f"商品 {product.sku} 已有后续编辑，请人工合并后恢复")
        original = fixture["original"]
        for field in FIELDS:
            value = deepcopy(original[field])
            if field in DATES and value is not None:
                value = datetime.fromisoformat(value)
            setattr(product, field, value)
        product.record_version += 1
        restored += 1
    db.flush()
    return {"restored": restored}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写入；默认仅预览后回滚")
    parser.add_argument("--restore", action="store_true", help="恢复未被后续编辑的原始字段")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = restore_development_catalog(db) if args.restore else supplement_development_catalog(db)
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps({**result, "applied": args.apply}, ensure_ascii=False))


if __name__ == "__main__":
    main()
