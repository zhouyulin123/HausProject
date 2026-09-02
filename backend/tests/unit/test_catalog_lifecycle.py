from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import CustomQuoteRule, Product
from app.services.catalog_service import (
    build_catalog_context,
    find_product_alternatives,
    is_product_eligible,
    verify_and_enrich_plans,
)


NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


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
        "verification_status": "verified",
        "availability_status": "in_stock",
        "stock_quantity": 5,
        "region_codes": ["CN-SH", "CN-ZJ"],
        "lead_time_days_min": 3,
        "lead_time_days_max": 7,
        "price_valid_from": NOW - timedelta(days=1),
        "price_valid_to": NOW + timedelta(days=1),
        "verified_at": NOW - timedelta(days=1),
        "verified_by": "factory:7",
        "data_version": "catalog-2026-09-01",
        "record_version": 2,
        "alternative_skus": [],
        "model_width_mm": 2200,
        "model_height_mm": 800,
        "model_depth_mm": 950,
    }
    values.update(overrides)
    return Product(**values)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"verification_status": "draft"}, "verification_required"),
        ({"verification_status": "rejected"}, "verification_rejected"),
        ({"verification_status": "expired"}, "verification_expired"),
        ({"data_origin": "public_reference"}, "public_reference"),
        ({"availability_status": "out_of_stock", "stock_quantity": 0}, "out_of_stock"),
        ({"availability_status": "unknown"}, "availability_unknown"),
        ({"price_valid_from": NOW + timedelta(seconds=1)}, "price_not_started"),
        ({"price_valid_to": NOW - timedelta(seconds=1)}, "price_expired"),
        ({"region_codes": ["CN-BJ"]}, "region_unavailable"),
        ({"model_width_mm": None}, "dimensions_missing"),
        ({"model_width_mm": 2600}, "dimensions_exceeded"),
        ({"price": 9000}, "budget_exceeded"),
    ],
)
def test_product_eligibility_returns_structured_hard_failure(overrides, reason):
    result = is_product_eligible(
        _product("P-001", **overrides),
        at=NOW,
        region="CN-SH",
        max_unit_price=8000,
        max_dimensions_mm={"width": 2400, "depth": 1200, "height": 1200},
    )

    assert result.eligible is False
    assert reason in result.reason_codes


def test_price_validity_boundaries_are_inclusive_and_draft_needs_explicit_override():
    product = _product("P-001", price_valid_from=NOW, price_valid_to=NOW)
    assert is_product_eligible(product, at=NOW, region="CN-SH").eligible

    draft = _product("P-002", verification_status="draft", data_origin="merchant_draft")
    assert not is_product_eligible(draft, at=NOW, region="CN-SH").eligible
    assert is_product_eligible(
        draft,
        at=NOW,
        region="CN-SH",
        allow_draft=True,
    ).eligible


def test_region_specific_product_requires_explicit_region_context():
    regional = _product("P-REGIONAL")
    global_product = _product("P-GLOBAL", region_codes=["*"])

    result = is_product_eligible(regional, at=NOW)

    assert result.eligible is False
    assert "region_required" in result.reason_codes
    assert is_product_eligible(global_product, at=NOW).eligible


def test_catalog_context_only_contains_current_eligible_products(db):
    verified = _product("GOOD-001")
    draft = _product("DRAFT-001", verification_status="draft", data_origin="merchant_draft")
    reference = _product("REF-001", data_origin="public_reference")
    db.add_all([verified, draft, reference])
    db.commit()

    context = build_catalog_context(db, at=NOW, region="CN-SH")

    assert "GOOD-001" in context
    assert "DRAFT-001" not in context
    assert "REF-001" not in context


def test_alternatives_are_deterministic_and_include_reason_codes(db):
    source = _product(
        "SOFA-OLD",
        availability_status="out_of_stock",
        stock_quantity=0,
        alternative_skus=["SOFA-EXPLICIT"],
    )
    explicit = _product("SOFA-EXPLICIT", price=5200)
    closest = _product("SOFA-CLOSE", price=4900)
    wrong_room = _product("SOFA-WRONG", room="卧室", price=5000)
    too_wide = _product("SOFA-WIDE", price=4800, model_width_mm=2800)
    db.add_all([source, explicit, closest, wrong_room, too_wide])
    db.commit()

    alternatives = find_product_alternatives(
        db,
        source,
        at=NOW,
        region="CN-SH",
        max_unit_price=5500,
        max_dimensions_mm={"width": 2400, "depth": 1200, "height": 1200},
    )

    assert [item["sku"] for item in alternatives] == [
        "SOFA-EXPLICIT",
        "SOFA-CLOSE",
        "SOFA-WRONG",
    ]
    assert "explicit_alternative" in alternatives[0]["reason_codes"]
    assert "same_room" in alternatives[1]["reason_codes"]
    assert "SOFA-WIDE" not in {item["sku"] for item in alternatives}


