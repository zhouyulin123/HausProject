import hashlib
import hmac
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from app.db.database import Base
from app.db.models import DesignPlanVersion, DesignTask
from app.services.design_version_service import persist_generation
from app.services.plan_traceability_audit_service import (
    PlanTraceabilityCohortError,
    audit_plan_snapshot,
    audit_plan_traceability,
    load_plan_traceability_cohort,
)
from tests.real_world_fixtures import (
    frozen_catalog_quote_line,
    frozen_catalog_suggestion,
    frozen_custom_quote,
)


SIGNING_KEY = "traceability-cohort-signing-key-at-least-32-bytes"
KEY_ID = "traceability-cohort-v1"
ENVIRONMENT = "production-cn"


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def _traceable_plan(index: int) -> dict:
    sku = f"SKU-{index:03d}"
    unit_price = 1000 + index
    suggestion = frozen_catalog_suggestion(
        sku=sku,
        unit_price=unit_price,
        data_version="catalog-2026-q3",
        record_version=2,
    )
    suggestion.update(
        {
            "name": f"商品 {index}",
            "subtotal": unit_price,
            "dataStatus": "verified",
        }
    )
    return {
        "id": f"plan-{index:03d}",
        "name": f"可追溯方案 {index}",
        "style": "现代简约",
        "furnitureSuggestions": [suggestion],
        "customItems": [],
        "shopQuote": {
            "furnitureTotal": unit_price,
            "customTotal": 0,
            "total": unit_price,
            "catalogVersion": "catalog-2026-q3",
            "priceVersion": "prices:sha256-valid",
            "ruleVersion": "rules:sha256-valid",
            "pricedAt": "2026-09-02T00:00:00+00:00",
            "lineItems": [frozen_catalog_quote_line(suggestion)],
            "customLineItems": [],
        },
    }


def _persist_plans(db, count: int) -> list[DesignPlanVersion]:
    task = DesignTask(status="completed", confirmed_requirement_json={})
    db.add(task)
    db.commit()
    revision = persist_generation(
        db,
        task=task,
        plans=[_traceable_plan(index) for index in range(count)],
        generator="llm",
    )
    db.commit()
    return list(revision.plans)


def test_development_snapshot_requires_explicit_audit_policy(db):
    plan = _persist_plans(db, 1)[0]
    product = plan.plan_json["furnitureSuggestions"][0]
    product.update(dataOrigin="development_fixture", dataStatus="draft", verifiedAt=None)
    evidence = product["catalogEligibility"]
    evidence["policy"]["allowDevelopment"] = True
    evidence["facts"].update(dataOrigin="development_fixture", verificationStatus="draft", verifiedAt=None, verifiedBy=None)

    assert not audit_plan_snapshot(plan).passed
    assert audit_plan_snapshot(plan, allow_development=True).passed
    evidence["facts"]["stockQuantity"] = 0
    assert not audit_plan_snapshot(plan, allow_development=True).passed


def test_development_delivery_uses_server_policy_without_relaxing_formal_audit(db, monkeypatch):
    from datetime import datetime, timezone
    from app.core.config import settings
    from app.services.plan_delivery_service import require_deliverable, PlanDeliveryBlocked

    plan = _persist_plans(db, 1)[0]
    product = plan.plan_json["furnitureSuggestions"][0]
    product.update(dataOrigin="development_fixture", dataStatus="draft", verifiedAt=None)
    product["catalogEligibility"]["policy"]["allowDevelopment"] = True
    product["catalogEligibility"]["facts"].update(dataOrigin="development_fixture", verificationStatus="draft", verifiedAt=None, verifiedBy=None)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "development_catalog_enabled", True)
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    delivery = require_deliverable(plan, now=now)
    assert delivery.delivery_mode == "development_preview"
    assert not audit_plan_snapshot(plan).passed
    monkeypatch.setattr(settings, "development_catalog_enabled", False)
    with pytest.raises(PlanDeliveryBlocked):
        require_deliverable(plan, now=now)


