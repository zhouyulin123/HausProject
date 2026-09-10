from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Product
from app.services.catalog_service import build_catalog_readiness_summary
from app.services.product_eligibility import PRODUCT_ELIGIBILITY_REASON_CODES


NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def _product(sku: str, **overrides) -> Product:
    values = {
        "sku": sku,
        "name": f"商品 {sku}",
        "category": "沙发",
        "room": "客厅",
        "style": "现代简约",
        "material": "布艺",
        "price": 5000,
        "is_active": True,
        "data_origin": "merchant",
        "source_name": "供应商目录",
        "source_url": f"https://supplier.example/products/{sku}",
        "source_product_id": sku,
        "source_retrieved_at": NOW - timedelta(days=1),
        "price_observed_at": NOW - timedelta(days=1),
        "verification_status": "verified",
        "verified_at": NOW - timedelta(hours=1),
        "verified_by": "user:7",
        "data_version": "catalog-readiness-v1",
        "availability_status": "in_stock",
        "stock_quantity": 5,
        "region_codes": ["CN-SH"],
        "lead_time_days_min": 3,
        "lead_time_days_max": 7,
        "price_valid_from": NOW - timedelta(days=1),
        "price_valid_to": NOW + timedelta(days=1),
        "model_width_mm": 2200,
        "model_height_mm": 800,
        "model_depth_mm": 950,
    }
    values.update(overrides)
    return Product(**values)


def test_catalog_readiness_summarizes_all_products_with_stable_reason_keys(db):
    db.add_all(
        [
            _product("READY"),
            _product(
                "DRAFT",
                data_origin="merchant_draft",
                verification_status="draft",
                availability_status="unknown",
                stock_quantity=None,
                price_valid_from=None,
                price_valid_to=None,
            ),
            _product(
                "REFERENCE",
                is_active=False,
                data_origin="public_reference",
            ),
        ]
    )
    db.commit()

    summary = build_catalog_readiness_summary(db, region="cn-sh", at=NOW)

    assert summary["checked_at"] == NOW
    assert summary["region"] == "CN-SH"
    assert summary["total"] == 3
    assert summary["active_total"] == 2
    assert summary["inactive_total"] == 1
    assert summary["eligible_total"] == 1
    assert summary["ineligible_total"] == 2
    assert summary["verification_status_counts"] == {"draft": 1, "verified": 2}
    assert summary["availability_status_counts"] == {"in_stock": 2, "unknown": 1}
    assert summary["data_origin_counts"] == {
        "merchant": 1,
        "merchant_draft": 1,
        "public_reference": 1,
    }
    assert summary["reason_code_counts"]["verification_required"] == 1
    assert summary["reason_code_counts"]["availability_unknown"] == 1
    assert summary["reason_code_counts"]["price_validity_unknown"] == 1
    assert summary["reason_code_counts"]["inactive"] == 1
    assert summary["reason_code_counts"]["public_reference"] == 1
    assert summary["reason_code_counts"]["region_unavailable"] == 0
    assert tuple(summary["reason_code_counts"]) == PRODUCT_ELIGIBILITY_REASON_CODES
    assert all(count >= 0 for count in summary["reason_code_counts"].values())


def test_catalog_readiness_applies_explicit_region_to_every_product(db):
    db.add(_product("SH-ONLY"))
    db.commit()

    summary = build_catalog_readiness_summary(db, region="CN-BJ", at=NOW)

    assert summary["eligible_total"] == 0
    assert summary["reason_code_counts"]["region_unavailable"] == 1


def test_catalog_readiness_rejects_empty_region(db):
    with pytest.raises(ValueError, match="region must not be empty"):
        build_catalog_readiness_summary(db, region="  ", at=NOW)
