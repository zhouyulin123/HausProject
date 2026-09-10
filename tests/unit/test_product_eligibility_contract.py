from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Product
from app.services import catalog_service
from app.services.product_eligibility import (
    ProductDimensions,
    ProductEligibilityFacts,
    ProductEligibilityPolicy,
    evaluate_product_eligibility,
)
from evals.trusted_evidence import (
    EvaluationInputError,
    _consume_valid_frozen_catalog_line,
    _frozen_catalog_reasons,
)


NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
LIMITS = ProductDimensions(width=2400, depth=1200, height=1200)


def _product(**overrides) -> Product:
    values = {
        "sku": "SOFA-CONTRACT",
        "name": "资格规则契约沙发",
        "category": "沙发",
        "room": "客厅",
        "style": "现代简约",
        "material": "布艺",
        "price": 5000,
        "is_active": True,
        "data_origin": "merchant",
        "source_name": "供应商目录",
        "source_url": "https://supplier.example/products/SOFA-CONTRACT",
        "source_product_id": "SOFA-CONTRACT",
        "source_retrieved_at": NOW - timedelta(hours=2),
        "price_observed_at": NOW - timedelta(hours=1),
        "verification_status": "verified",
        "verified_at": NOW - timedelta(minutes=30),
        "verified_by": "user:7",
        "availability_status": "in_stock",
        "stock_quantity": 5,
        "region_codes": ["CN-SH", "CN-ZJ"],
        "lead_time_days_min": 3,
        "lead_time_days_max": 7,
        "price_valid_from": NOW - timedelta(days=1),
        "price_valid_to": NOW + timedelta(days=1),
        "data_version": "catalog-contract-v1",
        "record_version": 1,
        "model_width_mm": 2200,
        "model_depth_mm": 950,
        "model_height_mm": 800,
    }
    values.update(overrides)
    return Product(**values)


BASE_FACTS = ProductEligibilityFacts(
    is_active=True,
    data_origin="merchant",
    source_name="供应商目录",
    source_url="https://supplier.example/products/SOFA-CONTRACT",
    source_product_id="SOFA-CONTRACT",
    source_retrieved_at=NOW - timedelta(hours=2),
    price_observed_at=NOW - timedelta(hours=1),
    verification_status="verified",
    verified_at=NOW - timedelta(minutes=30),
    verified_by="user:7",
    data_version="catalog-contract-v1",
    availability_status="in_stock",
    stock_quantity=5,
    lead_time_days_min=3,
    lead_time_days_max=7,
    price_valid_from=NOW - timedelta(days=1),
    price_valid_to=NOW + timedelta(days=1),
    region_codes=("CN-SH", "CN-ZJ"),
    dimensions_mm=ProductDimensions(width=2200, depth=950, height=800),
    unit_price=5000,
)
BASE_POLICY = ProductEligibilityPolicy(
    checked_at=NOW,
    region="CN-SH",
    allow_draft=False,
    max_unit_price=8000,
    max_dimensions_mm=LIMITS,
    required_quantity=1,
)


