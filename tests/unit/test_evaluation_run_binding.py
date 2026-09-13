from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import DesignTask, EvaluationRunBinding, UploadedImage
from app.api.routes import tasks as task_routes
from app.services import evaluation_binding_service, generation_run_service
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


def test_budget_replan_preserves_initial_evaluation_input_and_provenance(
    db,
    tmp_path,
    monkeypatch,
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
    frozen = {
        field: deepcopy(getattr(run, field))
        for field in (
            "model",
            "prompt_snapshot",
            "prompt_digest",
            "rules_digest",
            "data_digest",
            "input_snapshot",
            "input_digest",
            "provenance_schema_version",
        )
    }
    assert '"budget_max": 20000' in frozen["input_snapshot"]["user"]
    assert "【本次已确认生成硬约束】" in frozen["input_snapshot"]["user"]
    totals = iter((25_000, 19_000))
    generation_inputs: list[dict] = []

    class BudgetReplanWorkflow:
        def __init__(self, **_):
            pass

        def run(self, *, requirement, **_):
            generation_inputs.append(deepcopy(requirement))
            total = next(totals)
            return {
                "plans": [{
                    "id": "plan-a",
                    "name": "评测预算方案",
                    "style": "现代",
                    "furnitureSuggestions": [{"id": "SOFA-001"}],
                    "shopQuote": {
                        "furnitureTotal": total,
                        "customTotal": 0,
                        "total": total,
                    },
                }],
                "generator": "llm",
                "node_trace": [],
            }

    def current_meta():
        input_snapshot = deepcopy(frozen["input_snapshot"])
        if len(generation_inputs) > 1:
            input_snapshot["budget_replan"] = generation_inputs[-1]["budget_replan"]
        return {
            "model": frozen["model"],
            "prompt_snapshot": frozen["prompt_snapshot"],
            "input_snapshot": input_snapshot,
            "provenance_schema_version": frozen["provenance_schema_version"],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
            "cost_cny": 0.1,
        }

    monkeypatch.setattr(task_routes, "DesignWorkflow", BudgetReplanWorkflow)
    monkeypatch.setattr(task_routes.llm_service, "last_generation_meta", current_meta)

    def persist_meta(payload):
        generation_run_service.record_generation_meta(
            db,
            run=run,
            meta=payload["meta"],
            output_snapshot=payload["output_snapshot"],
        )

    task_routes._execute_generation(
        db,
        task=task,
        on_step=lambda step: generation_run_service.record_step(
            db,
            run=run,
            step=step,
        ),
        on_meta=persist_meta,
    )

    evaluation_binding_service.validate_persisted_binding(db, run=run)
    for field, value in frozen.items():
        assert getattr(run, field) == value
    assert run.usage_json == {
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
    }
    assert run.cost_cny == pytest.approx(0.2)
    assert run.output_snapshot["retry_count"] == 1
    assert [event.node for event in run.events].count("budget_replan") == 1


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
