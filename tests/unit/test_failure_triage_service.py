from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import FailureCluster, FailureVerificationImport
from app.schemas.failure_triage import (
    FailureClusterUpdate,
    FailureTriageReportRequest,
    FailureVerificationReportRequest,
)
from app.services.failure_triage_service import (
    FailureTriageConflict,
    FailureTriageSignatureError,
    sync_failure_verification,
    sync_verified_report,
    update_failure_cluster,
)
from app.services.failure_triage_signature import sign_failure_triage_payload


_SIGNING_KEY = "test-report-signing-key-at-least-32-bytes"


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def _report(report_id: str, candidate_version: str = "candidate-1"):
    payload = {
        "schema_version": "2.0",
        "report_id": report_id,
        "taxonomy_version": "taxonomy-1",
        "data_version": "data-1",
        "manifest_digest": "sha256:" + "1" * 64,
        "evidence_digest": "sha256:" + "2" * 64,
        "output_digests": ["sha256:" + "3" * 64],
        "candidate_version": candidate_version,
        "signature_algorithm": "hmac-sha256",
        "signature_key_id": "eval-key-v1",
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
    payload["signature"] = sign_failure_triage_payload(
        payload,
        signing_key=_SIGNING_KEY,
    )
    return FailureTriageReportRequest.model_validate(payload)


def _verification_report(
    report_id: str,
    clusters: list[FailureCluster],
    *,
    candidate_version: str = "candidate-2",
) -> FailureVerificationReportRequest:
    payload = {
        "schema_version": "1.0",
        "report_type": "failure_verification",
        "report_id": report_id,
        "taxonomy_version": "taxonomy-1",
        "data_version": "data-1",
        "candidate_version": candidate_version,
        "release_gate_report_digest": "sha256:" + "0" * 64,
        "manifest_digests": ["sha256:" + str(index) * 64 for index in range(1, 4)],
        "evidence_digests": ["sha256:" + str(index) * 64 for index in range(4, 7)],
        "baseline_evidence_digests": [
            "sha256:" + str(index) * 64 for index in range(7, 10)
        ],
        "output_digests": ["sha256:" + "4" * 64],
        "covered_splits": ["blind", "development", "regression"],
        "verified_clusters": [
            {
                "fingerprint": cluster.fingerprint,
                "fixed_version": cluster.fixed_version,
            }
            for cluster in clusters
        ],
        "signature_algorithm": "hmac-sha256",
        "signature_key_id": "eval-key-v1",
        "generated_at": "2026-09-08T10:00:00Z",
    }
    payload["signature"] = sign_failure_triage_payload(
        payload,
        signing_key=_SIGNING_KEY,
    )
    return FailureVerificationReportRequest.model_validate(payload)


def _resolved_clusters(db) -> tuple[FailureCluster, FailureCluster]:
    first = FailureCluster(
        fingerprint="a" * 64,
        taxonomy_version="taxonomy-1",
        data_version="data-1",
        failure_type="layout",
        code="item_collision",
        severity="high",
        status="resolved",
        owner="quality-admin",
        occurrence_count=2,
        affected_count=2,
        first_seen_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        detected_version="candidate-1",
        fixed_version="rules-2",
    )
    second = FailureCluster(
        fingerprint="b" * 64,
        taxonomy_version="taxonomy-1",
        data_version="data-1",
        failure_type="quote",
        code="quote_mismatch",
        severity="critical",
        status="resolved",
        owner="quality-admin",
        occurrence_count=1,
        affected_count=1,
        first_seen_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        detected_version="candidate-1",
        fixed_version="quote-rules-2",
    )
    db.add_all([first, second])
    db.commit()
    return first, second


def test_verification_schema_rejects_partial_coverage_and_noncanonical_digests(db):
    clusters = list(_resolved_clusters(db))
    payload = _verification_report("verify-001", clusters).model_dump(mode="json")

    payload["covered_splits"] = ["development", "regression"]
    with pytest.raises(ValueError, match="covered_splits"):
        FailureVerificationReportRequest.model_validate(payload)

    payload = _verification_report("verify-002", clusters).model_dump(mode="json")
    payload["manifest_digests"] = [
        "sha256:" + "2" * 64,
        "sha256:" + "1" * 64,
        "sha256:" + "3" * 64,
    ]
    with pytest.raises(ValueError, match="排序去重"):
        FailureVerificationReportRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "slice_end"),
    [
        ("manifest_digests", 2),
        ("manifest_digests", None),
        ("evidence_digests", 2),
        ("evidence_digests", None),
        ("baseline_evidence_digests", 2),
        ("baseline_evidence_digests", None),
    ],
)
def test_verification_schema_requires_exactly_three_digests_per_evidence_family(
    db, field, slice_end
):
    clusters = list(_resolved_clusters(db))
    payload = _verification_report("verify-001", clusters).model_dump(mode="json")
    if slice_end is None:
        payload[field].append("sha256:" + "a" * 64)
    else:
        payload[field] = payload[field][:slice_end]

    with pytest.raises(ValueError):
        FailureVerificationReportRequest.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    ["taxonomy_version", "data_version", "candidate_version"],
)
def test_verification_schema_rejects_blank_versions(db, field):
    clusters = list(_resolved_clusters(db))
    payload = _verification_report("verify-001", clusters).model_dump(mode="json")
    payload[field] = "   "

    with pytest.raises(ValueError, match="版本不能为空"):
        FailureVerificationReportRequest.model_validate(payload)


