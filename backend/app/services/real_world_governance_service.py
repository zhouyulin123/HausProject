"""真实案例治理收件箱：提升、证据登记、并发控制与数据集冻结。"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    DesignTask,
    GovernanceEvent,
    RealWorldAnnotationRevision,
    RealWorldCaseImport,
    RealWorldCaseRecord,
    RealWorldConsentDecision,
    RealWorldDatasetRevision,
    UploadedImage,
)
from app.schemas.real_world_governance import (
    AnnotationRevisionCreate,
    CaseGovernanceUpdate,
    CaseImportRequest,
    ConsentDecisionCreate,
    DatasetFreezeRequest,
    RealWorldCaseResponse,
)
from app.services.evaluation_binding_service import task_input_payload
from evals.annotations import CaseAnnotation
from evals.real_world import RealWorldCase, RealWorldDataset


class RealWorldGovernanceError(RuntimeError):
    pass


class RealWorldGovernanceNotFound(RealWorldGovernanceError):
    pass


class RealWorldGovernanceConflict(RealWorldGovernanceError):
    pass


class RealWorldGovernanceValidationError(RealWorldGovernanceError):
    pass


@dataclass(frozen=True)
class CaseImportPreview:
    asset_digest: str
    task_input: dict
    duplicate_asset: bool


@dataclass(frozen=True)
class CaseImportResult:
    created: bool
    case: RealWorldCaseRecord


@dataclass(frozen=True)
class DatasetFreezeResult:
    revision_ref: str
    schema_version: str
    dataset_version: str
    manifest_digest: str
    case_count: int
    split_counts: dict[str, int]
    created_at: datetime
    snapshot: tuple[dict, ...]


def _now(value: datetime | None = None) -> datetime:
    return value or datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RealWorldGovernanceValidationError("案例资产不可读取") from exc
    return f"sha256:{digest.hexdigest()}"


def _controlled_upload_path(image: UploadedImage, upload_root: Path | str) -> Path:
    raw_url = (image.file_url or "").strip()
    if not raw_url.startswith("/uploads/"):
        raise RealWorldGovernanceValidationError("图片不是受控上传资产")
    relative = Path(raw_url.removeprefix("/uploads/"))
    if relative.is_absolute():
        raise RealWorldGovernanceValidationError("图片不是受控上传资产")
    root = Path(upload_root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise RealWorldGovernanceValidationError("受控图片资产不存在")
    return path


def _import_inputs(
    db: Session,
    payload: CaseImportRequest,
    *,
    upload_root: Path | str,
) -> tuple[dict, str, str]:
    task = db.get(DesignTask, payload.task_id)
    image = db.get(UploadedImage, payload.uploaded_image_id)
    if task is None or image is None or image.task_id != task.id:
        raise RealWorldGovernanceNotFound("设计任务或所属图片不存在")
    task_input = task_input_payload(db, task)
    if not isinstance(task_input.get("confirmed_requirement"), dict):
        raise RealWorldGovernanceValidationError("设计任务缺少已确认需求")
    asset_digest = _file_digest(_controlled_upload_path(image, upload_root))
    if image.content_digest is not None and image.content_digest != asset_digest:
        raise RealWorldGovernanceValidationError("图片实际摘要与上传记录摘要不一致")
    request_digest = _canonical_digest(
        {
            "task_id": task.id,
            "uploaded_image_id": image.id,
            "asset_digest": asset_digest,
            "task_input": task_input,
        }
    )
    return task_input, asset_digest, request_digest


def preview_case_import(
    db: Session,
    payload: CaseImportRequest,
    *,
    upload_root: Path | str,
) -> CaseImportPreview:
    task_input, asset_digest, _ = _import_inputs(db, payload, upload_root=upload_root)
    duplicate = db.scalar(
        select(RealWorldCaseRecord.id).where(
            RealWorldCaseRecord.asset_digest == asset_digest
        )
    )
    return CaseImportPreview(
        asset_digest=asset_digest,
        task_input=task_input,
        duplicate_asset=duplicate is not None,
    )


def _audit_digest(db: Session, case: RealWorldCaseRecord | None) -> str:
    if case is None:
        return _canonical_digest({"state": "absent"})
    consent = _latest_consent(db, case.id)
    annotation = _latest_annotation(db, case.id)
    return _canonical_digest(
        {
            "case_ref": case.case_ref,
            "record_version": case.record_version,
            "split": case.split,
            "redaction_review": case.redaction_review,
            "asset_digest": case.asset_digest,
            "task_input_digest": case.task_input_digest,
            "consent_state_digest": (
                _canonical_digest(
                    {
                        "id": consent.id,
                        "decision": consent.decision,
                        "evidence_digest": consent.evidence_digest,
                        "effective_at": consent.effective_at,
                        "expires_at": consent.expires_at,
                        "allowed_purposes": consent.allowed_purposes_json,
                    }
                )
                if consent is not None
                else None
            ),
            "annotation_digest": (
                annotation.annotation_digest if annotation is not None else None
            ),
        }
    )


def _append_event(
    db: Session,
    *,
    case: RealWorldCaseRecord | None,
    actor_user_id: int,
    action: str,
    request_id: str,
    before_digest: str,
    after_digest: str,
) -> None:
    db.add(
        GovernanceEvent(
            case_id=case.id if case is not None else None,
            actor_user_id=actor_user_id,
            action=action,
            request_id=request_id,
            before_digest=before_digest,
            after_digest=after_digest,
        )
    )


def create_case_import(
    db: Session,
    payload: CaseImportRequest,
    *,
    actor_user_id: int,
    request_id: str,
    upload_root: Path | str,
) -> CaseImportResult:
    task_input, asset_digest, request_digest = _import_inputs(
        db, payload, upload_root=upload_root
    )
    existing = db.scalar(
        select(RealWorldCaseImport).where(
            RealWorldCaseImport.client_import_id == payload.client_import_id
        )
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise RealWorldGovernanceConflict(
                "client_import_id 已用于不同的案例提升输入"
            )
        case = db.get(RealWorldCaseRecord, existing.case_id)
        if case is None:
            raise RealWorldGovernanceConflict("案例提升记录缺少关联案例")
        return CaseImportResult(created=False, case=case)
    if (
        db.scalar(
            select(RealWorldCaseRecord.id).where(
                RealWorldCaseRecord.asset_digest == asset_digest
            )
        )
        is not None
    ):
        raise RealWorldGovernanceConflict("同一物理资产已经进入治理收件箱")

    case = RealWorldCaseRecord(
        case_ref=f"rwc_{secrets.token_hex(16)}",
        task_id=payload.task_id,
        uploaded_image_id=payload.uploaded_image_id,
        origin="private_real",
        asset_digest=asset_digest,
        task_input_json=task_input,
        task_input_digest=_canonical_digest(task_input),
        split="unassigned",
        redaction_review="pending",
        record_version=1,
        created_by_user_id=actor_user_id,
    )
    db.add(case)
    try:
        db.flush()
        db.add(
            RealWorldCaseImport(
                client_import_id=payload.client_import_id,
                request_digest=request_digest,
                case_id=case.id,
                actor_user_id=actor_user_id,
            )
        )
        _append_event(
            db,
            case=case,
            actor_user_id=actor_user_id,
            action="case_imported",
            request_id=request_id,
            before_digest=_canonical_digest({"state": "absent"}),
            after_digest=_audit_digest(db, case),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent = db.scalar(
            select(RealWorldCaseImport).where(
                RealWorldCaseImport.client_import_id == payload.client_import_id
            )
        )
        if concurrent is not None and concurrent.request_digest == request_digest:
            concurrent_case = db.get(RealWorldCaseRecord, concurrent.case_id)
            if concurrent_case is not None:
                return CaseImportResult(created=False, case=concurrent_case)
        if (
            db.scalar(
                select(RealWorldCaseRecord.id).where(
                    RealWorldCaseRecord.asset_digest == asset_digest
                )
            )
            is not None
        ):
            raise RealWorldGovernanceConflict("同一物理资产已经进入治理收件箱") from exc
        raise RealWorldGovernanceConflict("案例提升并发冲突，请重试") from exc
    db.refresh(case)
    return CaseImportResult(created=True, case=case)


def _case_or_raise(db: Session, case_ref: str) -> RealWorldCaseRecord:
    case = db.scalar(
        select(RealWorldCaseRecord).where(RealWorldCaseRecord.case_ref == case_ref)
    )
    if case is None:
        raise RealWorldGovernanceNotFound("真实案例治理记录不存在")
    return case


def _latest_consent(db: Session, case_id: int) -> RealWorldConsentDecision | None:
    return db.scalar(
        select(RealWorldConsentDecision)
        .where(RealWorldConsentDecision.case_id == case_id)
        .order_by(RealWorldConsentDecision.id.desc())
        .limit(1)
    )


def _latest_annotation(db: Session, case_id: int) -> RealWorldAnnotationRevision | None:
    return db.scalar(
        select(RealWorldAnnotationRevision)
        .where(RealWorldAnnotationRevision.case_id == case_id)
        .order_by(RealWorldAnnotationRevision.id.desc())
        .limit(1)
    )


def _consent_status(
    decision: RealWorldConsentDecision | None,
    *,
    now: datetime,
) -> str:
    if decision is None:
        return "pending"
    if decision.decision != "granted":
        return decision.decision
    current = _as_utc(now)
    if _as_utc(decision.effective_at) > current:
        return "pending"
    if decision.expires_at is not None and _as_utc(decision.expires_at) <= current:
        return "expired"
    return "granted"


def case_freeze_blockers(
    case: RealWorldCaseRecord,
    consent: RealWorldConsentDecision | None,
    annotation: RealWorldAnnotationRevision | None,
    *,
    now: datetime,
) -> list[str]:
    """共享候选准入条件；只检查治理记录，不读取私有资产。"""
    blockers: list[str] = []
    if case.origin != "private_real":
        blockers.append("case_not_private_real")
    if not case.task_input_json or not case.task_input_digest:
        blockers.append("task_input_not_ready")
    if case.redaction_review != "reviewed":
        blockers.append("redaction_not_reviewed")
    if _consent_status(consent, now=now) != "granted":
        blockers.append("consent_not_granted")
    elif "offline_evaluation" not in (consent.allowed_purposes_json or []):
        blockers.append("purpose_not_allowed")
    if annotation is None:
        blockers.append("annotation_not_ready")
    if case.split not in {"development", "regression", "blind"}:
        blockers.append("split_not_assigned")
    return blockers


def project_case_record(
    db: Session,
    case: RealWorldCaseRecord,
    *,
    now: datetime | None = None,
) -> RealWorldCaseResponse:
    current = _now(now)
    consent = _latest_consent(db, case.id)
    annotation = _latest_annotation(db, case.id)
    return RealWorldCaseResponse(
        case_ref=case.case_ref,
        origin="private_real",
        split=case.split,
        redaction_review=case.redaction_review,
        consent_status=_consent_status(consent, now=current),
        annotation_status="ready" if annotation is not None else "pending",
        record_version=case.record_version,
        blockers=case_freeze_blockers(case, consent, annotation, now=current),
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def list_case_records(
    db: Session,
    *,
    split: str | None = None,
    blocker: str | None = None,
    now: datetime | None = None,
) -> list[RealWorldCaseResponse]:
    statement = select(RealWorldCaseRecord).order_by(RealWorldCaseRecord.id.desc())
    if split is not None:
        statement = statement.where(RealWorldCaseRecord.split == split)
    items = [
        project_case_record(db, case, now=now) for case in db.scalars(statement).all()
    ]
    if blocker is not None:
        items = [item for item in items if blocker in item.blockers]
    return items


def _cas_version(
    db: Session,
    case: RealWorldCaseRecord,
    expected_version: int,
    *,
    values: dict | None = None,
) -> None:
    result = db.execute(
        sql_update(RealWorldCaseRecord)
        .where(
            RealWorldCaseRecord.id == case.id,
            RealWorldCaseRecord.record_version == expected_version,
        )
        .values(
            **(values or {}),
            record_version=RealWorldCaseRecord.record_version + 1,
            updated_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise RealWorldGovernanceConflict("案例版本已变化，请刷新后重试")


def _reload_case(db: Session, case_id: int) -> RealWorldCaseRecord:
    case = db.scalar(
        select(RealWorldCaseRecord)
        .where(RealWorldCaseRecord.id == case_id)
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise RealWorldGovernanceNotFound("真实案例治理记录不存在")
    return case


def update_case_governance(
    db: Session,
    case_ref: str,
    payload: CaseGovernanceUpdate,
    *,
    actor_user_id: int,
    request_id: str,
) -> RealWorldCaseRecord:
    case = _case_or_raise(db, case_ref)
    before = _audit_digest(db, case)
    values = (
        {"split": payload.split}
        if payload.split is not None
        else {"redaction_review": payload.redaction_review}
    )
    _cas_version(db, case, payload.expected_version, values=values)
    updated = _reload_case(db, case.id)
    if payload.split is not None:
        action = (
            "split_unassigned" if payload.split == "unassigned" else "split_assigned"
        )
    else:
        action = f"redaction_{payload.redaction_review}"
    _append_event(
        db,
        case=updated,
        actor_user_id=actor_user_id,
        action=action,
        request_id=request_id,
        before_digest=before,
        after_digest=_audit_digest(db, updated),
    )
    db.commit()
    db.refresh(updated)
    return updated


def add_consent_decision(
    db: Session,
    case_ref: str,
    payload: ConsentDecisionCreate,
    *,
    actor_user_id: int,
    request_id: str,
    now: datetime | None = None,
) -> RealWorldCaseRecord:
    current = _now(now)
    if payload.decision == "granted" and (
        _as_utc(payload.effective_at) > _as_utc(current)
        or (
            payload.expires_at is not None
            and _as_utc(payload.expires_at) <= _as_utc(current)
        )
    ):
        raise RealWorldGovernanceValidationError("授权当前尚未生效或已经过期")
    case = _case_or_raise(db, case_ref)
    before = _audit_digest(db, case)
    _cas_version(db, case, payload.expected_version)
    db.add(
        RealWorldConsentDecision(
            case_id=case.id,
            decision=payload.decision,
            legal_basis=payload.legal_basis,
            allowed_purposes_json=list(payload.allowed_purposes),
            evidence_digest=payload.evidence_digest,
            effective_at=payload.effective_at,
            expires_at=payload.expires_at,
            actor_user_id=actor_user_id,
        )
    )
    db.flush()
    updated = _reload_case(db, case.id)
    _append_event(
        db,
        case=updated,
        actor_user_id=actor_user_id,
        action=f"consent_{payload.decision}",
        request_id=request_id,
        before_digest=before,
        after_digest=_audit_digest(db, updated),
    )
    db.commit()
    db.refresh(updated)
    return updated


def add_annotation_revision(
    db: Session,
    case_ref: str,
    payload: AnnotationRevisionCreate,
    *,
    actor_user_id: int,
    request_id: str,
) -> RealWorldCaseRecord:
    case = _case_or_raise(db, case_ref)
    annotation: CaseAnnotation = payload.annotation
    if annotation.case_id != case.case_ref:
        raise RealWorldGovernanceValidationError("标注 case_id 与治理案例不一致")
    if annotation.source_asset_sha256 != case.asset_digest.removeprefix("sha256:"):
        raise RealWorldGovernanceValidationError("标注来源资产摘要与案例资产摘要不一致")
    annotation_json = annotation.model_dump(mode="json", by_alias=True)
    annotation_digest = _canonical_digest(annotation_json)
    before = _audit_digest(db, case)
    _cas_version(db, case, payload.expected_version)
    db.add(
        RealWorldAnnotationRevision(
            case_id=case.id,
            label_version=annotation.label_version,
            annotation_json=annotation_json,
            annotation_digest=annotation_digest,
            actor_user_id=actor_user_id,
        )
    )
    db.flush()
    updated = _reload_case(db, case.id)
    _append_event(
        db,
        case=updated,
        actor_user_id=actor_user_id,
        action="annotation_added",
        request_id=request_id,
        before_digest=before,
        after_digest=_audit_digest(db, updated),
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RealWorldGovernanceConflict("相同标注修订已经存在") from exc
    db.refresh(updated)
    return updated


def freeze_dataset_revision(
    db: Session,
    payload: DatasetFreezeRequest,
    *,
    actor_user_id: int,
    request_id: str,
    now: datetime | None = None,
) -> DatasetFreezeResult:
    replayed = _exact_dataset_freeze_replay(db, payload)
    if replayed is not None:
        return replayed

    refs = sorted(item.case_ref for item in payload.cases)
    expected = {item.case_ref: item.expected_version for item in payload.cases}
    cases = tuple(
        db.scalars(
            select(RealWorldCaseRecord)
            .where(RealWorldCaseRecord.case_ref.in_(refs))
            .order_by(RealWorldCaseRecord.case_ref)
            .with_for_update()
        ).all()
    )
    if len(cases) != len(refs):
        raise RealWorldGovernanceNotFound("冻结目标包含不存在的案例")
    if any(case.record_version != expected[case.case_ref] for case in cases):
        db.rollback()
        raise RealWorldGovernanceConflict("冻结目标版本已变化，请刷新后重试")
    if len(cases) < 20:
        raise RealWorldGovernanceValidationError("冻结数据集至少需要 20 个真实案例")

    current = _now(now)
    snapshots: list[dict] = []
    assets: set[str] = set()
    split_counts: Counter[str] = Counter()
    for case in cases:
        consent = _latest_consent(db, case.id)
        annotation = _latest_annotation(db, case.id)
        blockers = case_freeze_blockers(case, consent, annotation, now=current)
        if blockers:
            raise RealWorldGovernanceValidationError(
                f"案例 {case.case_ref} 尚未满足冻结条件：{','.join(blockers)}"
            )
        if case.asset_digest in assets:
            raise RealWorldGovernanceValidationError("冻结目标包含重复物理资产")
        assets.add(case.asset_digest)
        split_counts[case.split] += 1
        assert consent is not None and annotation is not None
        snapshots.append(
            {
                "case_ref": case.case_ref,
                "record_version": case.record_version,
                "split": case.split,
                "origin": case.origin,
                "asset_digest": case.asset_digest,
                "task_input_digest": case.task_input_digest,
                "redaction_review": case.redaction_review,
                "annotation_digest": annotation.annotation_digest,
                "annotation_revision_id": annotation.id,
                "label_version": annotation.label_version,
                "consent_decision_id": consent.id,
                "consent_evidence_digest": consent.evidence_digest,
                "consent_effective_at": _as_utc(consent.effective_at).isoformat(),
                "consent_expires_at": (
                    _as_utc(consent.expires_at).isoformat()
                    if consent.expires_at is not None
                    else None
                ),
                "allowed_purposes": sorted(consent.allowed_purposes_json),
            }
        )
    required_splits = {"development", "regression", "blind"}
    if set(split_counts) != required_splits:
        raise RealWorldGovernanceValidationError("冻结数据集的三个评测分组必须均非空")

    snapshot = tuple(sorted(snapshots, key=lambda item: item["case_ref"]))
    manifest_digest = _canonical_digest(
        {
            "schema_version": "2.0",
            "dataset_version": payload.dataset_version,
            "cases": snapshot,
        }
    )
    revision = RealWorldDatasetRevision(
        revision_ref=f"rwd_{secrets.token_hex(16)}",
        schema_version="2.0",
        dataset_version=payload.dataset_version,
        manifest_digest=manifest_digest,
        snapshot_json=list(snapshot),
        case_count=len(snapshot),
        created_by_user_id=actor_user_id,
    )
    db.add(revision)
    try:
        db.flush()
        _append_event(
            db,
            case=None,
            actor_user_id=actor_user_id,
            action="dataset_frozen",
            request_id=request_id,
            before_digest=_canonical_digest({"state": "absent"}),
            after_digest=manifest_digest,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replayed = _exact_dataset_freeze_replay(db, payload)
        if replayed is not None:
            return replayed
        raise RealWorldGovernanceConflict("dataset_version 或冻结内容已经存在") from exc
    db.refresh(revision)
    return DatasetFreezeResult(
        revision_ref=revision.revision_ref,
        schema_version=revision.schema_version,
        dataset_version=revision.dataset_version,
        manifest_digest=revision.manifest_digest,
        case_count=revision.case_count,
        split_counts=dict(sorted(split_counts.items())),
        created_at=revision.created_at,
        snapshot=snapshot,
    )


def _exact_dataset_freeze_replay(
    db: Session,
    payload: DatasetFreezeRequest,
) -> DatasetFreezeResult | None:
    """仅对完全相同的冻结请求返回既有不可变结果。"""
    revision = db.scalar(
        select(RealWorldDatasetRevision).where(
            RealWorldDatasetRevision.dataset_version == payload.dataset_version
        )
    )
    if revision is None:
        return None

    raw_snapshot = revision.snapshot_json
    if (
        revision.schema_version != "2.0"
        or not isinstance(raw_snapshot, list)
        or len(raw_snapshot) != revision.case_count
    ):
        raise RealWorldGovernanceValidationError("既有冻结数据集快照结构不合法")

    requested_targets = sorted(
        (item.case_ref, item.expected_version) for item in payload.cases
    )
    try:
        frozen_targets = sorted(
            (str(item["case_ref"]), int(item["record_version"]))
            for item in raw_snapshot
            if isinstance(item, dict)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RealWorldGovernanceValidationError(
            "既有冻结数据集快照目标不合法"
        ) from exc
    if len(frozen_targets) != len(raw_snapshot):
        raise RealWorldGovernanceValidationError("既有冻结数据集快照目标不合法")
    if requested_targets != frozen_targets:
        raise RealWorldGovernanceConflict("dataset_version 已用于不同冻结请求")

    manifest_digest = _canonical_digest(
        {
            "schema_version": revision.schema_version,
            "dataset_version": revision.dataset_version,
            "cases": raw_snapshot,
        }
    )
    if manifest_digest != revision.manifest_digest:
        raise RealWorldGovernanceValidationError("既有冻结数据集摘要校验失败")

    split_counts: Counter[str] = Counter()
    for item in raw_snapshot:
        split = item.get("split")
        if split not in {"development", "regression", "blind"}:
            raise RealWorldGovernanceValidationError("既有冻结数据集分组不合法")
        split_counts[split] += 1
    if set(split_counts) != {"development", "regression", "blind"}:
        raise RealWorldGovernanceValidationError("既有冻结数据集分组不完整")

    return DatasetFreezeResult(
        revision_ref=revision.revision_ref,
        schema_version=revision.schema_version,
        dataset_version=revision.dataset_version,
        manifest_digest=revision.manifest_digest,
        case_count=revision.case_count,
        split_counts=dict(sorted(split_counts.items())),
        created_at=revision.created_at,
        snapshot=tuple(raw_snapshot),
    )


def load_frozen_dataset_for_evaluation(
    db: Session,
    dataset_version: str,
    *,
    upload_root: Path | str,
    now: datetime | None = None,
) -> RealWorldDataset:
    """保留冻结证据与标注；读取资产前整批复核历史证据和当前授权。"""
    revision = db.scalar(
        select(RealWorldDatasetRevision).where(
            RealWorldDatasetRevision.dataset_version == dataset_version
        )
    )
    if revision is None:
        raise RealWorldGovernanceNotFound("冻结数据集不存在")
    raw_snapshot = revision.snapshot_json
    if not isinstance(raw_snapshot, list) or len(raw_snapshot) != revision.case_count:
        raise RealWorldGovernanceValidationError("冻结数据集快照结构不合法")
    expected_manifest = _canonical_digest(
        {
            "schema_version": revision.schema_version,
            "dataset_version": revision.dataset_version,
            "cases": raw_snapshot,
        }
    )
    if expected_manifest != revision.manifest_digest:
        raise RealWorldGovernanceValidationError("冻结数据集摘要不一致")

    current = _now(now)
    reconstructed: list[RealWorldCase] = []
    authorized_cases: list[tuple[dict, RealWorldCaseRecord]] = []
    for frozen in raw_snapshot:
        if not isinstance(frozen, dict):
            raise RealWorldGovernanceValidationError("冻结案例快照结构不合法")
        if frozen.get("redaction_review") != "reviewed":
            raise RealWorldGovernanceValidationError("冻结案例缺少已审核脱敏状态")
        case = db.scalar(
            select(RealWorldCaseRecord).where(
                RealWorldCaseRecord.case_ref == frozen.get("case_ref")
            )
        )
        if case is None or case.origin != "private_real":
            raise RealWorldGovernanceValidationError("冻结案例来源记录不存在")
        latest_consent = _latest_consent(db, case.id)
        if (
            _consent_status(latest_consent, now=current) != "granted"
            or "offline_evaluation" not in (latest_consent.allowed_purposes_json or [])
        ):
            raise RealWorldGovernanceValidationError("冻结案例当前授权已失效或用途不允许")
        if case.asset_digest != frozen.get("asset_digest"):
            raise RealWorldGovernanceValidationError("冻结案例资产摘要已变化")
        if case.task_input_digest != frozen.get("task_input_digest") or (
            _canonical_digest(case.task_input_json) != frozen.get("task_input_digest")
        ):
            raise RealWorldGovernanceValidationError("冻结案例任务输入摘要不一致")
        consent = db.get(RealWorldConsentDecision, frozen.get("consent_decision_id"))
        if consent is None or consent.case_id != case.id:
            raise RealWorldGovernanceValidationError("冻结案例授权证据不存在")
        if (
            consent.decision != "granted"
            or consent.evidence_digest != frozen.get("consent_evidence_digest")
            or _as_utc(consent.effective_at).isoformat()
            != frozen.get("consent_effective_at")
            or (
                _as_utc(consent.expires_at).isoformat()
                if consent.expires_at is not None
                else None
            )
            != frozen.get("consent_expires_at")
            or sorted(consent.allowed_purposes_json) != frozen.get("allowed_purposes")
            or _consent_status(consent, now=current) != "granted"
            or "offline_evaluation" not in consent.allowed_purposes_json
        ):
            raise RealWorldGovernanceValidationError("冻结案例授权证据不一致或已失效")
        authorized_cases.append((frozen, case))

    for frozen, case in authorized_cases:
        image = db.get(UploadedImage, case.uploaded_image_id)
        if image is None:
            raise RealWorldGovernanceValidationError("冻结案例受控图片不存在")
        asset_path = _controlled_upload_path(image, upload_root)
        if _file_digest(asset_path) != frozen.get("asset_digest"):
            raise RealWorldGovernanceValidationError("冻结案例资产文件摘要不一致")

        annotation_row = db.get(
            RealWorldAnnotationRevision, frozen.get("annotation_revision_id")
        )
        if annotation_row is None or annotation_row.case_id != case.id:
            raise RealWorldGovernanceValidationError("冻结案例标注修订不存在")
        if annotation_row.annotation_digest != frozen.get(
            "annotation_digest"
        ) or _canonical_digest(annotation_row.annotation_json) != frozen.get(
            "annotation_digest"
        ):
            raise RealWorldGovernanceValidationError("冻结案例标注摘要不一致")
        try:
            annotation = CaseAnnotation.model_validate(annotation_row.annotation_json)
        except ValueError as exc:
            raise RealWorldGovernanceValidationError("冻结案例标注结构不合法") from exc
        if (
            annotation.case_id != case.case_ref
            or annotation.label_version != frozen.get("label_version")
            or annotation.source_asset_sha256
            != case.asset_digest.removeprefix("sha256:")
        ):
            raise RealWorldGovernanceValidationError("冻结案例标注绑定不一致")
        annotation_file_digest = annotation_row.annotation_digest.removeprefix(
            "sha256:"
        )
        annotation = annotation.model_copy(
            update={"file_sha256": annotation_file_digest}
        )

        reconstructed.append(
            RealWorldCase(
                id=case.case_ref,
                name="匿名真实案例",
                split=frozen["split"],
                origin="private_real",
                asset_path=asset_path,
                consent_status="granted",
                annotation_status="ready",
                label_version=annotation.label_version,
                allowed_purposes=tuple(frozen["allowed_purposes"]),
                failure_tags=(),
                asset_sha256=case.asset_digest.removeprefix("sha256:"),
                task_input=case.task_input_json,
                annotation_sha256=annotation_file_digest,
                annotation=annotation,
            )
        )
    return RealWorldDataset(
        schema_version="2.0",
        dataset_version=revision.dataset_version,
        cases=tuple(reconstructed),
        governance_manifest_digest=revision.manifest_digest,
    )
