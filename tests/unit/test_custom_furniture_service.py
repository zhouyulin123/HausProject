from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import CustomQuoteRule
from app.schemas.custom_furniture import CustomFurniturePreviewRequest
from app.services.custom_furniture_service import build_preview


def _cabinet_payload(**overrides):
    payload = {
        "family": "cabinet",
        "name": "主卧定制衣柜",
        "purpose": "wardrobe",
        "material": "E0 颗粒板",
        "dimensions": {
            "width_mm": 1200,
            "height_mm": 2400,
            "depth_mm": 600,
        },
        "structure": {
            "door_style": "hinged",
            "door_count": 3,
            "compartment_count": 3,
            "shelf_count": 4,
            "drawer_count": 2,
            "panel_thickness_mm": 18,
            "leg_height_mm": 80,
        },
    }
    payload.update(overrides)
    return payload


def _table_payload(**overrides):
    payload = {
        "family": "table",
        "name": "六人位餐桌",
        "purpose": "dining_table",
        "material": "实木（橡木）",
        "dimensions": {
            "width_mm": 1600,
            "height_mm": 750,
            "depth_mm": 800,
        },
        "structure": {
            "top_shape": "rectangle",
            "base_style": "four_leg",
            "support_count": 4,
            "seat_count": 6,
            "top_thickness_mm": 36,
            "edge_radius_mm": 12,
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def test_cabinet_preview_is_deterministic_and_recalculates_quote(db):
    db.add(
        CustomQuoteRule(
            project_name="定制衣柜",
            category="柜类定制",
            pricing_unit="㎡",
            material_grade="E0 颗粒板",
            unit_price=680,
            is_active=True,
        )
    )
    db.commit()
    request = CustomFurniturePreviewRequest.model_validate(
        {"spec": _cabinet_payload()}
    )

    first = build_preview(db, request.spec)
    second = build_preview(db, request.spec)

    assert first == second
    assert first.status == "preview_ready"
    assert first.quote_preview.status == "estimated"
    assert first.quote_preview.quantity == Decimal("2.880")
    assert first.quote_preview.estimated_amount == Decimal("1958.40")
    assert first.quote_preview.rule_id is not None
    rule = first.model_spec["确定性建模规则"]
    assert rule["规则状态"] == "ready"
    assert rule["生成器"] == "cabinet_v2"
    assert rule["包围尺寸_mm"] == {"宽": 1200, "高": 2400, "深": 600}
    assert len({part["部件ID"] for part in rule["部件"]}) == len(rule["部件"])


def test_table_without_exact_rule_is_marked_for_human_quote(db):
    request = CustomFurniturePreviewRequest.model_validate(
        {"spec": _table_payload()}
    )

    preview = build_preview(db, request.spec)

    assert preview.status == "needs_human"
    assert preview.quote_preview.status == "needs_human"
    assert preview.quote_preview.reason_code == "quote_rule_missing"
    assert preview.quote_preview.unit_price is None
    assert preview.quote_preview.estimated_amount is None
    assert preview.model_spec["确定性建模规则"]["生成器"] == "table_v2"


def test_custom_preview_applies_regional_cost_factors(db):
    db.add(
        CustomQuoteRule(
            project_name="定制衣柜",
            category="柜类定制",
            pricing_unit="㎡",
            material_grade="E0 颗粒板",
            unit_price=680,
            region_codes=["CN-SH"],
            waste_rate_bps=500,
            minimum_quantity=3,
            installation_fee=300,
            shipping_fee=200,
            tax_rate_bps=600,
            data_version="custom-price-2026-09",
            record_version=2,
            is_active=True,
        )
    )
    db.commit()
    request = CustomFurniturePreviewRequest.model_validate(
        {"spec": _cabinet_payload()}
    )

    outside_region = build_preview(db, request.spec, region="CN-BJ")
    shanghai = build_preview(db, request.spec, region="CN-SH")

    assert outside_region.quote_preview.reason_code == "quote_rule_missing"
    assert shanghai.quote_preview.billable_quantity == Decimal("3.024")
    assert shanghai.quote_preview.base_subtotal == Decimal("2056.32")
    assert shanghai.quote_preview.tax_amount == Decimal("153.38")
    assert shanghai.quote_preview.estimated_amount == Decimal("2709.70")
    assert shanghai.quote_preview.data_version == "custom-price-2026-09"
    assert shanghai.quote_preview.record_version == 2


@pytest.mark.parametrize(
    "spec, expected_fragment",
    [
        (
            _cabinet_payload(
                dimensions={
                    "width_mm": 399,
                    "height_mm": 2400,
                    "depth_mm": 600,
                }
            ),
            "width_mm",
        ),
        (
            _cabinet_payload(
                dimensions={
                    "width_mm": "1200",
                    "height_mm": 2400,
                    "depth_mm": 600,
                }
            ),
            "width_mm",
        ),
        (_cabinet_payload(material="未知板材"), "material"),
        (
            _cabinet_payload(
                structure={
                    "door_style": "open",
                    "door_count": 2,
                    "compartment_count": 3,
                    "shelf_count": 4,
                    "drawer_count": 0,
                    "panel_thickness_mm": 18,
                    "leg_height_mm": 0,
                }
            ),
            "开放式柜体",
        ),
        (
            _table_payload(
                structure={
                    "top_shape": "triangle",
                    "base_style": "four_leg",
                    "support_count": 4,
                    "seat_count": 6,
                    "top_thickness_mm": 36,
                    "edge_radius_mm": 12,
                }
            ),
            "top_shape",
        ),
        (
            _table_payload(
                structure={
                    "top_shape": "rectangle",
                    "base_style": "pedestal",
                    "support_count": 4,
                    "seat_count": 6,
                    "top_thickness_mm": 36,
                    "edge_radius_mm": 12,
                }
            ),
            "pedestal",
        ),
    ],
)
def test_custom_furniture_contract_rejects_invalid_dimensions_material_or_structure(
    spec,
    expected_fragment,
):
    with pytest.raises(ValidationError) as exc_info:
        CustomFurniturePreviewRequest.model_validate({"spec": spec})

    assert expected_fragment in str(exc_info.value)


def test_round_table_requires_equal_width_and_depth():
    payload = _table_payload()
    payload["structure"] = {
        **payload["structure"],
        "top_shape": "round",
        "base_style": "pedestal",
        "support_count": 1,
    }

    with pytest.raises(ValidationError, match="圆桌的宽度和深度必须一致"):
        CustomFurniturePreviewRequest.model_validate({"spec": payload})


def test_duplicate_active_quote_rules_require_human_review(db):
    db.add_all(
        [
            CustomQuoteRule(
                project_name="定制衣柜",
                category="柜类定制",
                pricing_unit="㎡",
                material_grade="E0 颗粒板",
                unit_price=680,
                is_active=True,
            ),
            CustomQuoteRule(
                project_name="定制衣柜",
                category="柜类定制",
                pricing_unit="㎡",
                material_grade="E0 颗粒板",
                unit_price=720,
                is_active=True,
            ),
        ]
    )
    db.commit()
    request = CustomFurniturePreviewRequest.model_validate(
        {"spec": _cabinet_payload()}
    )

    preview = build_preview(db, request.spec)

    assert preview.status == "needs_human"
    assert preview.quote_preview.reason_code == "quote_rule_ambiguous"
    assert preview.quote_preview.estimated_amount is None
