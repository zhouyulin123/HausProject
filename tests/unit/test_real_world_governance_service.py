from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import (
    DesignTask,
    GovernanceEvent,
    RealWorldDatasetRevision,
    RealWorldCaseRecord,
    RealWorldConsentDecision,
    UploadedImage,
    User,
)
from app.schemas.real_world_governance import (
    AnnotationRevisionCreate,
    CaseGovernanceUpdate,
    CaseImportRequest,
    ConsentDecisionCreate,
    DatasetFreezeRequest,
    DatasetFreezeTarget,
    DatasetRevisionResponse,
)
from app.services.real_world_governance_service import (
    RealWorldGovernanceConflict,
    RealWorldGovernanceValidationError,
    add_annotation_revision,
    add_consent_decision,
    create_case_import,
    freeze_dataset_revision,
    list_case_records,
    load_frozen_dataset_for_evaluation,
    preview_case_import,
    update_case_governance,
)
from evals.trusted_evidence import dataset_fingerprint


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def governance_db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'governance.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    try:
        with factory() as db:
            admin = User(
                id=7101,
                phone="13800007101",
                role="admin",
                phone_verified=True,
            )
            task = DesignTask(
                id=7201,
                user_id=None,
                status="confirmed",
                raw_user_input="已脱敏的客厅设计需求",
                confirmed_requirement_json={"space_type": "客厅"},
                space_type="客厅",
                style="现代简约",
                budget_min=10000,
                budget_max=30000,
            )
            content = b"deidentified-real-room"
            (upload_root / "case-1.png").write_bytes(content)
            image = UploadedImage(
                id=7301,
                task_id=task.id,
                file_url="/uploads/case-1.png",
                file_name="case-1.png",
                content_digest="sha256:" + hashlib.sha256(content).hexdigest(),
                analysis_json={"findings": ["客厅宽约 4 米"]},
            )
            db.add_all([admin, task, image])
            db.commit()
        yield factory, upload_root
    finally:
        engine.dispose()


def _import_request(import_id: str = "import-001") -> CaseImportRequest:
    return CaseImportRequest(
        client_import_id=import_id,
        task_id=7201,
        uploaded_image_id=7301,
    )


def _annotation(case_ref: str, asset_digest: str, version: int):
    return AnnotationRevisionCreate(
        expected_version=version,
        annotation={
            "schema_version": "1.0",
            "annotation_type": "real_world_case_annotation",
            "case_id": case_ref,
            "label_version": "labels-2026-09-10.1",
            "source_asset_sha256": asset_digest.removeprefix("sha256:"),
            "requirements": [{"field": "space_type", "value": "客厅"}],
            "space_facts": [
                {
                    "fact_path": "rooms.living.width_m",
                    "value": 4.0,
                    "confidence": 1.0,
                    "requires_confirmation": False,
                }
            ],
            "allowed_skus": ["SOFA-001"],
            "budget": {"currency": "CNY", "min": 10000, "max": 30000},
            "layout_hard_constraints": [
                {
                    "constraint_id": "sofa-inside-room",
                    "type": "inside_room",
                    "room_id": "living",
                    "subject_id": "sofa-main",
                    "related_id": None,
                    "operator": "eq",
                    "value": True,
                    "unit": "boolean",
                }
            ],
            "style_tags": ["现代简约"],
        },
    )


def _grant(version: int, *, expires_at: datetime | None = None):
    return ConsentDecisionCreate(
        expected_version=version,
        decision="granted",
        legal_basis="explicit_consent",
        allowed_purposes=["offline_evaluation"],
        evidence_digest="sha256:" + "e" * 64,
        effective_at=NOW - timedelta(days=1),
        expires_at=expires_at or NOW + timedelta(days=30),
    )


def test_preview_is_read_only_and_recomputes_asset_and_task_input(governance_db):
    factory, upload_root = governance_db
    expected_asset_digest = "sha256:" + hashlib.sha256(
        b"deidentified-real-room"
    ).hexdigest()

    with factory() as db:
        preview = preview_case_import(db, _import_request(), upload_root=upload_root)

        assert preview.asset_digest == expected_asset_digest
        assert preview.task_input["confirmed_requirement"] == {"space_type": "客厅"}
        assert db.scalar(select(RealWorldCaseRecord)) is None
        assert db.scalar(select(GovernanceEvent)) is None