@pytest.mark.parametrize(
    ("facts_changes", "policy_changes", "expected_reason"),
    [
        ({"is_active": False}, {}, "inactive"),
        ({"data_origin": "public_reference"}, {}, "public_reference"),
        ({"data_origin": "verified"}, {}, "provenance_unverified"),
        ({"source_name": None}, {}, "source_name_missing"),
        ({"source_url": None, "source_product_id": None}, {}, "source_reference_missing"),
        ({"source_retrieved_at": None}, {}, "source_retrieved_at_missing"),
        (
            {"source_retrieved_at": NOW + timedelta(seconds=1)},
            {},
            "source_retrieved_at_future",
        ),
        ({"price_observed_at": None}, {}, "price_observed_at_missing"),
        (
            {"price_observed_at": NOW + timedelta(seconds=1)},
            {},
            "price_observed_at_future",
        ),
        ({"verification_status": "draft"}, {}, "verification_required"),
        ({"verified_at": None}, {}, "verified_at_missing"),
        ({"verified_at": NOW + timedelta(seconds=1)}, {}, "verified_at_future"),
        ({"verified_by": None}, {}, "verified_by_missing"),
        ({"data_version": "draft-v2"}, {}, "data_version_unverified"),
        ({"verification_status": "rejected"}, {}, "verification_rejected"),
        ({"verification_status": "expired"}, {}, "verification_expired"),
        ({"verification_status": "unexpected"}, {}, "verification_invalid"),
        ({"availability_status": "out_of_stock"}, {}, "out_of_stock"),
        ({"availability_status": "unknown"}, {}, "availability_unknown"),
        (
            {
                "availability_status": "preorder",
                "lead_time_days_min": None,
                "lead_time_days_max": None,
            },
            {},
            "lead_time_unknown",
        ),
        ({"availability_status": "unexpected"}, {}, "availability_invalid"),
        ({"stock_quantity": 1}, {"required_quantity": 2}, "insufficient_stock"),
        ({"price_valid_from": None}, {}, "price_validity_unknown"),
        (
            {"price_valid_from": NOW + timedelta(seconds=1)},
            {},
            "price_not_started",
        ),
        (
            {"price_valid_to": NOW - timedelta(seconds=1)},
            {},
            "price_expired",
        ),
        ({}, {"region": None}, "region_required"),
        ({}, {"region": "CN-BJ"}, "region_unavailable"),
        ({"region_codes": ()}, {}, "region_unknown"),
        (
            {"dimensions_mm": ProductDimensions(width=None, depth=950, height=800)},
            {},
            "dimensions_missing",
        ),
        (
            {"dimensions_mm": ProductDimensions(width=2600, depth=950, height=800)},
            {},
            "dimensions_exceeded",
        ),
        ({"unit_price": 9000}, {}, "budget_exceeded"),
    ],
)
def test_pure_product_eligibility_rule_covers_each_reason_code(
    facts_changes,
    policy_changes,
    expected_reason,
):
    facts = ProductEligibilityFacts(**{**BASE_FACTS.__dict__, **facts_changes})
    policy = ProductEligibilityPolicy(**{**BASE_POLICY.__dict__, **policy_changes})

    result = evaluate_product_eligibility(facts, policy)

    assert result.reason_codes == (expected_reason,)


@pytest.mark.parametrize(
    ("product_overrides", "call_overrides"),
    [
        ({"is_active": False}, {}),
        ({"data_origin": "public_reference"}, {}),
        ({"data_origin": "verified"}, {}),
        ({"source_name": None}, {}),
        ({"source_url": None, "source_product_id": None}, {}),
        ({"source_retrieved_at": None}, {}),
        ({"source_retrieved_at": NOW + timedelta(seconds=1)}, {}),
        ({"price_observed_at": None}, {}),
        ({"price_observed_at": NOW + timedelta(seconds=1)}, {}),
        ({"verification_status": "draft"}, {}),
        ({"verified_at": None}, {}),
        ({"verified_at": NOW + timedelta(seconds=1)}, {}),
        ({"verified_by": None}, {}),
        ({"data_version": "draft-v2"}, {}),
        ({"verification_status": "rejected"}, {}),
        ({"verification_status": "expired"}, {}),
        ({"verification_status": "unexpected"}, {}),
        ({"availability_status": "out_of_stock"}, {}),
        ({"availability_status": "unknown"}, {}),
        (
            {
                "availability_status": "preorder",
                "lead_time_days_min": None,
                "lead_time_days_max": None,
            },
            {},
        ),
        ({"availability_status": "unexpected"}, {}),
        ({"stock_quantity": 1}, {"required_quantity": 2}),
        ({"price_valid_from": None}, {}),
        ({"price_valid_from": NOW + timedelta(seconds=1)}, {}),
        ({"price_valid_to": NOW - timedelta(seconds=1)}, {}),
        ({}, {"region": None}),
        ({}, {"region": "CN-BJ"}),
        ({"region_codes": []}, {}),
        ({"model_width_mm": None}, {}),
        ({"model_width_mm": 2600}, {}),
        ({"price": 9000}, {}),
    ],
)
def test_online_and_frozen_adapters_recompute_identical_reason_codes(
    product_overrides,
    call_overrides,
):
    product = _product(**product_overrides)
    options = {
        "at": NOW,
        "region": "CN-SH",
        "allow_draft": False,
        "max_unit_price": 8000,
        "max_dimensions_mm": {"width": 2400, "depth": 1200, "height": 1200},
        "required_quantity": 1,
        **call_overrides,
    }
    online = catalog_service.is_product_eligible(product, **options)
    snapshot = catalog_service._eligibility_snapshot(
        product,
        checked_at=options["at"],
        region=options["region"],
        allow_draft=options["allow_draft"],
        max_unit_price=options["max_unit_price"],
        max_dimensions_mm=options["max_dimensions_mm"],
        required_quantity=options["required_quantity"],
    )

    frozen_reasons = _frozen_catalog_reasons(snapshot, run_id=7)

    assert frozen_reasons == online.reason_codes


