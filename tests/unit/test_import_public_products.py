from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Product
from app.services.catalog_service import build_catalog_context
from import_public_products import (
    DATA_FILE,
    load_dataset,
    product_payload_from_record,
    upsert_products,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_public_dataset_has_traceable_inactive_reference_products() -> None:
    records = load_dataset(DATA_FILE)

    assert len(records) >= 15
    assert len({record["sku"] for record in records}) == len(records)
    assert {record["room"] for record in records} >= {"客厅", "卧室", "餐厅", "书房"}
    for record in records:
        assert record["sku"].startswith("REF-IKEA-")
        assert record["data_origin"] == "public_reference"
        assert record["is_active"] is False
        assert record["image_url"] is None
        assert record["source_name"] == "宜家中国官网"
        assert record["source_url"].startswith("https://www.ikea.cn/cn/zh/p/")
        assert record["source_product_id"]
        assert record["price"] > 0
        assert record["model_width_mm"] > 0
        assert record["model_height_mm"] > 0
        assert record["model_depth_mm"] > 0


def test_product_payload_parses_timestamps_and_keeps_reference_inactive() -> None:
    record = load_dataset(DATA_FILE)[0]

    payload = product_payload_from_record(record)

    assert payload["data_origin"] == "public_reference"
    assert payload["is_active"] is False
    assert isinstance(payload["source_retrieved_at"], datetime)
    assert isinstance(payload["price_observed_at"], datetime)
    assert payload["source_metadata"]["currency"] == "CNY"
    assert "不代表本店现货" in payload["price_note"]


def test_upsert_is_idempotent_and_does_not_enter_quote_catalog(db) -> None:
    record = load_dataset(DATA_FILE)[0]

    first = upsert_products(db, [record])
    second = upsert_products(db, [record])
    stored = db.query(Product).filter(Product.sku == record["sku"]).one()

    assert first == {"added": 1, "updated": 0}
    assert second == {"added": 0, "updated": 1}
    assert stored.data_origin == "public_reference"
    assert stored.is_active is False
    assert record["sku"] not in build_catalog_context(db)


def test_upsert_refuses_to_overwrite_non_reference_product(db) -> None:
    record = load_dataset(DATA_FILE)[0]
    db.add(
        Product(
            sku=record["sku"],
            name="本店同号商品",
            category="沙发",
            room="客厅",
            style="现代简约",
            price=999,
            data_origin="merchant",
            is_active=True,
        )
    )
    db.commit()

    with pytest.raises(ValueError, match="拒绝覆盖非公开参考商品"):
        upsert_products(db, [record])

