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

from app.db.models import FailureCluster, FailureTriageImport
from app.schemas.failure_triage import (
    FailureClusterUpdate,
    FailureTriageItem,
    FailureTriageReportRequest,
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


_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_NEXT_STATUS = {
    "open": "in_progress",
    "in_progress": "resolved",
    "resolved": "verified",
}


def _payload_hash(report: FailureTriageReportRequest) -> str:
    payload = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
    if cluster.status == "verified":
        cluster.status = "open"
        cluster.fixed_version = None
        cluster.verified_version = None
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
    verified_version = (
        update.verified_version
        if "verified_version" in update.model_fields_set
        else cluster.verified_version
    )
    if target_status == "in_progress" and not owner:
        raise FailureTriageConflict("认领失败簇必须指定负责人")
    if "fixed_version" in update.model_fields_set and target_status not in {
        "resolved",
        "verified",
    }:
        raise FailureTriageConflict("修复版本只能在标记修复后写入")
    if "verified_version" in update.model_fields_set and target_status != "verified":
        raise FailureTriageConflict("复测版本只能在验证关闭时写入")
    if target_status in {"resolved", "verified"} and not fixed_version:
        raise FailureTriageConflict("标记修复必须指定修复版本")
    if target_status == "verified" and not verified_version:
        raise FailureTriageConflict("验证关闭必须指定复测版本")

    cluster.status = target_status
    cluster.owner = owner
    cluster.fixed_version = fixed_version
    cluster.verified_version = verified_version
    cluster.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cluster)
    return cluster
