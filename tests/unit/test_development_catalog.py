"""开发商品不冒充商用证据，并保留确定性硬约束。"""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.services import catalog_service, frozen_product_eligibility_service
from app.services.product_eligibility import evaluate_product_eligibility
from tests.unit.test_product_eligibility_contract import (
    BASE_FACTS, BASE_POLICY, NOW, _product,
)


def development_facts(**changes):
    return replace(BASE_FACTS, **{
        "data_origin": "development_fixture", "verification_status": "draft",
        "verified_at": None, "verified_by": None, **changes,
    })


def test_development_policy_allows_only_explicit_fixtures():
    policy = replace(BASE_POLICY, allow_development=True)
    assert evaluate_product_eligibility(development_facts(), policy).eligible
    assert not evaluate_product_eligibility(development_facts(), BASE_POLICY).eligible
    for origin in ("merchant_draft", "public_reference", "unknown"):
        assert not evaluate_product_eligibility(development_facts(data_origin=origin), policy).eligible


@pytest.mark.parametrize(("changes", "reason"), [
    ({"stock_quantity": 0}, "out_of_stock"),
    ({"price_valid_to": None}, "price_validity_unknown"),
    ({"region_codes": ("CN-BJ",)}, "region_unavailable"),
    ({"unit_price": 9000}, "budget_exceeded"),
    ({"dimensions_mm": replace(BASE_FACTS.dimensions_mm, width=None)}, "dimensions_missing"),
    ({"verification_status": "rejected"}, "verification_rejected"),
])
def test_development_policy_preserves_hard_gates(changes, reason):
    result = evaluate_product_eligibility(development_facts(**changes), replace(BASE_POLICY, allow_development=True))
    assert reason in result.reason_codes


def test_development_setting_is_opt_in_and_environment_limited():
    assert not Settings(_env_file=None).development_catalog_enabled
    assert Settings(_env_file=None, app_env="development", development_catalog_enabled=True).development_catalog_enabled
    for environment in ("test", "production"):
        with pytest.raises(ValidationError, match="DEVELOPMENT_CATALOG_ENABLED"):
            Settings(_env_file=None, app_env=environment, development_catalog_enabled=True)


def test_runtime_policy_and_frozen_evidence_are_explicit(monkeypatch):
    product = _product(data_origin="development_fixture", verification_status="draft", verified_at=None, verified_by=None)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "development_catalog_enabled", True)
    assert catalog_service.is_product_eligible(product, at=NOW, region="CN-SH").eligible
    assert not catalog_service.is_product_eligible(product, at=NOW, region="CN-SH", allow_development=False).eligible
    snapshot = catalog_service._eligibility_snapshot(product, checked_at=NOW, region="CN-SH", allow_draft=False, max_unit_price=None, max_dimensions_mm=None, required_quantity=1)
    assert snapshot["policy"]["allowDevelopment"] is True
    suggestion = {key: snapshot[key] for key in ("sku", "quantity", "unitPrice", "dataVersion", "recordVersion")}
    suggestion.update(dataOrigin="development_fixture", sourceName=product.source_name, sourceUrl=product.source_url, verifiedAt=None, dataStatus="draft", catalogEligibility=snapshot)
    with pytest.raises(frozen_product_eligibility_service.FrozenEligibilityError):
        frozen_product_eligibility_service.verify_suggestion(suggestion)
    frozen_product_eligibility_service.verify_suggestion(suggestion, allow_development=True)
    monkeypatch.setattr(settings, "app_env", "production")
    assert not catalog_service.is_product_eligible(product, at=NOW, region="CN-SH").eligible


def test_legacy_snapshot_policy_is_still_strict():
    from app.schemas.product_eligibility import FrozenProductEligibilitySnapshot
    snapshot = catalog_service._eligibility_snapshot(_product(), checked_at=NOW, region="CN-SH", allow_draft=False, max_unit_price=None, max_dimensions_mm=None, required_quantity=1)
    snapshot["policy"].pop("allowDevelopment", None)
    assert not FrozenProductEligibilitySnapshot.model_validate(snapshot).policy.allow_development


def test_development_catalog_runs_quote_flow_but_not_commercial_readiness(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.database import Base
    from evals.trusted_evidence import EvaluationInputError, _frozen_catalog_reasons

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "development_catalog_enabled", True)
    with Session(engine) as db:
        product = _product(data_origin="development_fixture", verification_status="draft", verified_at=None, verified_by=None)
        db.add(product)
        db.flush()
        assert [item.sku for item in catalog_service.eligible_products(db, at=NOW, region="CN-SH")] == [product.sku]
        assert catalog_service.build_catalog_readiness_summary(db, at=NOW, region="CN-SH")["eligible_total"] == 0
        plans = [{"furnitureSuggestions": [{"sku": product.sku, "quantity": 2}]}]
        catalog_service.verify_and_enrich_plans(db, plans, at=NOW, region="CN-SH")
        assert plans[0]["catalogValidation"]["hardErrors"] == []
        assert plans[0]["shopQuote"]["total"] == 10000
        snapshot = plans[0]["furnitureSuggestions"][0]["catalogEligibility"]
        assert snapshot["policy"]["allowDevelopment"] is True
        with pytest.raises(EvaluationInputError):
            _frozen_catalog_reasons(snapshot, run_id=1)
        monkeypatch.setattr(settings, "development_catalog_enabled", False)
        assert catalog_service.eligible_products(db, at=NOW, region="CN-SH") == []
    engine.dispose()
