from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Product
from app.schemas.design_agent import AgentFactsPatch
from app.services.design_agent_service import _catalog_tool


NOW = datetime.now(timezone.utc)


def test_agent_facts_accept_and_normalize_explicit_material_preferences():
    facts = AgentFactsPatch(
        preferred_materials=[" 实木 ", "棉麻", "实木"],
    )

    assert facts.preferred_materials == ["实木", "棉麻"]


def _product(
    sku: str,
    *,
    style: str,
    material: str,
    price: int,
) -> Product:
    return Product(
        sku=sku,
        name=f"商品 {sku}",
        category="沙发",
        room="客厅",
        style=style,
        material=material,
        price=price,
        is_active=True,
        data_origin="merchant",
        verification_status="verified",
        availability_status="in_stock",
        stock_quantity=10,
        region_codes=["CN-SH"],
        price_valid_from=NOW - timedelta(days=1),
        price_valid_to=NOW + timedelta(days=1),
        verified_at=NOW - timedelta(days=1),
        verified_by="factory:7",
        data_version="catalog-test-v1",
        record_version=1,
        model_width_mm=2000,
        model_height_mm=800,
        model_depth_mm=900,
    )


def test_catalog_tool_ranks_explicit_preferences_before_limit_with_reasons():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        db.add_all(
            [
                _product(
                    f"CHEAP-{index:02d}",
                    style="工业风",
                    material="金属",
                    price=1000 + index,
                )
                for index in range(21)
            ]
        )
        db.add(
            _product(
                "PREFERRED-01",
                style="现代简约",
                material="白橡木实木",
                price=9000,
            )
        )
        db.commit()

        result = _catalog_tool(db)(
            {
                "facts": {
                    "delivery_region": "CN-SH",
                    "budget_max": 10000,
                    "room_width_m": 5,
                    "room_depth_m": 4,
                    "space_type": "客厅",
                    "style": "现代简约",
                    "preferred_materials": ["实木"],
                }
            }
        )

    assert result["candidate_count"] == 22
    assert len(result["products"]) == 20
    assert result["products"][0]["sku"] == "PREFERRED-01"
    assert result["products"][0]["ranking_reasons"] == [
        {
            "code": "style_preference_match",
            "preference": "现代简约",
            "value": "现代简约",
        },
        {
            "code": "material_preference_match",
            "preference": "实木",
            "value": "白橡木实木",
        },
    ]
    assert "matchScore" not in result["products"][0]


def test_catalog_tool_keeps_price_order_when_no_preference_is_provided():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        db.add_all(
            [
                _product("HIGH", style="现代简约", material="实木", price=5000),
                _product("LOW", style="工业风", material="金属", price=3000),
            ]
        )
        db.commit()

        result = _catalog_tool(db)(
            {
                "facts": {
                    "delivery_region": "CN-SH",
                    "budget_max": 10000,
                    "room_width_m": 5,
                    "room_depth_m": 4,
                    "space_type": "客厅",
                }
            }
        )

    assert [product["sku"] for product in result["products"]] == ["LOW", "HIGH"]
    assert all(not product["ranking_reasons"] for product in result["products"])