def test_alternative_does_not_claim_dimensions_fit_without_size_constraint(db):
    source = _product(
        "SOFA-OLD",
        availability_status="out_of_stock",
        stock_quantity=0,
    )
    candidate = _product("SOFA-NEW")
    db.add_all([source, candidate])
    db.commit()

    alternative = find_product_alternatives(
        db,
        source,
        at=NOW,
        region="CN-SH",
        limit=1,
    )[0]

    assert "dimensions_fit" not in alternative["reason_codes"]
    assert "dimensions_known" in alternative["reason_codes"]


def test_alternatives_require_enough_stock_for_requested_quantity(db):
    source = _product("SOFA-OLD", stock_quantity=1)
    insufficient = _product("SOFA-LOW", stock_quantity=2)
    sufficient = _product("SOFA-ENOUGH", stock_quantity=3)
    db.add_all([source, insufficient, sufficient])
    db.commit()

    alternatives = find_product_alternatives(
        db,
        source,
        at=NOW,
        region="CN-SH",
        required_quantity=3,
    )

    assert [item["sku"] for item in alternatives] == ["SOFA-ENOUGH"]
    assert "stock_sufficient" in alternatives[0]["reason_codes"]


def test_enrichment_replaces_unavailable_sku_and_records_versioned_quote(db):
    unavailable = _product(
        "SOFA-OLD",
        availability_status="out_of_stock",
        stock_quantity=0,
        alternative_skus=["SOFA-NEW"],
    )
    replacement = _product("SOFA-NEW", price=4800, data_version="catalog-v8", record_version=4)
    db.add_all([unavailable, replacement])
    db.commit()
    plans = [{
        "id": "plan-a",
        "style": "现代简约",
        "furnitureSuggestions": [{"sku": "SOFA-OLD", "quantity": 2}],
        "customItems": [],
    }]

    verify_and_enrich_plans(db, plans, at=NOW, region="CN-SH")

    item = plans[0]["furnitureSuggestions"][0]
    quote = plans[0]["shopQuote"]
    assert item["sku"] == "SOFA-NEW"
    assert item["replacedSku"] == "SOFA-OLD"
    assert "explicit_alternative" in item["replacementReasonCodes"]
    assert item["dataVersion"] == "catalog-v8"
    assert item["recordVersion"] == 4
    assert quote["furnitureTotal"] == 9600
    assert quote["lineItems"][0]["unitPrice"] == 4800
    assert quote["catalogVersion"]
    assert quote["priceVersion"]


def test_enrichment_replaces_product_with_insufficient_requested_stock(db):
    source = _product(
        "SOFA-LOW",
        stock_quantity=1,
        alternative_skus=["SOFA-ENOUGH"],
    )
    replacement = _product("SOFA-ENOUGH", stock_quantity=3, price=4800)
    db.add_all([source, replacement])
    db.commit()
    plans = [{
        "id": "plan-a",
        "furnitureSuggestions": [{"sku": "SOFA-LOW", "quantity": 3}],
        "customItems": [],
    }]

    verify_and_enrich_plans(db, plans, at=NOW, region="CN-SH")

    item = plans[0]["furnitureSuggestions"][0]
    assert item["sku"] == "SOFA-ENOUGH"
    assert item["replacedSku"] == "SOFA-LOW"
    assert "stock_sufficient" in item["replacementReasonCodes"]
    assert plans[0]["catalogValidation"]["hardErrors"] == []
    assert plans[0]["shopQuote"]["furnitureTotal"] == 14400


def test_enrichment_blocks_when_source_and_alternatives_have_insufficient_stock(db):
    source = _product(
        "SOFA-LOW",
        stock_quantity=1,
        alternative_skus=["SOFA-STILL-LOW"],
    )
    insufficient = _product("SOFA-STILL-LOW", stock_quantity=2)
    db.add_all([source, insufficient])
    db.commit()
    plans = [{
        "id": "plan-a",
        "furnitureSuggestions": [{"sku": "SOFA-LOW", "quantity": 3}],
        "customItems": [],
    }]

    verify_and_enrich_plans(db, plans, at=NOW, region="CN-SH")

    validation = plans[0]["catalogValidation"]
    assert validation["quoteStatus"] == "blocked"
    assert "insufficient_stock" in validation["hardErrors"]
    assert validation["rejected"][0]["sku"] == "SOFA-LOW"
    assert "insufficient_stock" in validation["rejected"][0]["reason_codes"]
    assert "shopQuote" not in plans[0]