def test_signed_verification_atomically_closes_resolved_clusters_and_is_idempotent(db):
    clusters = list(_resolved_clusters(db))
    report = _verification_report("verify-001", clusters)

    first = sync_failure_verification(db, report, signing_key=_SIGNING_KEY)
    duplicate = sync_failure_verification(db, report, signing_key=_SIGNING_KEY)

    assert first.imported is True
    assert duplicate.imported is False
    assert {item.status for item in first.clusters} == {"verified"}
    assert {item.verified_version for item in first.clusters} == {"candidate-2"}
    assert {item.verification_report_id for item in first.clusters} == {"verify-001"}
    assert all(item.report_digest.startswith("sha256:") for item in first.clusters)
    assert all(item.coverage_digest.startswith("sha256:") for item in first.clusters)
    imported = db.scalar(select(FailureVerificationImport))
    assert imported is not None
    assert imported.report_id == "verify-001"


def test_verification_rejects_forgery_replay_and_report_id_conflict(db):
    clusters = list(_resolved_clusters(db))
    report = _verification_report("verify-001", clusters)
    forged = report.model_copy(update={"candidate_version": "forged"})
    with pytest.raises(FailureTriageSignatureError, match="签名"):
        sync_failure_verification(db, forged, signing_key=_SIGNING_KEY)

    sync_failure_verification(db, report, signing_key=_SIGNING_KEY)
    changed = _verification_report("verify-001", clusters, candidate_version="candidate-3")
    with pytest.raises(FailureTriageConflict, match="report_id"):
        sync_failure_verification(db, changed, signing_key=_SIGNING_KEY)
    replay = _verification_report("verify-002", clusters)
    with pytest.raises(FailureTriageConflict, match="相同语义证据"):
        sync_failure_verification(db, replay, signing_key=_SIGNING_KEY)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda cluster: setattr(cluster, "status", "in_progress"), "resolved"),
        (lambda cluster: setattr(cluster, "taxonomy_version", "taxonomy-2"), "taxonomy"),
        (lambda cluster: setattr(cluster, "data_version", "data-2"), "data"),
        (lambda cluster: setattr(cluster, "fixed_version", "rules-other"), "fixed_version"),
    ],
)
def test_verification_mismatch_fails_whole_report_without_partial_updates(
    db, mutation, message
):
    first, second = _resolved_clusters(db)
    report = _verification_report("verify-001", [first, second])
    mutation(second)
    db.commit()

    with pytest.raises(FailureTriageConflict, match=message):
        sync_failure_verification(db, report, signing_key=_SIGNING_KEY)

    db.refresh(first)
    assert first.status == "resolved"
    assert first.verification_report_id is None
    assert db.scalar(select(FailureVerificationImport)) is None