def test_preview_fails_closed_when_stored_asset_digest_does_not_match(governance_db):
    factory, upload_root = governance_db
    with factory() as db:
        image = db.get(UploadedImage, 7301)
        assert image is not None
        image.content_digest = "sha256:" + "0" * 64
        db.commit()

        with pytest.raises(RealWorldGovernanceValidationError, match="摘要"):
            preview_case_import(db, _import_request(), upload_root=upload_root)


@pytest.mark.parametrize("file_url", ["/uploads/../outside.png", "/uploads/missing.png"])
def test_preview_rejects_path_escape_and_missing_controlled_asset(
    governance_db,
    file_url,
):
    factory, upload_root = governance_db
    (upload_root.parent / "outside.png").write_bytes(b"outside")
    with factory() as db:
        image = db.get(UploadedImage, 7301)
        assert image is not None
        image.file_url = file_url
        db.commit()

        with pytest.raises(RealWorldGovernanceValidationError, match="受控"):
            preview_case_import(db, _import_request(), upload_root=upload_root)


def test_import_is_idempotent_and_rejects_same_key_with_changed_input(governance_db):
    factory, upload_root = governance_db
    with factory() as db:
        first = create_case_import(
            db,
            _import_request(),
            actor_user_id=7101,
            request_id="request-import-1",
            upload_root=upload_root,
        )
        duplicate = create_case_import(
            db,
            _import_request(),
            actor_user_id=7101,
            request_id="request-import-2",
            upload_root=upload_root,
        )

        assert first.created is True
        assert duplicate.created is False
        assert duplicate.case.case_ref == first.case.case_ref
        assert db.query(RealWorldCaseRecord).count() == 1
        assert db.query(GovernanceEvent).count() == 1

        task = db.get(DesignTask, 7201)
        assert task is not None
        task.style = "原木"
        db.commit()
        with pytest.raises(RealWorldGovernanceConflict, match="client_import_id"):
            create_case_import(
                db,
                _import_request(),
                actor_user_id=7101,
                request_id="request-import-3",
                upload_root=upload_root,
            )


def test_different_import_cannot_reuse_the_same_physical_asset(governance_db):
    factory, upload_root = governance_db
    with factory() as db:
        create_case_import(
            db,
            _import_request("import-first"),
            actor_user_id=7101,
            request_id="request-first",
            upload_root=upload_root,
        )
        with pytest.raises(RealWorldGovernanceConflict, match="物理资产"):
            create_case_import(
                db,
                _import_request("import-second"),
                actor_user_id=7101,
                request_id="request-second",
                upload_root=upload_root,
            )


def test_list_projection_is_anonymous_and_contains_only_derived_states(governance_db):
    factory, upload_root = governance_db
    with factory() as db:
        created = create_case_import(
            db,
            _import_request(),
            actor_user_id=7101,
            request_id="request-import",
            upload_root=upload_root,
        )
        items = list_case_records(db, now=NOW)

        assert len(items) == 1
        payload = items[0]
        assert payload.case_ref == created.case.case_ref
        assert payload.consent_status == "pending"
        assert payload.annotation_status == "pending"
        assert set(payload.blockers) == {
            "redaction_not_reviewed",
            "consent_not_granted",
            "annotation_not_ready",
            "split_not_assigned",
        }
        serialized = payload.model_dump(mode="json")
        for forbidden in (
            "asset_path",
            "file_url",
            "asset_digest",
            "task_input",
            "user_id",
            "evidence_digest",
            "annotation",
        ):
            assert forbidden not in serialized