@pytest.mark.parametrize("invalid_quantity", [None, 0, -2, "not-a-number"])
def test_enrichment_normalizes_invalid_quantity_before_stock_gate(
    db,
    invalid_quantity,
):
    db.add(_product("SOFA-ONE", stock_quantity=1))
    db.commit()
    plans = [{
        "id": "plan-a",
        "furnitureSuggestions": [{
            "sku": "SOFA-ONE",
            "quantity": invalid_quantity,
        }],
        "customItems": [],
    }]

    verify_and_enrich_plans(db, plans, at=NOW, region="CN-SH")

    assert plans[0]["catalogValidation"]["hardErrors"] == []
    assert plans[0]["furnitureSuggestions"][0]["quantity"] == 1
    assert plans[0]["shopQuote"]["lineItems"][0]["quantity"] == 1


def test_enrichment_replaces_item_to_fit_remaining_total_budget(db):
    first = _product("SOFA-FIRST", price=6000)
    second = _product(
        "SOFA-SECOND",
        price=5000,
        alternative_skus=["SOFA-TOO-MUCH", "SOFA-BUDGET"],
    )
    per_unit_too_expensive = _product("SOFA-TOO-MUCH", price=3000)
    budget_alternative = _product("SOFA-BUDGET", price=1900)
    db.add_all([first, second, per_unit_too_expensive, budget_alternative])
    db.commit()
    plans = [{
        "id": "plan-a",
        "furnitureSuggestions": [
            {"sku": "SOFA-FIRST", "quantity": 1},
            {"sku": "SOFA-SECOND", "quantity": 2},
        ],
        "customItems": [],
    }]

    verify_and_enrich_plans(
        db,
        plans,
        at=NOW,
        region="CN-SH",
        budget_max=10000,
    )

    items = plans[0]["furnitureSuggestions"]
    assert [item["sku"] for item in items] == ["SOFA-FIRST", "SOFA-BUDGET"]
    assert items[1]["replacedSku"] == "SOFA-SECOND"
    assert "budget_fit" in items[1]["replacementReasonCodes"]
    assert plans[0]["catalogValidation"]["hardErrors"] == []
    assert plans[0]["shopQuote"]["furnitureTotal"] == 9800


def test_enrichment_blocks_quote_when_total_budget_has_no_legal_alternative(db):
    first = _product("SOFA-FIRST", price=6000)
    second = _product("SOFA-SECOND", price=5000)
    db.add_all([first, second])
    db.commit()
    plans = [{
        "id": "plan-a",
        "furnitureSuggestions": [
            {"sku": "SOFA-FIRST", "quantity": 1},
            {"sku": "SOFA-SECOND", "quantity": 1},
        ],
        "customItems": [],
    }]

    verify_and_enrich_plans(
        db,
        plans,
        at=NOW,
        region="CN-SH",
        budget_max=10000,
    )

    validation = plans[0]["catalogValidation"]
    assert validation["quoteStatus"] == "blocked"
    assert "budget_exceeded" in validation["hardErrors"]
    assert validation["rejected"] == [{
        "sku": "SOFA-SECOND",
        "reason_codes": ["budget_exceeded"],
    }]
    assert "shopQuote" not in plans[0]


def test_enrichment_rejects_plan_without_sku_instead_of_style_fallback(db):
    db.add(_product("SOFA-AVAILABLE"))
    db.commit()
    plans = [{"id": "plan-a", "style": "现代简约", "customItems": []}]

    verify_and_enrich_plans(db, plans, at=NOW, region="CN-SH")

    assert plans[0]["furnitureSuggestions"] == []
    assert "missing_product_sku" in plans[0]["catalogValidation"]["hardErrors"]
    assert plans[0]["catalogValidation"]["quoteStatus"] == "blocked"
    assert "shopQuote" not in plans[0]


def test_custom_quote_rule_requires_exact_project_and_grade(db):
    db.add_all([
        _product("SOFA-001"),
        CustomQuoteRule(
            project_name="定制衣柜",
            material_grade="E0 实木多层板",
            pricing_unit="㎡",
            unit_price=1280,
            is_active=True,
        ),
    ])
    db.commit()
    plans = [{
        "id": "plan-a",
        "furnitureSuggestions": [{"sku": "SOFA-001"}],
        "customItems": [{
            "project": "衣柜",
            "grade": "E0 实木多层板",
            "quantity": 3,
        }],
    }]

    verify_and_enrich_plans(db, plans, at=NOW, region="CN-SH")

    validation = plans[0]["catalogValidation"]
    assert plans[0]["customItems"] == []
    assert "custom_quote_rule_missing" in validation["hardErrors"]
    assert validation["customRuleErrors"][0]["reason_code"] == (
        "custom_quote_rule_missing"
    )


