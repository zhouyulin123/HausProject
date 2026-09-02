import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from app.db.database import Base
from app.db.models import DesignPlanVersion, DesignTask
from app.services.design_version_service import persist_generation
from app.services.plan_traceability_audit_service import audit_plan_traceability


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
    return {
        "id": f"plan-{index:03d}",
        "name": f"可追溯方案 {index}",
        "style": "现代简约",
        "furnitureSuggestions": [
            {
                "id": sku,
                "sku": sku,
                "name": f"商品 {index}",
                "quantity": 1,
                "unitPrice": unit_price,
                "subtotal": unit_price,
                "dataVersion": "catalog-2026-q3",
                "recordVersion": 2,
                "dataStatus": "verified",
                "sourceName": "门店商品主表",
                "verifiedAt": "2026-09-01T00:00:00+00:00",
            }
        ],
        "customItems": [],
        "shopQuote": {
            "furnitureTotal": unit_price,
            "customTotal": 0,
            "total": unit_price,
            "catalogVersion": "catalog-2026-q3",
            "priceVersion": "prices:sha256-valid",
            "ruleVersion": "rules:sha256-valid",
            "pricedAt": "2026-09-02T00:00:00+00:00",
            "lineItems": [
                {
                    "sku": sku,
                    "quantity": 1,
                    "unitPrice": unit_price,
                    "subtotal": unit_price,
                    "dataVersion": "catalog-2026-q3",
                    "recordVersion": 2,
                }
            ],
            "customLineItems": [],
        },
    }


def _persist_plans(db, count: int) -> list[DesignPlanVersion]:
    task = DesignTask(status="completed", confirmed_requirement_json={})
    db.add(task)
    db.commit()
    persist_generation(
        db,
        task=task,
        plans=[_traceable_plan(index) for index in range(count)],
        generator="llm",
    )
    db.commit()
    return list(db.scalars(select(DesignPlanVersion)).all())


@pytest.mark.unit
def test_traceability_audit_passes_only_with_complete_twenty_plan_sample(db):
    _persist_plans(db, 21)

    first = audit_plan_traceability(db, sample_size=20, seed="weekly-2026-36")
    second = audit_plan_traceability(db, sample_size=20, seed="weekly-2026-36")

    assert first.passed is True
    assert first.available_plan_count == 21
    assert first.sampled_plan_count == 20
    assert first.sample_shortfall == 0
    assert all(result.passed for result in first.results)
    assert [result.plan_version_id for result in first.results] == [
        result.plan_version_id for result in second.results
    ]


@pytest.mark.unit
def test_traceability_audit_fails_closed_when_fewer_than_twenty_plans_exist(db):
    _persist_plans(db, 19)

    report = audit_plan_traceability(db, sample_size=20, seed="weekly-2026-36")

    assert report.passed is False
    assert report.sampled_plan_count == 19
    assert report.sample_shortfall == 1


@pytest.mark.unit
def test_traceability_audit_detects_snapshot_and_product_provenance_tampering(db):
    plans = _persist_plans(db, 20)
    broken = plans[0]
    broken.plan_json["furnitureSuggestions"][0]["sourceName"] = ""
    broken.quote_snapshot.quote_json["lineItems"][0]["subtotal"] += 1
    flag_modified(broken, "plan_json")
    flag_modified(broken.quote_snapshot, "quote_json")
    db.commit()

    report = audit_plan_traceability(db, sample_size=20, seed="weekly-2026-36")
    result = next(
        item for item in report.results if item.plan_version_id == broken.id
    )

    assert report.passed is False
    assert result.passed is False
    assert "product_source_missing" in result.reason_codes
    assert "quote_line_subtotal_mismatch" in result.reason_codes
    assert "quote_snapshot_inconsistent" in result.reason_codes


@pytest.mark.unit
def test_traceability_audit_does_not_filter_out_missing_quote_snapshots(db):
    plans = _persist_plans(db, 20)
    db.delete(plans[0].quote_snapshot)
    db.commit()

    report = audit_plan_traceability(db, sample_size=20, seed="weekly-2026-36")

    assert report.passed is False
    assert report.sampled_plan_count == 20
    assert any(
        result.reason_codes == ("quote_snapshot_missing",)
        for result in report.results
    )


@pytest.mark.unit
@pytest.mark.parametrize("sample_size", [0, 101])
def test_traceability_audit_rejects_unsafe_sample_sizes(db, sample_size):
    with pytest.raises(ValueError, match="sample_size"):
        audit_plan_traceability(db, sample_size=sample_size, seed="weekly")
