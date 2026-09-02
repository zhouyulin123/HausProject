from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import FailureCluster
from app.schemas.failure_triage import FailureClusterUpdate, FailureTriageReportRequest
from app.services.failure_triage_service import (
    FailureTriageConflict,
    sync_verified_report,
    update_failure_cluster,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def _report(report_id: str, candidate_version: str = "candidate-1"):
    return FailureTriageReportRequest.model_validate(
        {
            "schema_version": "1.0",
            "report_id": report_id,
            "verification_status": "verified",
            "taxonomy_version": "taxonomy-1",
            "data_version": "data-1",
            "candidate_version": candidate_version,
            "generated_at": "2026-09-02T08:00:00Z",
            "failures": [
                {
                    "failure_type": "layout",
                    "code": "item_collision",
                    "severity": "high",
                    "occurrence_count": 3,
                    "affected_count": 2,
                }
            ],
        }
    )


def test_report_sync_is_idempotent_and_verified_recurrence_reopens(db):
    first = sync_verified_report(db, _report("report-001"))
    duplicate = sync_verified_report(db, _report("report-001"))

    assert first.imported is True
    assert duplicate.imported is False
    cluster = db.scalar(select(FailureCluster))
    assert cluster is not None
    assert cluster.occurrence_count == 3
    assert cluster.affected_count == 2
    assert len(cluster.fingerprint) == 64
    changed_payload = _report("report-001")
    changed_payload.failures[0].occurrence_count = 4
    with pytest.raises(FailureTriageConflict, match="report_id"):
        sync_verified_report(db, changed_payload)

    update_failure_cluster(
        db,
        cluster,
        FailureClusterUpdate(status="in_progress", owner="quality-admin"),
    )
    update_failure_cluster(
        db,
        cluster,
        FailureClusterUpdate(status="resolved", fixed_version="rules-2"),
    )
    update_failure_cluster(
        db,
        cluster,
        FailureClusterUpdate(status="verified", verified_version="eval-2"),
    )

    sync_verified_report(db, _report("report-002", "candidate-3"))
    db.refresh(cluster)

    assert cluster.status == "open"
    assert cluster.occurrence_count == 6
    assert cluster.affected_count == 4
    assert cluster.detected_version == "candidate-3"
    assert cluster.fixed_version is None
    assert cluster.verified_version is None


def test_status_machine_rejects_skips_and_requires_versions(db):
    sync_verified_report(db, _report("report-001"))
    cluster = db.scalar(select(FailureCluster))
    assert cluster is not None

    with pytest.raises(FailureTriageConflict, match="状态迁移"):
        update_failure_cluster(
            db,
            cluster,
            FailureClusterUpdate(status="resolved", fixed_version="rules-2"),
        )
    with pytest.raises(FailureTriageConflict, match="负责人"):
        update_failure_cluster(
            db,
            cluster,
            FailureClusterUpdate(status="in_progress"),
        )
    with pytest.raises(FailureTriageConflict, match="修复版本"):
        update_failure_cluster(
            db,
            cluster,
            FailureClusterUpdate(fixed_version="rules-too-early"),
        )

    update_failure_cluster(
        db,
        cluster,
        FailureClusterUpdate(status="in_progress", owner="quality-admin"),
    )
    with pytest.raises(FailureTriageConflict, match="修复版本"):
        update_failure_cluster(
            db,
            cluster,
            FailureClusterUpdate(status="resolved"),
        )
    update_failure_cluster(
        db,
        cluster,
        FailureClusterUpdate(status="resolved", fixed_version="rules-2"),
    )
    with pytest.raises(FailureTriageConflict, match="复测版本"):
        update_failure_cluster(
            db,
            cluster,
            FailureClusterUpdate(status="verified"),
        )


def test_report_schema_rejects_case_ids_and_unverified_inputs():
    payload = _report("report-001").model_dump(mode="json")
    payload["failures"][0]["case_id"] = "private-case-001"
    with pytest.raises(ValueError):
        FailureTriageReportRequest.model_validate(payload)

    payload = _report("report-002").model_dump(mode="json")
    payload["verification_status"] = "draft"
    with pytest.raises(ValueError):
        FailureTriageReportRequest.model_validate(payload)