def test_custom_quote_rule_exact_unique_match_is_priced(db):
    rule = CustomQuoteRule(
        project_name="定制衣柜",
        material_grade="E0 实木多层板",
        pricing_unit="㎡",
        unit_price=1280,
        is_active=True,
    )
    db.add_all([_product("SOFA-001"), rule])
    db.commit()
    plans = [{
        "id": "plan-a",
        "furnitureSuggestions": [{"sku": "SOFA-001"}],
        "customItems": [{
            "project": "定制衣柜",
            "grade": "E0 实木多层板",
            "quantity": 3,
        }],
    }]

    verify_and_enrich_plans(db, plans, at=NOW, region="CN-SH")

    assert plans[0]["catalogValidation"]["hardErrors"] == []
    assert plans[0]["customItems"][0]["ruleId"] == rule.id
    assert plans[0]["shopQuote"]["customTotal"] == 3840


def test_custom_quote_rule_must_be_unique(db):
    rules = [
        CustomQuoteRule(
            project_name="定制衣柜",
            material_grade="E0 实木多层板",
            pricing_unit="㎡",
            unit_price=price,
            is_active=True,
        )
        for price in (1280, 1380)
    ]
    db.add_all([_product("SOFA-001"), *rules])
    db.commit()
    plans = [{
        "id": "plan-a",
        "furnitureSuggestions": [{"sku": "SOFA-001"}],
        "customItems": [{
            "project": "定制衣柜",
            "grade": "E0 实木多层板",
            "quantity": 3,
        }],
    }]

    verify_and_enrich_plans(db, plans, at=NOW, region="CN-SH")

    validation = plans[0]["catalogValidation"]
    assert plans[0]["customItems"] == []
    assert "custom_quote_rule_ambiguous" in validation["hardErrors"]
    assert validation["customRuleErrors"][0]["matching_rule_ids"] == [
        rules[0].id,
        rules[1].id,
    ]


def test_custom_quote_includes_region_waste_minimum_fees_and_tax(db):
    rule = CustomQuoteRule(
        project_name="定制衣柜",
        material_grade="E0 实木多层板",
        pricing_unit="㎡",
        unit_price=1280,
        region_codes=["CN-SH"],
        waste_rate_bps=500,
        minimum_quantity=3,
        installation_fee=300,
        shipping_fee=200,
        tax_rate_bps=600,
        data_version="custom-price-2026-09",
        record_version=4,
        is_active=True,
    )
    db.add_all([_product("SOFA-001"), rule])
    db.commit()
    plans = [{
        "id": "plan-a",
        "furnitureSuggestions": [{"sku": "SOFA-001"}],
        "customItems": [{
            "project": "定制衣柜",
            "grade": "E0 实木多层板",
            "quantity": 2,
        }],
    }]

    verify_and_enrich_plans(db, plans, at=NOW, region="CN-SH")

    custom = plans[0]["customItems"][0]
    line = plans[0]["shopQuote"]["customLineItems"][0]
    assert custom["requestedQuantity"] == 2
    assert custom["billableQuantity"] == 3
    assert custom["baseSubtotal"] == 3840
    assert custom["taxAmount"] == 260
    assert custom["subtotal"] == 4600
    assert line["subtotal"] == 4600
    assert line["dataVersion"] == "custom-price-2026-09"
    assert line["recordVersion"] == 4
    assert plans[0]["shopQuote"]["customTotal"] == 4600


def test_custom_quote_rejects_rule_outside_delivery_region(db):
    db.add_all([
        _product("SOFA-001"),
        CustomQuoteRule(
            project_name="定制衣柜",
            material_grade="E0 实木多层板",
            pricing_unit="㎡",
            unit_price=1280,
            region_codes=["CN-SH"],
            is_active=True,
        ),
    ])
    db.commit()
    plans = [{
        "id": "plan-a",
        "furnitureSuggestions": [{"sku": "SOFA-001"}],
        "customItems": [{
            "project": "定制衣柜",
            "grade": "E0 实木多层板",
            "quantity": 3,
        }],
    }]

    verify_and_enrich_plans(db, plans, at=NOW, region="CN-BJ")

    assert plans[0]["catalogValidation"]["quoteStatus"] == "blocked"
    assert "custom_quote_rule_missing" in plans[0]["catalogValidation"]["hardErrors"]
    assert "shopQuote" not in plans[0]