def _write_cohort(tmp_path, plans, **overrides):
    payload = {
        "schema_version": "1.0",
        "cohort_kind": "production_acceptance",
        "cohort_id": "prod-acceptance-2026-w36",
        "cutover_id": "release-2026-w36",
        "environment": ENVIRONMENT,
        "issued_at": "2026-09-08T00:00:00+00:00",
        "members": [
            {"task_id": plan.revision.task_id, "plan_version_id": plan.id}
            for plan in plans
        ],
    }
    payload.update(overrides)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["attestation"] = {
        "algorithm": "hmac-sha256",
        "key_id": KEY_ID,
        "signature": hmac.new(
            SIGNING_KEY.encode("utf-8"), canonical, hashlib.sha256
        ).hexdigest(),
    }
    path = tmp_path / "traceability-cohort.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _load_cohort(tmp_path, plans, **overrides):
    return load_plan_traceability_cohort(
        _write_cohort(tmp_path, plans, **overrides),
        expected_environment=ENVIRONMENT,
        verification_keys={KEY_ID: SIGNING_KEY},
    )


@pytest.mark.unit
def test_traceability_audit_uses_only_explicit_signed_production_cohort(db, tmp_path):
    demo = _persist_plans(db, 1)[0]
    production = _persist_plans(db, 21)
    cohort = _load_cohort(tmp_path, production)

    first = audit_plan_traceability(db, cohort=cohort, sample_size=20)
    second = audit_plan_traceability(db, cohort=cohort, sample_size=20)

    assert first.passed is True
    assert first.schema_version == "2.0"
    assert first.eligible_member_count == 21
    assert first.audited_plan_count == 21
    assert first.minimum_shortfall == 0
    assert all(result.passed for result in first.results)
    assert [result.plan_version_id for result in first.results] == [
        result.plan_version_id for result in second.results
    ]
    assert demo.id not in {result.plan_version_id for result in first.results}
    assert first.cohort_id == "prod-acceptance-2026-w36"
    assert first.cutover_id == "release-2026-w36"
    assert first.environment == ENVIRONMENT
    assert first.manifest_digest.startswith("sha256:")
    assert first.signature_key_id == KEY_ID
    assert all(binding.passed for binding in first.bindings)


@pytest.mark.unit
def test_traceability_audit_fails_closed_when_fewer_than_twenty_plans_exist(db, tmp_path):
    plans = _persist_plans(db, 19)

    report = audit_plan_traceability(
        db,
        cohort=_load_cohort(tmp_path, plans),
        sample_size=20,
    )

    assert report.passed is False
    assert report.audited_plan_count == 19
    assert report.minimum_shortfall == 1


@pytest.mark.unit
def test_traceability_audit_detects_snapshot_and_product_provenance_tampering(db, tmp_path):
    plans = _persist_plans(db, 20)
    broken = plans[0]
    broken.plan_json["furnitureSuggestions"][0]["sourceName"] = ""
    broken.quote_snapshot.quote_json["lineItems"][0]["subtotal"] += 1
    flag_modified(broken, "plan_json")
    flag_modified(broken.quote_snapshot, "quote_json")
    db.commit()

    report = audit_plan_traceability(
        db,
        cohort=_load_cohort(tmp_path, plans),
        sample_size=20,
    )
    result = next(
        item for item in report.results if item.plan_version_id == broken.id
    )

    assert report.passed is False
    assert result.passed is False
    assert "product_source_missing" in result.reason_codes
    assert "quote_line_subtotal_mismatch" in result.reason_codes
    assert "quote_snapshot_inconsistent" in result.reason_codes


