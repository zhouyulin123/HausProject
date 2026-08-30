"""导入可追溯的公开参考商品，不进入本店可报价商品目录。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Product


DATA_FILE = Path(__file__).resolve().parent / "data" / "public_reference_products.json"
_DATETIME_FIELDS = ("source_retrieved_at", "price_observed_at")
_REQUIRED_FIELDS = {
    "sku",
    "name",
    "category",
    "room",
    "price",
    "source_name",
    "source_url",
    "source_product_id",
    "source_retrieved_at",
    "price_observed_at",
    "model_width_mm",
    "model_height_mm",
    "model_depth_mm",
}


def load_dataset(path: Path = DATA_FILE) -> list[dict[str, Any]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("公开参考商品数据必须是 JSON 数组")

    seen_skus: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"第 {index} 条公开参考商品不是对象")
        missing = _REQUIRED_FIELDS - record.keys()
        if missing:
            raise ValueError(f"第 {index} 条公开参考商品缺少字段: {sorted(missing)}")
        sku = str(record["sku"])
        if sku in seen_skus:
            raise ValueError(f"公开参考商品 SKU 重复: {sku}")
        seen_skus.add(sku)
    return records


def _parse_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是 ISO 8601 时间")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def product_payload_from_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    if not str(payload["sku"]).startswith("REF-IKEA-"):
        raise ValueError("公开参考商品 SKU 必须使用 REF-IKEA- 前缀")
    if not str(payload["source_url"]).startswith("https://www.ikea.cn/cn/zh/p/"):
        raise ValueError("公开参考商品必须指向宜家中国官方商品页")

    payload["data_origin"] = "public_reference"
    payload["is_active"] = False
    payload["image_url"] = None
    payload.setdefault("model_status", "missing")
    payload.setdefault("price_note", "官网公开价格快照，仅供参考，不代表本店现货或报价")
    payload.setdefault("source_metadata", {"currency": "CNY"})
    payload["source_metadata"] = {
        **payload["source_metadata"],
        "currency": "CNY",
    }
    for field in _DATETIME_FIELDS:
        payload[field] = _parse_datetime(payload[field], field)
    return payload


def upsert_products(
    db: Session,
    records: list[dict[str, Any]],
) -> dict[str, int]:
    result = {"added": 0, "updated": 0}
    product_columns = {column.name for column in Product.__table__.columns}

    for record in records:
        payload = {
            key: value
            for key, value in product_payload_from_record(record).items()
            if key in product_columns and key not in {"id", "created_at", "updated_at"}
        }
        existing = db.scalar(select(Product).where(Product.sku == payload["sku"]))
        if existing:
            if existing.data_origin != "public_reference":
                raise ValueError(f"拒绝覆盖非公开参考商品: {payload['sku']}")
            for key, value in payload.items():
                setattr(existing, key, value)
            result["updated"] += 1
        else:
            db.add(Product(**payload))
            result["added"] += 1

    db.commit()
    return result


def main() -> None:
    records = load_dataset()
    with SessionLocal() as db:
        result = upsert_products(db, records)
    print(f"公开参考商品导入完成：新增 {result['added']}，更新 {result['updated']}")


if __name__ == "__main__":
    main()
