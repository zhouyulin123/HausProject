from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.db.models import CustomQuoteRule
from app.services import catalog_service, custom_quote_evidence_service


def _evidence() -> dict:
    return {
        "schemaVersion": "1.0",
        "checkedAt": "2026-09-01T00:00:00+00:00",
        "region": "CN-SH",
        "isActive": True,
        "ruleId": 7,
        "dataVersion": "custom-price-v4",
        "recordVersion": 4,
        "project": "定制衣柜",
        "grade": "E0 实木多层板",
        "pricingUnit": "㎡",
        "unitPrice": 1280,
        "ruleRegionCodes": ["CN-SH"],
        "requestedQuantity": 2.0,
        "billableQuantity": 3.0,
        "wasteRateBps": 500,
        "minimumQuantity": 3.0,
        "baseSubtotal": 3840,
        "installationFee": 300,
        "shippingFee": 200,
        "taxRateBps": 600,
        "taxAmount": 260,
        "subtotal": 4600,
    }


@pytest.mark.unit
def test_custom_quote_evidence_recomputes_frozen_rule_without_database():
    verified = custom_quote_evidence_service.verify_evidence(
        _evidence(),
        expected_region="CN-SH",
    )

    assert verified.subtotal == 4600
    assert verified.rule_id == 7
    assert verified.data_version == "custom-price-v4"
    assert verified.record_version == 4


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("installationFee",), 301, "custom_rule_evidence_inconsistent"),
        (("region",), "CN-BJ", "custom_rule_policy_mismatch"),
        (("recordVersion",), 0, "custom_rule_evidence_invalid"),
        (("unitPrice",), "1280", "custom_rule_evidence_invalid"),
        (("isActive",), False, "custom_rule_inactive"),
    ],
)
def test_custom_quote_evidence_fails_closed_on_tampering(path, value, reason):
    evidence = deepcopy(_evidence())
    evidence[path[0]] = value

    with pytest.raises(custom_quote_evidence_service.CustomRuleEvidenceError) as exc:
        custom_quote_evidence_service.verify_evidence(
            evidence,
            expected_region="CN-SH",
        )

    assert exc.value.code == reason


@pytest.mark.unit
def test_custom_quote_evidence_binds_quote_priced_at():
    with pytest.raises(custom_quote_evidence_service.CustomRuleEvidenceError) as exc:
        custom_quote_evidence_service.verify_evidence(
            _evidence(),
            expected_region="CN-SH",
            expected_priced_at="2026-09-01T00:00:01+00:00",
        )

    assert exc.value.code == "custom_rule_policy_mismatch"


@pytest.mark.unit
def test_custom_quote_money_uses_the_same_frozen_quantity_as_evidence():
    rule = CustomQuoteRule(
        id=7,
        project_name="定制柜体",
        material_grade="E0",
        pricing_unit="㎡",
        unit_price=1280,
        waste_rate_bps=500,
        minimum_quantity=0,
        installation_fee=300,
        shipping_fee=200,
        tax_rate_bps=600,
        region_codes=["CN-SH"],
        is_active=True,
        data_version="custom-price-v4",
        record_version=4,
    )
    priced_at = datetime(2026, 9, 1, tzinfo=timezone.utc)

    calculation = catalog_service.calculate_custom_quote(rule, 2.3456)
    evidence = custom_quote_evidence_service.build_evidence(
        rule,
        calculation,
        checked_at=priced_at,
        region="CN-SH",
    )

    verified = custom_quote_evidence_service.verify_evidence(
        evidence,
        expected_region="CN-SH",
        expected_priced_at=priced_at,
    )
    assert verified.requested_quantity == 2.346
    assert verified.subtotal == calculation["subtotal"]


@pytest.mark.unit
def test_frozen_product_evidence_rejects_coerced_text_fields():
    from app.schemas.product_eligibility import FrozenProductEligibilitySnapshot
    from tests.real_world_fixtures import frozen_catalog_suggestion

    evidence = frozen_catalog_suggestion()["catalogEligibility"]
    evidence["facts"]["sourceName"] = 123

    with pytest.raises(ValidationError):
        FrozenProductEligibilitySnapshot.model_validate(evidence)