@pytest.mark.unit
def test_traceability_recomputes_frozen_custom_rule_and_binds_outer_line(db):
    payload = _traceable_plan(1)
    custom_item, custom_line = frozen_custom_quote()
    payload["customItems"] = [custom_item]
    payload["shopQuote"]["customLineItems"] = [custom_line]
    payload["shopQuote"]["customTotal"] = 4600
    payload["shopQuote"]["total"] += 4600
    task = DesignTask(status="completed", confirmed_requirement_json={})
    db.add(task)
    db.flush()
    revision = persist_generation(
        db,
        task=task,
        plans=[payload],
        generator="llm",
    )
    db.commit()
    plan = revision.plans[0]

    assert audit_plan_snapshot(plan).passed is True

    changed_plan = dict(plan.plan_json)
    changed_quote = dict(changed_plan["shopQuote"])
    changed_lines = [dict(changed_quote["customLineItems"][0])]
    changed_lines[0]["unitPrice"] += 1
    changed_quote["customLineItems"] = changed_lines
    changed_plan["shopQuote"] = changed_quote
    plan.plan_json = changed_plan
    snapshot_quote = dict(plan.quote_snapshot.quote_json)
    snapshot_quote["customLineItems"] = changed_lines
    plan.quote_snapshot.quote_json = snapshot_quote
    db.commit()

    result = audit_plan_snapshot(plan)
    assert result.passed is False
    assert "custom_rule_evidence_mismatch" in result.reason_codes

    restored_item, restored_line = frozen_custom_quote()
    restored_item["project"] = "校验后被替换的定制项目"
    changed_plan = dict(plan.plan_json)
    changed_plan["customItems"] = [restored_item]
    changed_quote = dict(changed_plan["shopQuote"])
    changed_quote["customLineItems"] = [restored_line]
    changed_plan["shopQuote"] = changed_quote
    plan.plan_json = changed_plan
    snapshot_quote = dict(plan.quote_snapshot.quote_json)
    snapshot_quote["customLineItems"] = [restored_line]
    plan.quote_snapshot.quote_json = snapshot_quote
    db.commit()

    result = audit_plan_snapshot(plan)
    assert result.passed is False
    assert "custom_rule_evidence_mismatch" in result.reason_codes


@pytest.mark.unit
def test_snapshot_audit_rejects_untrusted_and_unbound_derived_generators(db):
    untrusted = _persist_plans(db, 1)[0]
    untrusted.revision.generator = "template"
    db.commit()
    assert audit_plan_snapshot(untrusted).reason_codes == (
        "generation_source_untrusted",
    )

    derived = _persist_plans(db, 1)[0]
    derived.revision.generator = "refine"
    derived.revision.workflow_trace_snapshot = [
        {"node": "plan_refine", "status": "completed"}
    ]
    db.commit()
    assert audit_plan_snapshot(derived).reason_codes == (
        "generation_source_chain_invalid",
    )

@pytest.mark.unit
def test_traceability_audit_checks_members_beyond_minimum_instead_of_sampling_them_out(
    db, tmp_path
):
    plans = _persist_plans(db, 21)
    broken = plans[-1]
    broken.plan_json["furnitureSuggestions"][0]["sourceName"] = ""
    flag_modified(broken, "plan_json")
    db.commit()

    report = audit_plan_traceability(
        db,
        cohort=_load_cohort(tmp_path, plans),
        sample_size=20,
    )

    assert report.audited_plan_count == 21
    assert report.passed is False
    assert next(
        item for item in report.results if item.plan_version_id == broken.id
    ).reason_codes == (
        "product_source_missing",
        "product_eligibility_facts_mismatch",
    )


@pytest.mark.unit
def test_traceability_audit_does_not_filter_out_missing_quote_snapshots(db, tmp_path):
    plans = _persist_plans(db, 20)
    db.delete(plans[0].quote_snapshot)
    db.commit()

    report = audit_plan_traceability(
        db,
        cohort=_load_cohort(tmp_path, plans),
        sample_size=20,
    )

    assert report.passed is False
    assert report.audited_plan_count == 20
    assert any(
        result.reason_codes == ("quote_snapshot_missing",)
        for result in report.results
    )


@pytest.mark.unit
@pytest.mark.parametrize("sample_size", [0, 101])
def test_traceability_audit_rejects_unsafe_sample_sizes(db, sample_size):
    with pytest.raises(ValueError, match="sample_size"):
        audit_plan_traceability(db, cohort=None, sample_size=sample_size)