def test_frozen_snapshot_contains_all_commercial_verification_facts():
    snapshot = catalog_service._eligibility_snapshot(
        _product(),
        checked_at=NOW,
        region="CN-SH",
        allow_draft=False,
        max_unit_price=None,
        max_dimensions_mm=None,
        required_quantity=1,
    )

    assert snapshot["schemaVersion"] == "1.1"
    assert {
        key: snapshot["facts"][key]
        for key in (
            "sourceName",
            "sourceUrl",
            "sourceProductId",
            "sourceRetrievedAt",
            "priceObservedAt",
            "verifiedAt",
            "verifiedBy",
            "dataVersion",
        )
    } == {
        "sourceName": "供应商目录",
        "sourceUrl": "https://supplier.example/products/SOFA-CONTRACT",
        "sourceProductId": "SOFA-CONTRACT",
        "sourceRetrievedAt": (NOW - timedelta(hours=2)).isoformat(),
        "priceObservedAt": (NOW - timedelta(hours=1)).isoformat(),
        "verifiedAt": (NOW - timedelta(minutes=30)).isoformat(),
        "verifiedBy": "user:7",
        "dataVersion": "catalog-contract-v1",
    }


def test_legacy_frozen_snapshot_version_is_not_silently_reinterpreted():
    snapshot = catalog_service._eligibility_snapshot(
        _product(),
        checked_at=NOW,
        region="CN-SH",
        allow_draft=False,
        max_unit_price=None,
        max_dimensions_mm=None,
        required_quantity=1,
    )
    snapshot["schemaVersion"] = "1.0"

    with pytest.raises(EvaluationInputError, match="版本不受支持"):
        _consume_valid_frozen_catalog_line(
            {"catalogEligibility": snapshot},
            quote_lines=[],
            run_id=7,
        )


def test_explicit_draft_policy_does_not_require_fabricated_verification_audit():
    draft = ProductEligibilityFacts(
        **{
            **BASE_FACTS.__dict__,
            "data_origin": "merchant_draft",
            "verification_status": "draft",
            "verified_at": None,
            "verified_by": None,
            "data_version": "draft-v2",
        }
    )
    policy = ProductEligibilityPolicy(**{**BASE_POLICY.__dict__, "allow_draft": True})

    assert evaluate_product_eligibility(draft, policy).reason_codes == ()
    missing_version = ProductEligibilityFacts(
        **{**draft.__dict__, "data_version": None}
    )
    assert evaluate_product_eligibility(missing_version, policy).reason_codes == (
        "data_version_unverified",
    )


def test_verified_product_requires_audit_even_when_drafts_are_allowed():
    invalid_verified = ProductEligibilityFacts(
        **{
            **BASE_FACTS.__dict__,
            "verified_at": None,
            "verified_by": None,
            "data_version": "draft-v2",
        }
    )
    policy = ProductEligibilityPolicy(**{**BASE_POLICY.__dict__, "allow_draft": True})

    assert evaluate_product_eligibility(invalid_verified, policy).reason_codes == (
        "verified_at_missing",
        "verified_by_missing",
        "data_version_unverified",
    )