def test_consent_annotation_redaction_and_split_are_cas_guarded(governance_db):
    factory, upload_root = governance_db
    with factory() as db:
        imported = create_case_import(
            db,
            _import_request(),
            actor_user_id=7101,
            request_id="request-import",
            upload_root=upload_root,
        )
        case = imported.case

        case = update_case_governance(
            db,
            case.case_ref,
            CaseGovernanceUpdate(expected_version=1, redaction_review="reviewed"),
            actor_user_id=7101,
            request_id="request-redaction",
        )
        with pytest.raises(RealWorldGovernanceConflict, match="版本"):
            update_case_governance(
                db,
                case.case_ref,
                CaseGovernanceUpdate(expected_version=1, split="development"),
                actor_user_id=7101,
                request_id="request-stale",
            )
        case = add_consent_decision(
            db,
            case.case_ref,
            _grant(case.record_version),
            actor_user_id=7101,
            request_id="request-consent",
            now=NOW,
        )
        case = add_annotation_revision(
            db,
            case.case_ref,
            _annotation(case.case_ref, case.asset_digest, case.record_version),
            actor_user_id=7101,
            request_id="request-annotation",
        )
        case = update_case_governance(
            db,
            case.case_ref,
            CaseGovernanceUpdate(
                expected_version=case.record_version,
                split="development",
            ),
            actor_user_id=7101,
            request_id="request-split",
        )

        item = list_case_records(db, now=NOW)[0]
        assert item.record_version == case.record_version == 5
        assert item.consent_status == "granted"
        assert item.annotation_status == "ready"
        assert item.blockers == []
        events = db.scalars(select(GovernanceEvent).order_by(GovernanceEvent.id)).all()
        assert [event.action for event in events] == [
            "case_imported",
            "redaction_reviewed",
            "consent_granted",
            "annotation_added",
            "split_assigned",
        ]
        assert all(event.actor_user_id == 7101 for event in events)
        assert all("客厅" not in event.before_digest for event in events)
        assert all("客厅" not in event.after_digest for event in events)


def test_granted_consent_requires_evidence_purpose_and_valid_window(governance_db):
    factory, upload_root = governance_db
    with factory() as db:
        case = create_case_import(
            db,
            _import_request(),
            actor_user_id=7101,
            request_id="request-import",
            upload_root=upload_root,
        ).case
        base = _grant(case.record_version).model_dump()

        for override in (
            {"evidence_digest": None},
            {"allowed_purposes": []},
        ):
            with pytest.raises(ValueError):
                ConsentDecisionCreate.model_validate(base | override)
        expired = ConsentDecisionCreate.model_validate(
            base
            | {
                "effective_at": NOW - timedelta(days=2),
                "expires_at": NOW - timedelta(seconds=1),
            }
        )
        with pytest.raises(RealWorldGovernanceValidationError, match="过期"):
            add_consent_decision(
                db,
                case.case_ref,
                expired,
                actor_user_id=7101,
                request_id="request-expired-consent",
                now=NOW,
            )


@pytest.mark.parametrize(
    "override",
    [
        {"decision": "denied", "legal_basis": "explicit_consent", "evidence_digest": None},
        {"decision": "revoked", "legal_basis": "withdrawal_request", "evidence_digest": None},
        {"decision": "revoked", "legal_basis": "contract"},
        {"decision": "denied", "legal_basis": "withdrawal_request"},
    ],
)
def test_every_consent_decision_requires_compatible_evidence(override):
    values = {
        "expected_version": 1,
        "decision": "denied",
        "legal_basis": "explicit_consent",
        "allowed_purposes": [],
        "evidence_digest": "sha256:" + "d" * 64,
        "effective_at": NOW,
        "expires_at": None,
    }
    with pytest.raises(ValueError):
        ConsentDecisionCreate.model_validate(values | override)


def test_revocation_is_append_only_and_immediately_blocks_case(governance_db):
    factory, upload_root = governance_db
    with factory() as db:
        case = create_case_import(
            db,
            _import_request(),
            actor_user_id=7101,
            request_id="request-import",
            upload_root=upload_root,
        ).case
        case = add_consent_decision(
            db,
            case.case_ref,
            _grant(case.record_version),
            actor_user_id=7101,
            request_id="request-grant",
            now=NOW,
        )
        case = add_consent_decision(
            db,
            case.case_ref,
            ConsentDecisionCreate(
                expected_version=case.record_version,
                decision="revoked",
                legal_basis="withdrawal_request",
                allowed_purposes=[],
                evidence_digest="sha256:" + "f" * 64,
                effective_at=NOW,
                expires_at=None,
            ),
            actor_user_id=7101,
            request_id="request-revoke",
            now=NOW,
        )

        decisions = db.scalars(
            select(RealWorldConsentDecision).order_by(RealWorldConsentDecision.id)
        ).all()
        assert [item.decision for item in decisions] == ["granted", "revoked"]
        item = list_case_records(db, now=NOW)[0]
        assert item.consent_status == "revoked"
        assert "consent_not_granted" in item.blockers