def test_report_sync_is_idempotent_and_verified_recurrence_reopens(db):
    first = sync_verified_report(db, _report("report-001"), signing_key=_SIGNING_KEY)
    duplicate = sync_verified_report(
        db,
        _report("report-001"),
        signing_key=_SIGNING_KEY,
    )

    assert first.imported is True
    assert duplicate.imported is False
    cluster = db.scalar(select(FailureCluster))
    assert cluster is not None
    assert cluster.occurrence_count == 3
    assert cluster.affected_count == 2
    assert len(cluster.fingerprint) == 64
    changed_raw = _report("report-001").model_dump(mode="json")
    changed_raw["failures"][0]["occurrence_count"] = 4
    changed_raw["signature"] = sign_failure_triage_payload(
        changed_raw,
        signing_key=_SIGNING_KEY,
    )
    changed_payload = FailureTriageReportRequest.model_validate(changed_raw)
    with pytest.raises(FailureTriageConflict, match="report_id"):
        sync_verified_report(db, changed_payload, signing_key=_SIGNING_KEY)

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
    verification = _verification_report("verify-001", [cluster])
    sync_failure_verification(db, verification, signing_key=_SIGNING_KEY)
    assert cluster.verification_report_id == "verify-001"

    sync_verified_report(
        db,
        _report("report-002", "candidate-3"),
        signing_key=_SIGNING_KEY,
    )
    db.refresh(cluster)

    assert cluster.status == "open"
    assert cluster.occurrence_count == 6
    assert cluster.affected_count == 4
    assert cluster.detected_version == "candidate-3"
    assert cluster.fixed_version is None
    assert cluster.verified_version is None


def test_status_machine_rejects_skips_and_requires_versions(db):
    sync_verified_report(db, _report("report-001"), signing_key=_SIGNING_KEY)
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
    with pytest.raises(FailureTriageConflict, match="签名复测证据"):
        update_failure_cluster(
            db,
            cluster,
            FailureClusterUpdate(status="verified", verified_version="eval-2"),
        )
    with pytest.raises(FailureTriageConflict, match="签名复测证据"):
        update_failure_cluster(
            db,
            cluster,
            FailureClusterUpdate(verified_version="operator-claim"),
        )
    db.refresh(cluster)
    assert cluster.status == "resolved"
    assert cluster.verified_version is None


def test_signed_report_reopens_resolved_cluster_when_failure_recurs(db):
    sync_verified_report(db, _report("report-001"), signing_key=_SIGNING_KEY)
    cluster = db.scalar(select(FailureCluster))
    assert cluster is not None
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

    sync_verified_report(
        db,
        _report("report-002", "candidate-3"),
        signing_key=_SIGNING_KEY,
    )

    db.refresh(cluster)
    assert cluster.status == "open"
    assert cluster.fixed_version is None
    assert cluster.verified_version is None
    assert cluster.verification_report_id is None
    assert cluster.report_digest is None
    assert cluster.coverage_digest is None
    assert cluster.detected_version == "candidate-3"


def test_admin_update_cannot_mutate_verified_cluster(db):
    sync_verified_report(db, _report("report-001"), signing_key=_SIGNING_KEY)
    cluster = db.scalar(select(FailureCluster))
    assert cluster is not None
    cluster.status = "verified"
    cluster.fixed_version = "rules-2"
    cluster.verified_version = "signed-eval-2"
    db.commit()

    with pytest.raises(FailureTriageConflict, match="管理员 PATCH"):
        update_failure_cluster(
            db,
            cluster,
            FailureClusterUpdate(owner="another-operator"),
        )
    db.refresh(cluster)
    assert cluster.owner is None
    assert cluster.verified_version == "signed-eval-2"


def test_report_schema_rejects_case_ids_and_invalid_signatures(db):
    payload = _report("report-001").model_dump(mode="json")
    payload["failures"][0]["case_id"] = "private-case-001"
    with pytest.raises(ValueError):
        FailureTriageReportRequest.model_validate(payload)

    payload = _report("report-002").model_dump(mode="json")
    payload["signature"] = "0" * 64
    parsed = FailureTriageReportRequest.model_validate(payload)
    with pytest.raises(FailureTriageConflict, match="签名"):
        sync_verified_report(db, parsed, signing_key=_SIGNING_KEY)


def test_same_semantic_report_cannot_be_counted_twice_under_another_id(db):
    first = sync_verified_report(db, _report("report-001"), signing_key=_SIGNING_KEY)
    with pytest.raises(FailureTriageConflict, match="相同语义证据"):
        sync_verified_report(
            db,
            _report("report-002"),
            signing_key=_SIGNING_KEY,
        )

    assert first.imported is True
    cluster = db.scalar(select(FailureCluster))
    assert cluster is not None
    assert cluster.occurrence_count == 3