@pytest.mark.unit
def test_traceability_audit_never_infers_production_cohort_from_completed_rows(db):
    _persist_plans(db, 20)

    with pytest.raises(PlanTraceabilityCohortError, match="已验签"):
        audit_plan_traceability(
            db, cohort=None, sample_size=20
        )


@pytest.mark.unit
def test_cohort_manifest_rejects_tampering_unknown_key_and_wrong_environment(db, tmp_path):
    plans = _persist_plans(db, 1)
    path = _write_cohort(tmp_path, plans)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["members"][0]["task_id"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PlanTraceabilityCohortError, match="签名"):
        load_plan_traceability_cohort(
            path,
            expected_environment=ENVIRONMENT,
            verification_keys={KEY_ID: SIGNING_KEY},
        )
    with pytest.raises(PlanTraceabilityCohortError, match="环境"):
        load_plan_traceability_cohort(
            _write_cohort(tmp_path, plans),
            expected_environment="staging-cn",
            verification_keys={KEY_ID: SIGNING_KEY},
        )
    with pytest.raises(PlanTraceabilityCohortError, match="验签密钥"):
        load_plan_traceability_cohort(
            _write_cohort(tmp_path, plans),
            expected_environment=ENVIRONMENT,
            verification_keys={},
        )


@pytest.mark.unit
def test_cohort_database_binding_failures_are_never_filtered_from_gate(db, tmp_path):
    plans = _persist_plans(db, 19)
    failed_plan = _persist_plans(db, 1)[0]
    failed_plan.revision.status = "failed"
    plans.append(failed_plan)
    db.commit()
    cohort_path = _write_cohort(tmp_path, plans)
    cohort_payload = json.loads(cohort_path.read_text(encoding="utf-8"))
    cohort_payload["members"][0]["task_id"] += 1000
    cohort_payload["members"][1]["plan_version_id"] += 1000
    canonical = json.dumps(
        {key: value for key, value in cohort_payload.items() if key != "attestation"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    cohort_payload["attestation"]["signature"] = hmac.new(
        SIGNING_KEY.encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()
    cohort_path.write_text(json.dumps(cohort_payload), encoding="utf-8")
    cohort = load_plan_traceability_cohort(
        cohort_path,
        expected_environment=ENVIRONMENT,
        verification_keys={KEY_ID: SIGNING_KEY},
    )

    report = audit_plan_traceability(
        db, cohort=cohort, sample_size=20
    )

    assert report.passed is False
    assert report.eligible_member_count == 17
    assert report.minimum_shortfall == 3
    assert {reason for item in report.bindings for reason in item.reason_codes} == {
        "task_binding_mismatch",
        "plan_version_missing",
        "revision_not_completed",
    }


@pytest.mark.unit
def test_traceability_cli_requires_secret_env_and_writes_auditable_cohort_report(
    db, tmp_path, monkeypatch
):
    from audit_plan_traceability import main
    import audit_plan_traceability as cli

    plans = _persist_plans(db, 20)
    manifest = _write_cohort(tmp_path, plans)
    output = tmp_path / "report.json"
    args = [
        "--sample-size", "20",
        "--cohort-manifest", str(manifest),
        "--environment", ENVIRONMENT,
        "--output", str(output),
    ]
    monkeypatch.delenv("PLAN_TRACEABILITY_COHORT_KEY_ID", raising=False)
    monkeypatch.delenv("PLAN_TRACEABILITY_COHORT_HMAC_KEY", raising=False)
    assert main(args) == 2
    assert not output.exists()

    class SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return False

    monkeypatch.setenv("PLAN_TRACEABILITY_COHORT_KEY_ID", KEY_ID)
    monkeypatch.setenv("PLAN_TRACEABILITY_COHORT_HMAC_KEY", SIGNING_KEY)
    monkeypatch.setattr(cli, "SessionLocal", SessionContext)

    assert main(args) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["cohort_id"] == "prod-acceptance-2026-w36"
    assert report["cutover_id"] == "release-2026-w36"
    assert report["environment"] == ENVIRONMENT
    assert report["signature_key_id"] == KEY_ID
    assert SIGNING_KEY not in output.read_text(encoding="utf-8")
