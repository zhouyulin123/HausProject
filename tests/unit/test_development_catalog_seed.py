from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import Product
from app.core.config import settings
from app.services.development_catalog_seed import supplement_development_catalog, restore_development_catalog


def test_seed_preserves_originals_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        product = Product(sku="SF-001", name="现有沙发", price=3200,
                          category="沙发", room="客厅", style="现代简约",
                          material="布艺", data_origin="merchant_draft", is_active=True)
        reference = Product(sku="REF-1", name="参考商品", price=200,
                            data_origin="public_reference", is_active=False)
        db.add_all([product, reference])
        db.commit()
        now = datetime(2026, 9, 11, tzinfo=timezone.utc)
        result = supplement_development_catalog(db, at=now)
        assert result["updated"] == 1
        assert product.price == 3200
        assert product.data_origin == "development_fixture"
        assert product.verified_by is None
        assert product.verification_status == "draft"
        assert product.source_metadata["development_fixture"]["original"]["data_origin"] == "merchant_draft"
        assert product.stock_quantity > 0
        assert product.region_codes == ["CN"]
        assert product.model_width_mm > 0
        version = product.record_version
        assert supplement_development_catalog(db, at=now)["updated"] == 0
        assert product.record_version == version
        assert reference.data_origin == "public_reference"
        product.record_version += 1
        with pytest.raises(ValueError, match="后续编辑"):
            restore_development_catalog(db)
        product.record_version = version
        assert restore_development_catalog(db)["restored"] == 1
        assert product.data_origin == "merchant_draft"
        assert product.source_metadata is None
        assert product.price == 3200
        assert product.stock_quantity is None
    engine.dispose()


def test_seed_refuses_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(ValueError, match="开发环境"):
        supplement_development_catalog(None)