def test_annotation_is_bound_to_case_and_server_recomputed_asset_digest(governance_db):
    factory, upload_root = governance_db
    with factory() as db:
        case = create_case_import(
            db,
            _import_request(),
            actor_user_id=7101,
            request_id="request-import",
            upload_root=upload_root,
        ).case
        invalid = _annotation(case.case_ref, "sha256:" + "9" * 64, case.record_version)

        with pytest.raises(RealWorldGovernanceValidationError, match="资产摘要"):
            add_annotation_revision(
                db,
                case.case_ref,
                invalid,
                actor_user_id=7101,
                request_id="request-annotation",
            )


def test_freeze_requires_twenty_unique_private_cases_and_all_splits(governance_db):
    factory, _upload_root = governance_db
    with factory() as db:
        with pytest.raises(RealWorldGovernanceValidationError, match="至少需要 20"):
            freeze_dataset_revision(
                db,
                DatasetFreezeRequest(
                    dataset_version="dataset-2026-09-10.1",
                    cases=[],
                ),
                actor_user_id=7101,
                request_id="request-freeze",
                now=NOW,
            )


def test_dataset_freeze_rejects_stale_case_versions(governance_db):
    factory, upload_root = governance_db
    with factory() as db:
        case = create_case_import(
            db,
            _import_request(),
            actor_user_id=7101,
            request_id="request-import",
            upload_root=upload_root,
        ).case
        with pytest.raises(RealWorldGovernanceConflict, match="版本"):
            freeze_dataset_revision(
                db,
                DatasetFreezeRequest(
                    dataset_version="dataset-2026-09-10.1",
                    cases=[
                        DatasetFreezeTarget(
                            case_ref=case.case_ref,
                            expected_version=case.record_version + 1,
                        )
                    ],
                ),
                actor_user_id=7101,
                request_id="request-freeze",
                now=NOW,
            )
        assert db.scalar(select(RealWorldDatasetRevision)) is None
        assert db.scalar(
            select(GovernanceEvent).where(GovernanceEvent.action == "dataset_frozen")
        ) is None


