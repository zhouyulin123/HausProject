"""导入经人工核对的官网公开商品事实数据。

公开参考商品只用于方案匹配与价格研究，默认不可售，也不会进入报价候选。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Product


DATA_FILE = Path(__file__).resolve().parent / "data" / "public_products_ikea_cn_2026-08-30.json"
REFERENCE_ORIGIN = "public_reference"
PRODUCT_FIELDS = {
    column.name
    for column in Product.__table__.columns
    if column.name not in {"id", "created_at", "updated_at"}
}
TIMESTAMP_FIELDS = {"source_retrieved_at", "price_observed_at"}
REQUIRED_FIELDS = {
    "sku", "name", "category", "room", "price",
    "model_width_mm", "model_height_mm", "model_depth_mm",
    "data_origin", "is_active", "source_name", "source_url",
    "source_product_id", "source_retrieved_at", "price_observed_at",
    "price_note", "source_metadata",
}


def _parse_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是 ISO 8601 时间字符串")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} 不是有效的 ISO 8601 时间：{value}") from exc


def validate_records(records: Any) -> list[dict[str, Any]]:
    """验证公开数据集边界，防止参考数据误入可售商品。"""
    if not isinstance(records, list) or not records:
        raise ValueError("公开商品数据集必须是非空数组")

    validated: list[dict[str, Any]] = []
    seen_skus: set[str] = set()
    for index, raw in enumerate(records, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index} 条记录必须是对象")
        missing = sorted(REQUIRED_FIELDS - raw.keys())
        if missing:
            raise ValueError(f"第 {index} 条记录缺少字段：{', '.join(missing)}")

        sku = raw["sku"]
        if not isinstance(sku, str) or not sku.startswith("REF-IKEA-"):
            raise ValueError(f"第 {index} 条记录 SKU 必须以 REF-IKEA- 开头")
        if sku in seen_skus:
            raise ValueError(f"公开商品数据集存在重复 SKU：{sku}")
        seen_skus.add(sku)

        product_id = str(raw["source_product_id"])
        normalized_product_id = "".join(character for character in product_id if character.isdigit())
        if sku != f"REF-IKEA-{normalized_product_id}":
            raise ValueError(f"{sku} 与官网商品号 {product_id} 不一致")

        source = urlparse(str(raw["source_url"]))
        if (
            source.scheme != "https"
            or source.hostname != "www.ikea.cn"
            or not source.path.startswith("/cn/zh/p/")
        ):
            raise ValueError(f"{sku} 的来源必须是宜家中国官方商品页")
        if raw["source_name"] != "宜家中国官网":
            raise ValueError(f"{sku} 的来源名称不正确")
        if raw["data_origin"] != REFERENCE_ORIGIN or raw["is_active"] is not False:
            raise ValueError(f"{sku} 必须标记为不可售的 public_reference")
        if raw.get("image_url") is not None:
            raise ValueError(f"{sku} 不允许复制官网图片")
        if (
            not isinstance(raw["source_metadata"], dict)
            or raw["source_metadata"].get("currency") != "CNY"
        ):
            raise ValueError(f"{sku} 必须声明人民币价格口径")
        if not isinstance(raw["price"], int) or raw["price"] <= 0:
            raise ValueError(f"{sku} 的价格必须是正整数")
        for field in ("model_width_mm", "model_height_mm", "model_depth_mm"):
            if not isinstance(raw[field], int) or raw[field] <= 0:
                raise ValueError(f"{sku} 的 {field} 必须是正整数")

        _parse_datetime(raw["source_retrieved_at"], "source_retrieved_at")
        _parse_datetime(raw["price_observed_at"], "price_observed_at")
        validated.append(dict(raw))
    return validated


def load_dataset(path: Path | str = DATA_FILE) -> list[dict[str, Any]]:
    dataset_path = Path(path)
    with dataset_path.open("r", encoding="utf-8") as source:
        return validate_records(json.load(source))


def product_payload_from_record(record: dict[str, Any]) -> dict[str, Any]:
    validated = validate_records([record])[0]
    payload = {
        field: validated.get(field)
        for field in PRODUCT_FIELDS
        if field in validated
    }
    for field in TIMESTAMP_FIELDS:
        payload[field] = _parse_datetime(validated[field], field)
    return payload


def upsert_products(db: Session, records: Iterable[dict[str, Any]]) -> dict[str, int]:
    """按参考 SKU 幂等写入，并拒绝覆盖任何非参考商品。"""
    validated = validate_records(list(records))
    skus = [record["sku"] for record in validated]
    existing = {
        product.sku: product
        for product in db.scalars(select(Product).where(Product.sku.in_(skus))).all()
    }
    conflicts = [
        sku for sku, product in existing.items()
        if product.data_origin != REFERENCE_ORIGIN
    ]
    if conflicts:
        db.rollback()
        raise ValueError(f"拒绝覆盖非公开参考商品：{', '.join(sorted(conflicts))}")

    result = {"added": 0, "updated": 0}
    try:
        for record in validated:
            payload = product_payload_from_record(record)
            product = existing.get(record["sku"])
            if product is None:
                db.add(Product(**payload))
                result["added"] += 1
            else:
                for field, value in payload.items():
                    setattr(product, field, value)
                result["updated"] += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="导入官网公开参考商品")
    parser.add_argument("--file", type=Path, default=DATA_FILE, help="数据集 JSON 路径")
    parser.add_argument("--dry-run", action="store_true", help="只校验，不写入数据库")
    args = parser.parse_args()

    records = load_dataset(args.file)
    if args.dry_run:
        print(f"校验通过：{len(records)} 条公开参考商品")
        return

    with SessionLocal() as db:
        result = upsert_products(db, records)
    print(f"导入完成：新增 {result['added']} 条，更新 {result['updated']} 条")


if __name__ == "__main__":
    main()
