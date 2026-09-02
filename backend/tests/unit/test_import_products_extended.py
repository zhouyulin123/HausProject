from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from app.db.database import Base
from app.db.models import Product
from import_products import (
    PRODUCT_HEADERS,
    parse_product_row,
    product_to_export_record,
    upsert_product_rows,
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


def _row(**overrides):
    values = {
        "sku": "SF-001",
        "名称": "三人位沙发",
        "类别": "沙发",
        "空间": "客厅",
        "风格": "现代简约",
        "材质": "聚酯纤维、实木框架",
        "参考价": 4999,
        "价格上限": 6999,
        "尺寸": "宽2380×深980×高760mm",
        "宽(mm)": 2380,
        "深(mm)": 980,
        "高(mm)": 760,
        "卖点": "可拆洗",
        "替代选择": "双人位",
        "启用状态": "是",
        "人工复核状态": "已复核",
        "可售状态": "现货",
        "地区代码": "CN-SH,CN-ZJ",
        "库存数量": 12,
        "最短交期(天)": 3,
        "最长交期(天)": 7,
        "价格生效时间": "2026-09-01T00:00:00+00:00",
        "价格失效时间": "2026-12-31T23:59:59+00:00",
        "复核负责人": "factory:7",
        "数据版本": "catalog-2026-q3",
        "替代SKU": "SF-002,SF-003",
        "价格备注": "门店确认价",
    }
    values.update(overrides)
    return tuple(values.get(header) for header in PRODUCT_HEADERS)


def test_parse_extended_product_row_keeps_numeric_and_review_fields() -> None:
    parsed = parse_product_row(PRODUCT_HEADERS, _row())

    assert parsed is not None
    assert parsed["product"]["price"] == 4999
    assert parsed["product"]["model_width_mm"] == 2380
    assert parsed["product"]["model_depth_mm"] == 980
    assert parsed["product"]["model_height_mm"] == 760
    assert parsed["product"]["is_active"] is True
    assert parsed["review_status"] == "manual_verified"
    assert parsed["product"]["verification_status"] == "verified"
    assert parsed["product"]["availability_status"] == "in_stock"
    assert parsed["product"]["region_codes"] == ["CN-SH", "CN-ZJ"]
    assert parsed["product"]["stock_quantity"] == 12
    assert parsed["product"]["lead_time_days_min"] == 3
    assert parsed["product"]["lead_time_days_max"] == 7
    assert parsed["product"]["data_version"] == "catalog-2026-q3"
    assert parsed["product"]["alternative_skus"] == ["SF-002", "SF-003"]


def test_parse_keeps_legacy_price_column_compatible() -> None:
    headers = [
        "sku", "名称", "类别", "空间", "风格", "材质", "价格", "价格上限",
        "尺寸", "卖点", "替代选择",
    ]
    row = [
        "SF-OLD", "旧版沙发", "沙发", "客厅", "现代简约", "布艺", 2999,
        None, "宽2100×深900×高780mm", "易维护", None,
    ]

    parsed = parse_product_row(headers, row)

    assert parsed is not None
    assert parsed["product"]["price"] == 2999
    assert "model_width_mm" not in parsed["product"]
    assert parsed["review_status"] == "pending_manual_review"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("参考价", 0, "参考价必须大于 0"),
        ("宽(mm)", -1, r"宽\(mm\)必须大于 0"),
        ("启用状态", "可能", "启用状态只能是"),
        ("人工复核状态", "未知", "人工复核状态只能是"),
    ],
)
def test_parse_rejects_invalid_controlled_values(field, value, message) -> None:
    with pytest.raises(ValueError, match=message):
        parse_product_row(PRODUCT_HEADERS, _row(**{field: value}))


def test_upsert_updates_draft_and_records_manual_verification(db) -> None:
    product = Product(
        sku="SF-001",
        name="旧名称",
        category="沙发",
        room="客厅",
        style="现代简约",
        material="旧材料",
        price=1000,
        data_origin="merchant_draft",
        is_active=True,
    )
    db.add(product)
    db.commit()

    result = upsert_product_rows(db, PRODUCT_HEADERS, [_row()])
    db.refresh(product)

    assert result == {"added": 0, "updated": 1, "skipped": 0}
    assert product.name == "三人位沙发"
    assert product.price == 4999
    assert product.data_origin == "merchant_draft"
    assert product.source_name == "内部商品主表"
    assert product.source_metadata["verification_status"] == "manual_verified"
    assert product.verification_status == "verified"
    assert product.availability_status == "in_stock"
    assert product.record_version == 2


def test_upsert_refuses_to_overwrite_public_reference(db) -> None:
    db.add(
        Product(
            sku="SF-001",
            name="官网参考商品",
            category="沙发",
            room="客厅",
            style="现代简约",
            material="布艺",
            price=999,
            data_origin="public_reference",
            is_active=False,
        )
    )
    db.commit()

    with pytest.raises(ValueError, match="拒绝覆盖公开参考商品"):
        upsert_product_rows(db, PRODUCT_HEADERS, [_row()])


def test_json_export_record_round_trips_lifecycle_fields(db) -> None:
    upsert_product_rows(db, PRODUCT_HEADERS, [_row()])
    product = db.query(Product).filter(Product.sku == "SF-001").one()

    exported = product_to_export_record(product)
    reparsed = parse_product_row(
        PRODUCT_HEADERS,
        tuple(exported.get(header) for header in PRODUCT_HEADERS),
    )

    assert reparsed is not None
    assert reparsed["product"]["verification_status"] == "verified"
    assert reparsed["product"]["availability_status"] == "in_stock"
    assert reparsed["product"]["region_codes"] == ["CN-SH", "CN-ZJ"]
    assert reparsed["product"]["alternative_skus"] == ["SF-002", "SF-003"]
    assert reparsed["product"]["price_valid_from"].replace(tzinfo=None) == product.price_valid_from
    assert reparsed["product"]["price_valid_to"].replace(tzinfo=None) == product.price_valid_to
