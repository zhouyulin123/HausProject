"""匿名失败簇的报告同步、聚合与严格状态迁移。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import case, select, update as sql_update
from sqlalchemy.exc import IntegrityError, OperationalError
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
_REPORT_SYNC_MAX_ATTEMPTS = 3


def _is_retryable_database_concurrency_error(exc: OperationalError) -> bool:
    original = exc.orig
    sqlstate = (
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
    )
    if sqlstate in {"40001", "40P01"}:
        return True
    arguments = getattr(original, "args", ())
    if arguments and arguments[0] in {1205, 1213}:
        return True
    message = str(original).lower()
    return "database is locked" in message or "database table is locked" in message


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


def _existing_verification_result(
    db: Session,
    report: FailureVerificationReportRequest,
    *,
    report_digest: str,
    semantic_digest: str,
    lock: bool,
) -> FailureVerificationSyncResult | None:
    report_query = select(FailureVerificationImport).where(
        FailureVerificationImport.report_id == report.report_id
    )
    semantic_query = select(FailureVerificationImport).where(
        FailureVerificationImport.semantic_digest == semantic_digest
    )
    if lock:
        report_query = report_query.with_for_update()
        semantic_query = semantic_query.with_for_update()
    existing = db.scalar(report_query)
    if existing is not None:
        if existing.report_digest != report_digest:
            raise FailureTriageConflict("report_id 已用于不同复测证明")
        return FailureVerificationSyncResult(
            imported=False,
            report_digest=existing.report_digest,
            coverage_digest=existing.coverage_digest,
            clusters=_clusters_for_verification_report(db, report.report_id),
        )
    if db.scalar(semantic_query) is not None:
        raise FailureTriageConflict("相同语义证据已使用其他 report_id 导入")
    return None


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
    reopened = FailureCluster.status.in_(("resolved", "verified"))
    observed_at_or_after_current = FailureCluster.last_seen_at <= report.generated_at
    lower_severities = [
        severity
        for severity, rank in _SEVERITY_RANK.items()
        if rank < _SEVERITY_RANK[failure.severity]
    ]
    severity = (
        case(
            (FailureCluster.severity.in_(lower_severities), failure.severity),
            else_=FailureCluster.severity,
        )
        if lower_severities
        else FailureCluster.severity
    )
    result = db.execute(
        sql_update(FailureCluster)
        .where(FailureCluster.fingerprint == fingerprint)
        .values(
            occurrence_count=(
                FailureCluster.occurrence_count + failure.occurrence_count
            ),
            affected_count=FailureCluster.affected_count + failure.affected_count,
            record_version=FailureCluster.record_version + 1,
            first_seen_at=case(
                (FailureCluster.first_seen_at > report.generated_at, report.generated_at),
                else_=FailureCluster.first_seen_at,
            ),
            last_seen_at=case(
                (observed_at_or_after_current, report.generated_at),
                else_=FailureCluster.last_seen_at,
            ),
            detected_version=case(
                (observed_at_or_after_current, report.candidate_version),
                else_=FailureCluster.detected_version,
            ),
            severity=severity,
            status=case((reopened, "open"), else_=FailureCluster.status),
            fixed_version=case((reopened, None), else_=FailureCluster.fixed_version),
            verified_version=case(
                (reopened, None),
                else_=FailureCluster.verified_version,
            ),
            verification_report_id=case(
                (reopened, None),
                else_=FailureCluster.verification_report_id,
            ),
            report_digest=case(
                (reopened, None),
                else_=FailureCluster.report_digest,
            ),
            coverage_digest=case(
                (reopened, None),
                else_=FailureCluster.coverage_digest,
            ),
            updated_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
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
        db.flush()
        return cluster
    cluster = db.scalar(
        select(FailureCluster)
        .where(FailureCluster.fingerprint == fingerprint)
        .execution_options(populate_existing=True)
    )
    if cluster is None:
        raise FailureTriageConflict("失败簇原子更新后无法读取")
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
    for attempt in range(_REPORT_SYNC_MAX_ATTEMPTS):
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
            raise FailureTriageConflict(
                "相同语义证据已使用其他 report_id 导入"
            )

        failures = sorted(
            report.failures,
            key=lambda item: failure_fingerprint(
                taxonomy_version=report.taxonomy_version,
                data_version=report.data_version,
                failure_type=item.failure_type,
                code=item.code,
            ),
        )
        try:
            for item in failures:
                _upsert_cluster(db, report, item)
            db.add(
                FailureTriageImport(
                    report_id=report.report_id,
                    payload_hash=digest,
                    semantic_hash=semantic_digest,
                )
            )
            db.commit()
            break
        except (IntegrityError, OperationalError) as exc:
            db.rollback()
            if isinstance(exc, OperationalError) and not (
                _is_retryable_database_concurrency_error(exc)
            ):
                raise
            if attempt + 1 >= _REPORT_SYNC_MAX_ATTEMPTS:
                raise FailureTriageConflict("报告同步冲突，请重试") from exc
    else:  # pragma: no cover - 循环只会通过 break 或异常退出
        raise FailureTriageConflict("报告同步冲突，请重试")

    clusters = _clusters_for_report(db, report)
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
    existing_result = _existing_verification_result(
        db,
        report,
        report_digest=report_digest,
        semantic_digest=semantic_digest,
        lock=False,
    )
    if existing_result is not None:
        return existing_result

    claims = {item.fingerprint: item for item in report.verified_clusters}
    clusters = tuple(
        db.scalars(
            select(FailureCluster)
            .where(FailureCluster.fingerprint.in_(sorted(claims)))
            .order_by(FailureCluster.fingerprint)
            .with_for_update()
        ).all()
    )
    # 另一个事务可能在等待失败簇锁期间完成相同导入；锁后必须重新判定幂等。
    existing_result = _existing_verification_result(
        db,
        report,
        report_digest=report_digest,
        semantic_digest=semantic_digest,
        lock=True,
    )
    if existing_result is not None:
        return existing_result
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
            cluster.record_version += 1
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
    if cluster.record_version != update.expected_version:
        raise FailureTriageConflict("失败簇版本已变化，请刷新后重试")
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

    original = {
        "status": cluster.status,
        "owner": cluster.owner,
        "fixed_version": cluster.fixed_version,
        "verified_version": cluster.verified_version,
        "verification_report_id": cluster.verification_report_id,
        "report_digest": cluster.report_digest,
        "coverage_digest": cluster.coverage_digest,
    }
    conditions = [FailureCluster.id == cluster.id]
    conditions.append(FailureCluster.record_version == update.expected_version)
    for field_name, value in original.items():
        column = getattr(FailureCluster, field_name)
        conditions.append(column.is_(None) if value is None else column == value)
    result = db.execute(
        sql_update(FailureCluster)
        .where(*conditions)
        .values(
            status=target_status,
            owner=owner,
            fixed_version=fixed_version,
            verified_version=verified_version,
            record_version=FailureCluster.record_version + 1,
            updated_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise FailureTriageConflict(
            "失败簇已被其他管理员或评测流程并发更新，请刷新后重试"
        )
    db.commit()
    db.refresh(cluster)
    return cluster