def test_dataset_freeze_creates_an_immutable_digest_only_snapshot(governance_db):
    factory, upload_root = governance_db
    targets: list[DatasetFreezeTarget] = []
    with factory() as db:
        for index in range(20):
            task_id = 9000 + index
            image_id = 10000 + index
            content = f"deidentified-room-{index}".encode()
            filename = f"ready-{index}.png"
            (upload_root / filename).write_bytes(content)
            task = DesignTask(
                id=task_id,
                status="confirmed",
                raw_user_input=f"已脱敏需求 {index}",
                confirmed_requirement_json={"space_type": "客厅"},
                space_type="客厅",
            )
            image = UploadedImage(
                id=image_id,
                task_id=task_id,
                file_url=f"/uploads/{filename}",
                analysis_json={"findings": ["已脱敏空间事实"]},
            )
            db.add_all([task, image])
            db.commit()
            case = create_case_import(
                db,
                CaseImportRequest(
                    client_import_id=f"freeze-import-{index}",
                    task_id=task_id,
                    uploaded_image_id=image_id,
                ),
                actor_user_id=7101,
                request_id=f"request-import-{index}",
                upload_root=upload_root,
            ).case
            case = update_case_governance(
                db,
                case.case_ref,
                CaseGovernanceUpdate(
                    expected_version=case.record_version,
                    redaction_review="reviewed",
                ),
                actor_user_id=7101,
                request_id=f"request-redaction-{index}",
            )
            case = add_consent_decision(
                db,
                case.case_ref,
                _grant(case.record_version),
                actor_user_id=7101,
                request_id=f"request-consent-{index}",
                now=NOW,
            )
            case = add_annotation_revision(
                db,
                case.case_ref,
                _annotation(case.case_ref, case.asset_digest, case.record_version),
                actor_user_id=7101,
                request_id=f"request-annotation-{index}",
            )
            split = ("development", "regression", "blind")[index % 3]
            case = update_case_governance(
                db,
                case.case_ref,
                CaseGovernanceUpdate(
                    expected_version=case.record_version,
                    split=split,
                ),
                actor_user_id=7101,
                request_id=f"request-split-{index}",
            )
            targets.append(
                DatasetFreezeTarget(
                    case_ref=case.case_ref,
                    expected_version=case.record_version,
                )
            )

        revision = freeze_dataset_revision(
            db,
            DatasetFreezeRequest(
                dataset_version="dataset-2026-09-10.20",
                cases=targets,
            ),
            actor_user_id=7101,
            request_id="request-freeze-success",
            now=NOW,
        )

        assert revision.schema_version == "2.0"
        assert revision.case_count == 20
        assert revision.manifest_digest.startswith("sha256:")
        assert set(revision.split_counts) == {"development", "regression", "blind"}
        assert sum(revision.split_counts.values()) == 20
        snapshot_text = str(revision.snapshot)
        assert "已脱敏需求" not in snapshot_text
        assert "task_input_json" not in snapshot_text
        assert "已脱敏空间事实" not in snapshot_text
        assert all(
            {
                "case_ref",
                "record_version",
                "asset_digest",
                "task_input_digest",
                "redaction_review",
                "annotation_digest",
                "consent_evidence_digest",
                "consent_effective_at",
                "consent_expires_at",
            }
            <= set(item)
            for item in revision.snapshot
        )
        assert {item["consent_evidence_digest"] for item in revision.snapshot} == {
            "sha256:" + "e" * 64
        }
        assert {item["redaction_review"] for item in revision.snapshot} == {"reviewed"}

        replayed = freeze_dataset_revision(
            db,
            DatasetFreezeRequest(
                dataset_version="dataset-2026-09-10.20",
                cases=targets,
            ),
            actor_user_id=7101,
            request_id="request-freeze-network-retry",
            now=NOW,
        )
        assert replayed.revision_ref == revision.revision_ref
        assert replayed.manifest_digest == revision.manifest_digest
        assert db.scalar(
            select(func.count(GovernanceEvent.id)).where(
                GovernanceEvent.action == "dataset_frozen"
            )
        ) == 1

        conflicting_targets = list(targets)
        conflicting_targets[0] = conflicting_targets[0].model_copy(
            update={"expected_version": conflicting_targets[0].expected_version + 1}
        )
        with pytest.raises(RealWorldGovernanceConflict, match="不同冻结请求"):
            freeze_dataset_revision(
                db,
                DatasetFreezeRequest(
                    dataset_version="dataset-2026-09-10.20",
                    cases=conflicting_targets,
                ),
                actor_user_id=7101,
                request_id="request-freeze-conflict",
                now=NOW,
            )

        first_target = targets[0]
        first_case = db.scalar(
            select(RealWorldCaseRecord).where(
                RealWorldCaseRecord.case_ref == first_target.case_ref
            )
        )
        assert first_case is not None
        first_case = add_consent_decision(
            db,
            first_case.case_ref,
            _grant(first_case.record_version),
            actor_user_id=7101,
            request_id="request-newer-consent",
            now=NOW,
        )
        newer = _annotation(
            first_case.case_ref,
            first_case.asset_digest,
            first_case.record_version,
        )
        newer.annotation = newer.annotation.model_copy(
            update={"label_version": "labels-2026-09-10.2"}
        )
        add_annotation_revision(
            db,
            first_case.case_ref,
            newer,
            actor_user_id=7101,
            request_id="request-newer-annotation",
        )

        frozen = load_frozen_dataset_for_evaluation(
            db,
            revision.dataset_version,
            upload_root=upload_root,
            now=NOW,
        )
        frozen_first = next(
            case for case in frozen.cases if case.id == first_case.case_ref
        )
        frozen_first_snapshot = next(
            item for item in revision.snapshot if item["case_ref"] == first_case.case_ref
        )
        assert frozen_first.label_version == "labels-2026-09-10.1"
        assert frozen_first.split == frozen_first_snapshot["split"]
        assert frozen.governance_manifest_digest == revision.manifest_digest
        assert dataset_fingerprint(frozen, split=frozen_first.split).startswith("sha256:")
        public_response = DatasetRevisionResponse(
            revision_ref=revision.revision_ref,
            schema_version="2.0",
            dataset_version=revision.dataset_version,
            manifest_digest=revision.manifest_digest,
            case_count=revision.case_count,
            split_counts=revision.split_counts,
            created_at=revision.created_at,
        ).model_dump(mode="json")
        assert "snapshot" not in public_response

        with pytest.raises(RealWorldGovernanceValidationError, match="已失效"):
            load_frozen_dataset_for_evaluation(
                db,
                revision.dataset_version,
                upload_root=upload_root,
                now=NOW + timedelta(days=31),
            )

        (upload_root / "ready-0.png").write_bytes(b"tampered-private-room")
        with pytest.raises(RealWorldGovernanceValidationError, match="资产文件摘要"):
            load_frozen_dataset_for_evaluation(
                db,
                revision.dataset_version,
                upload_root=upload_root,
                now=NOW,
            )
