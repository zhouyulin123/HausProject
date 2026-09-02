import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import DesignTask, EvaluationRunBinding, UploadedImage
from app.services import generation_run_service
from evals.real_world import EvaluationInputError, load_case_manifest
from evals.trusted_evidence import (
    bind_evaluation_run,
    collect_trusted_evidence,
    evaluation_run_idempotency_key,
    RunBinding,
)
from tests.real_world_fixtures import write_v2_manifest


def _dataset(tmp_path: Path, *, image_context: list[str] | None = None):
    (tmp_path / "room.png").write_bytes(b"authorized-test-room")
    manifest = write_v2_manifest(
        tmp_path,
        filename="manifest.json",
        dataset_version="test-data-v1",
        cases=[
            {
                "id": "case-a",
                "name": "测试案例",
                "split": "regression",
                "origin": "private_real",
                "asset_path": "room.png",
                "consent_status": "granted",
                "annotation_status": "ready",
                "label_version": "labels-v1",
                "allowed_purposes": ["offline_evaluation"],
                "failure_tags": [],
                "task_input": {
                    "raw_user_input": "需要现代客厅",
                    "confirmed_requirement": {"style": "现代"},
                    "space_type": "客厅",
                    "style": "现代",
                    "budget_min": 10000,
                    "budget_max": 20000,
                    "image_context": image_context or [],
                },
            }
        ],
    )
    return load_case_manifest(manifest)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _task(db: Session, *, asset_digest: str, style: str = "现代") -> DesignTask:
    task = DesignTask(
        status="confirmed",
        progress=50,
        raw_user_input="需要现代客厅",
        confirmed_requirement_json={"style": style},
        space_type="客厅",
        style=style,
        budget_min=10000,
        budget_max=20000,
    )
    db.add(task)
    db.flush()
    db.add(
        UploadedImage(
            task_id=task.id,
            file_url="/uploads/test-room.png",
            content_digest=asset_digest,
        )
    )
    db.commit()
    return task


def test_binding_rejects_wrong_requirement_and_wrong_uploaded_asset(db, tmp_path):
    dataset = _dataset(tmp_path)
    case = dataset.eligible_cases()[0]
    correct_asset = f"sha256:{case.asset_sha256}"

    wrong_requirement = _task(db, asset_digest=correct_asset, style="轻法式")
    with pytest.raises(EvaluationInputError, match="任务输入"):
        bind_evaluation_run(
            db,
            dataset=dataset,
            split="regression",
            case_id=case.id,
            task=wrong_requirement,
        )

    wrong_asset = _task(db, asset_digest="sha256:" + "0" * 64)
    with pytest.raises(EvaluationInputError, match="案例资产"):
        bind_evaluation_run(
            db,
            dataset=dataset,
            split="regression",
            case_id=case.id,
            task=wrong_asset,
        )

    mixed_assets = _task(db, asset_digest=correct_asset)
    db.add(
        UploadedImage(
            task_id=mixed_assets.id,
            file_url="/uploads/unexpected-room.png",
            content_digest="sha256:" + "1" * 64,
        )
    )
    db.commit()
    with pytest.raises(EvaluationInputError, match="案例资产"):
        bind_evaluation_run(
            db,
            dataset=dataset,
            split="regression",
            case_id=case.id,
            task=mixed_assets,
        )


def test_binding_rejects_correct_asset_mixed_with_unverifiable_legacy_upload(
    db,
    tmp_path,
):
    dataset = _dataset(tmp_path)
    case = dataset.eligible_cases()[0]
    task = _task(db, asset_digest=f"sha256:{case.asset_sha256}")
    db.add(
        UploadedImage(
            task_id=task.id,
            file_url="/uploads/legacy-without-digest.png",
            content_digest=None,
        )
    )
    db.commit()

    with pytest.raises(EvaluationInputError, match="案例资产"):
        bind_evaluation_run(
            db,
            dataset=dataset,
            split="regression",
            case_id=case.id,
            task=task,
        )


def test_eval_idempotency_key_alone_cannot_create_a_run(db, tmp_path):
    dataset = _dataset(tmp_path)
    case = dataset.eligible_cases()[0]
    task = _task(db, asset_digest=f"sha256:{case.asset_sha256}")

    with pytest.raises(ValueError, match="持久化案例绑定"):
        generation_run_service.create_run(
            db,
            task=task,
            idempotency_key=evaluation_run_idempotency_key(
                db,
                dataset=dataset,
                split="regression",
                case_id=case.id,
                task=task,
            ),
        )


def test_worker_claim_revalidates_persisted_binding_and_rejects_task_mutation(
    db,
    tmp_path,
):
    dataset = _dataset(tmp_path)
    case = dataset.eligible_cases()[0]
    task = _task(db, asset_digest=f"sha256:{case.asset_sha256}")
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )

    task.confirmed_requirement_json = {"style": "篡改后的风格"}
    db.commit()
    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="eval-worker",
        lease_seconds=30,
        run_id=run.id,
    )

    assert claimed is None
    db.refresh(run)
    assert run.status == "dead_letter"
    assert run.current_node == "evaluation_binding_invalid"


def test_worker_claim_rejects_image_analysis_mutated_after_binding(db, tmp_path):
    dataset = _dataset(tmp_path, image_context=["绑定时的空间事实"])
    case = dataset.eligible_cases()[0]
    task = _task(db, asset_digest=f"sha256:{case.asset_sha256}")
    image = db.query(UploadedImage).filter_by(task_id=task.id).one()
    image.analysis_json = {"findings": ["绑定时的空间事实"]}
    db.commit()
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )

    image.analysis_json = {"findings": ["执行前被替换的空间事实"]}
    db.commit()
    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="eval-worker",
        lease_seconds=30,
        run_id=run.id,
    )

    assert claimed is None
    db.refresh(run)
    assert run.status == "dead_letter"
    assert run.current_node == "evaluation_binding_invalid"


def test_collector_requires_binding_even_when_idempotency_key_is_correct(db, tmp_path):
    dataset = _dataset(tmp_path)
    case = dataset.eligible_cases()[0]
    task = _task(db, asset_digest=f"sha256:{case.asset_sha256}")
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )
    binding = db.query(EvaluationRunBinding).filter_by(generation_run_id=run.id).one()
    db.delete(binding)
    run.status = "completed"
    task.status = "completed"
    db.commit()

    with pytest.raises(EvaluationInputError, match="持久化评测绑定"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            split="regression",
            bindings=(RunBinding(case.id, task.id, run.id),),
            signing_key="test-signing-key-longer-than-thirty-two-bytes",
            key_id="test-key",
        )
