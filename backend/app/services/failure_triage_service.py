"""匿名失败簇的报告同步、聚合与严格状态迁移。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    FailureCluster,
    FailureTriageImport,
    FailureVerificationImport,
)
from app.schemas.failure_triage import (
    FailureClusterUpdate,
    FailureTriageItem,
    FailureTriageReportRequest,
    FailureVerificationReportRequest,
)
from app.services.failure_triage_signature import verify_failure_triage_signature


class FailureTriageConflict(ValueError):
    pass


class FailureTriageSignatureError(FailureTriageConflict):
    pass


@dataclass(frozen=True)
class FailureTriageSyncResult:
    imported: bool
    clusters: tuple[FailureCluster, ...]


@dataclass(frozen=True)
class FailureVerificationSyncResult:
    imported: bool
    report_digest: str
    coverage_digest: str
    clusters: tuple[FailureCluster, ...]


_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_NEXT_STATUS = {
    "open": "in_progress",
    "in_progress": "resolved",
}


def _payload_hash(report: FailureTriageReportRequest) -> str:
    payload = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_digest(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def _verification_report_digest(report: FailureVerificationReportRequest) -> str:
    return _sha256_digest(report.model_dump(mode="json"))


def _verification_semantic_digest(report: FailureVerificationReportRequest) -> str:
    payload = report.model_dump(
        mode="json",
        exclude={"report_id", "generated_at", "signature_key_id", "signature"},
    )
    payload["verified_clusters"] = sorted(
        payload["verified_clusters"],
        key=lambda item: (item["fingerprint"], item["fixed_version"]),
    )
    return _sha256_digest(payload)


def _verification_coverage_digest(report: FailureVerificationReportRequest) -> str:
    return _sha256_digest(
        report.model_dump(
            mode="json",
            include={
                "taxonomy_version",
                "data_version",
                "candidate_version",
                "release_gate_report_digest",
                "manifest_digests",
                "evidence_digests",
                "baseline_evidence_digests",
                "output_digests",
                "covered_splits",
            },
        )
    )


def _semantic_hash(report: FailureTriageReportRequest) -> str:
    payload = json.dumps(
        report.model_dump(
            mode="json",
            exclude={
                "report_id",
                "generated_at",
                "signature_key_id",
                "signature",
            },
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _clusters_for_report(
    db: Session,
    report: FailureTriageReportRequest,
) -> tuple[FailureCluster, ...]:
    return tuple(
        cluster
        for item in report.failures
        if (
            cluster := db.scalar(
                select(FailureCluster).where(
                    FailureCluster.fingerprint
                    == failure_fingerprint(
                        taxonomy_version=report.taxonomy_version,
                        data_version=report.data_version,
                        failure_type=item.failure_type,
                        code=item.code,
                    )
                )
            )
        )
        is not None
    )


def _clusters_for_verification_report(
    db: Session,
    report_id: str,
) -> tuple[FailureCluster, ...]:
    return tuple(
        db.scalars(
            select(FailureCluster)
            .where(FailureCluster.verification_report_id == report_id)
            .order_by(FailureCluster.id)
        ).all()
    )


def failure_fingerprint(
    *,
    taxonomy_version: str,
    data_version: str,
    failure_type: str,
    code: str,
) -> str:
    payload = json.dumps(
        [taxonomy_version, data_version, failure_type, code],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _later(left: datetime, right: datetime) -> datetime:
    return max(_aware(left), _aware(right))


def _upsert_cluster(
    db: Session,
    report: FailureTriageReportRequest,
    failure: FailureTriageItem,
) -> FailureCluster:
    fingerprint = failure_fingerprint(
        taxonomy_version=report.taxonomy_version,
        data_version=report.data_version,
        failure_type=failure.failure_type,
        code=failure.code,
    )
    cluster = db.scalar(
        select(FailureCluster).where(FailureCluster.fingerprint == fingerprint)
    )
    if cluster is None:
        cluster = FailureCluster(
            fingerprint=fingerprint,
            taxonomy_version=report.taxonomy_version,
            data_version=report.data_version,
            failure_type=failure.failure_type,
            code=failure.code,
            severity=failure.severity,
            status="open",
            occurrence_count=failure.occurrence_count,
            affected_count=failure.affected_count,
            first_seen_at=report.generated_at,
            last_seen_at=report.generated_at,
            detected_version=report.candidate_version,
        )
        db.add(cluster)
        return cluster

    cluster.occurrence_count += failure.occurrence_count
    cluster.affected_count += failure.affected_count
    cluster.last_seen_at = _later(cluster.last_seen_at, report.generated_at)
    cluster.detected_version = report.candidate_version
    if _SEVERITY_RANK[failure.severity] > _SEVERITY_RANK[cluster.severity]:
        cluster.severity = failure.severity
    if cluster.status in {"resolved", "verified"}:
        cluster.status = "open"
        cluster.fixed_version = None
        cluster.verified_version = None
        cluster.verification_report_id = None
        cluster.report_digest = None
        cluster.coverage_digest = None
    return cluster


def sync_verified_report(
    db: Session,
    report: FailureTriageReportRequest,
    *,
    signing_key: str,
) -> FailureTriageSyncResult:
    serialized = report.model_dump(mode="json")
    if not verify_failure_triage_signature(
        serialized,
        signing_key=signing_key,
    ):
        raise FailureTriageSignatureError("失败分诊报告签名无效")
    digest = _payload_hash(report)
    semantic_digest = _semantic_hash(report)
    existing = db.scalar(
        select(FailureTriageImport).where(
            FailureTriageImport.report_id == report.report_id
        )
    )
    if existing is not None:
        if existing.payload_hash != digest:
            raise FailureTriageConflict("report_id 已用于不同报告")
        return FailureTriageSyncResult(
            imported=False,
            clusters=_clusters_for_report(db, report),
        )

    replay = db.scalar(
        select(FailureTriageImport).where(
            FailureTriageImport.semantic_hash == semantic_digest
        )
    )
    if replay is not None:
        raise FailureTriageConflict("相同语义证据已使用其他 report_id 导入")

    clusters = tuple(_upsert_cluster(db, report, item) for item in report.failures)
    db.add(
        FailureTriageImport(
            report_id=report.report_id,
            payload_hash=digest,
            semantic_hash=semantic_digest,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(FailureTriageImport).where(
                FailureTriageImport.report_id == report.report_id
            )
        )
        if existing is not None and existing.payload_hash == digest:
            return FailureTriageSyncResult(
                imported=False,
                clusters=_clusters_for_report(db, report),
            )
        replay = db.scalar(
            select(FailureTriageImport).where(
                FailureTriageImport.semantic_hash == semantic_digest
            )
        )
        if replay is not None:
            raise FailureTriageConflict(
                "相同语义证据已使用其他 report_id 导入"
            ) from exc
        raise FailureTriageConflict("报告同步冲突，请重试") from exc
    for cluster in clusters:
        db.refresh(cluster)
    return FailureTriageSyncResult(imported=True, clusters=clusters)


def sync_failure_verification(
    db: Session,
    report: FailureVerificationReportRequest,
    *,
    signing_key: str,
) -> FailureVerificationSyncResult:
    """验签完整三切分复测证明，并原子关闭全部匹配的 resolved 失败簇。"""
    serialized = report.model_dump(mode="json")
    if not verify_failure_triage_signature(serialized, signing_key=signing_key):
        raise FailureTriageSignatureError("失败复测证明签名无效")

    report_digest = _verification_report_digest(report)
    semantic_digest = _verification_semantic_digest(report)
    coverage_digest = _verification_coverage_digest(report)
    existing = db.scalar(
        select(FailureVerificationImport).where(
            FailureVerificationImport.report_id == report.report_id
        )
    )
    if existing is not None:
        if existing.report_digest != report_digest:
            raise FailureTriageConflict("report_id 已用于不同复测证明")
        return FailureVerificationSyncResult(
            imported=False,
            report_digest=existing.report_digest,
            coverage_digest=existing.coverage_digest,
            clusters=_clusters_for_verification_report(db, report.report_id),
        )
    replay = db.scalar(
        select(FailureVerificationImport).where(
            FailureVerificationImport.semantic_digest == semantic_digest
        )
    )
    if replay is not None:
        raise FailureTriageConflict("相同语义证据已使用其他 report_id 导入")

    claims = {item.fingerprint: item for item in report.verified_clusters}
    clusters = tuple(
        db.scalars(
            select(FailureCluster)
            .where(FailureCluster.fingerprint.in_(sorted(claims)))
            .order_by(FailureCluster.id)
            .with_for_update()
        ).all()
    )
    found = {cluster.fingerprint: cluster for cluster in clusters}
    if set(found) != set(claims):
        raise FailureTriageConflict("复测证明包含不存在的失败簇")
    for fingerprint, claim in claims.items():
        cluster = found[fingerprint]
        if cluster.status != "resolved":
            raise FailureTriageConflict("复测目标必须全部处于 resolved 状态")
        if cluster.taxonomy_version != report.taxonomy_version:
            raise FailureTriageConflict("复测目标 taxonomy_version 不匹配")
        if cluster.data_version != report.data_version:
            raise FailureTriageConflict("复测目标 data_version 不匹配")
        if cluster.fixed_version != claim.fixed_version:
            raise FailureTriageConflict("复测目标 fixed_version 不匹配")

    db.add(
        FailureVerificationImport(
            report_id=report.report_id,
            report_digest=report_digest,
            semantic_digest=semantic_digest,
            coverage_digest=coverage_digest,
        )
    )
    try:
        db.flush()
        for cluster in clusters:
            cluster.status = "verified"
            cluster.verified_version = report.candidate_version
            cluster.verification_report_id = report.report_id
            cluster.report_digest = report_digest
            cluster.coverage_digest = coverage_digest
            cluster.updated_at = datetime.now(timezone.utc)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(FailureVerificationImport).where(
                FailureVerificationImport.report_id == report.report_id
            )
        )
        if existing is not None and existing.report_digest == report_digest:
            return FailureVerificationSyncResult(
                imported=False,
                report_digest=existing.report_digest,
                coverage_digest=existing.coverage_digest,
                clusters=_clusters_for_verification_report(db, report.report_id),
            )
        replay = db.scalar(
            select(FailureVerificationImport).where(
                FailureVerificationImport.semantic_digest == semantic_digest
            )
        )
        if replay is not None:
            raise FailureTriageConflict(
                "相同语义证据已使用其他 report_id 导入"
            ) from exc
        raise FailureTriageConflict("复测证明同步冲突，请重试") from exc
    for cluster in clusters:
        db.refresh(cluster)
    return FailureVerificationSyncResult(
        imported=True,
        report_digest=report_digest,
        coverage_digest=coverage_digest,
        clusters=clusters,
    )


def list_failure_clusters(
    db: Session,
    *,
    status: str | None = None,
    severity: str | None = None,
) -> tuple[list[FailureCluster], dict[str, object]]:
    statement = select(FailureCluster)
    if status is not None:
        statement = statement.where(FailureCluster.status == status)
    if severity is not None:
        statement = statement.where(FailureCluster.severity == severity)
    clusters = list(
        db.scalars(
            statement.order_by(FailureCluster.last_seen_at.desc(), FailureCluster.id)
        ).all()
    )
    return clusters, {
        "total": len(clusters),
        "by_status": dict(sorted(Counter(item.status for item in clusters).items())),
        "by_severity": dict(
            sorted(Counter(item.severity for item in clusters).items())
        ),
    }


def update_failure_cluster(
    db: Session,
    cluster: FailureCluster,
    update: FailureClusterUpdate,
) -> FailureCluster:
    # v2 分诊报告只列出现存失败，没有完整覆盖声明；“未列出”不能证明已修复。
    # verified 必须留给未来校验 manifest/evidence/output 摘要与覆盖范围的专用流程。
    if cluster.status == "verified":
        raise FailureTriageConflict("已验证失败簇不能通过管理员 PATCH 修改")
    if update.status == "verified" or "verified_version" in update.model_fields_set:
        raise FailureTriageConflict(
            "verified 状态只能由签名复测证据流程写入，管理员最多标记 resolved"
        )

    target_status = update.status or cluster.status
    if update.status is not None and update.status != cluster.status:
        expected = _NEXT_STATUS.get(cluster.status)
        if update.status != expected:
            raise FailureTriageConflict(
                f"不允许的状态迁移：{cluster.status} -> {update.status}"
            )

    owner = update.owner if "owner" in update.model_fields_set else cluster.owner
    fixed_version = (
        update.fixed_version
        if "fixed_version" in update.model_fields_set
        else cluster.fixed_version
    )
    verified_version = cluster.verified_version
    if target_status == "in_progress" and not owner:
        raise FailureTriageConflict("认领失败簇必须指定负责人")
    if "fixed_version" in update.model_fields_set and target_status not in {
        "resolved",
        "verified",
    }:
        raise FailureTriageConflict("修复版本只能在标记修复后写入")
    if target_status == "resolved" and not fixed_version:
        raise FailureTriageConflict("标记修复必须指定修复版本")

    cluster.status = target_status
    cluster.owner = owner
    cluster.fixed_version = fixed_version
    cluster.verified_version = verified_version
    cluster.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cluster)
    return cluster
