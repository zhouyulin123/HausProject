import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Product
from compile_active_catalog import (
    ACTIVE_DRAFT_SPECS,
    compile_active_products,
    validate_draft_specs,
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


def _product(sku: str, *, active: bool = True) -> Product:
    return Product(
        sku=sku,
        name="待整理商品",
        category="家具",
        room="客厅",
        style="现代简约",
        material="待复核材料",
        price=1000,
        size="详见 3D 参数",
        data_origin="unknown",
        is_active=active,
    )


def test_draft_specs_cover_40_complete_physical_products() -> None:
    specs = validate_draft_specs(ACTIVE_DRAFT_SPECS)

    assert len(specs) == 40
    assert len(set(specs)) == 40
    for sku, spec in specs.items():
        assert sku
        assert spec["model_width_mm"] > 0
        assert spec["model_height_mm"] > 0
        assert spec["model_depth_mm"] > 0
        assert "详见" not in spec["size"]


def test_compile_updates_known_product_as_editable_merchant_draft(db) -> None:
    product = _product("CJ-002")
    db.add(product)
    db.commit()

    result = compile_active_products(db, strict=False)
    db.refresh(product)

    assert result == {"updated": 1, "skipped": 0, "missing": 39}
    assert product.data_origin == "merchant_draft"
    assert product.source_name == "内部商品初稿"
    assert product.source_product_id == "CJ-002"
    assert product.price_note == "内部参考零售价，待人工复核；不含配送、安装和选配费用。"
    assert product.source_metadata["verification_status"] == "pending_manual_review"
    assert product.is_active is True
    assert (product.model_width_mm, product.model_height_mm, product.model_depth_mm) == (
        900,
        450,
        900,
    )
    assert "详见" not in product.size


def test_compile_does_not_modify_unlisted_or_inactive_products(db) -> None:
    unlisted = _product("SHOP-NEW-001")
    inactive = _product("CJ-002", active=False)
    db.add_all([unlisted, inactive])
    db.commit()

    result = compile_active_products(db, strict=False)
    db.refresh(unlisted)
    db.refresh(inactive)

    assert result == {"updated": 0, "skipped": 1, "missing": 40}
    assert unlisted.data_origin == "unknown"
    assert inactive.data_origin == "unknown"


def test_strict_mode_rolls_back_when_catalog_is_incomplete(db) -> None:
    product = _product("CJ-002")
    db.add(product)
    db.commit()

    with pytest.raises(ValueError, match="缺少 39 个目标 SKU"):
        compile_active_products(db, strict=True)

    db.refresh(product)
    assert product.data_origin == "unknown"
