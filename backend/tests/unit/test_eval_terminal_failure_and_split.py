import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.core.config import settings
from app.db.models import DesignTask, EvaluationRunBinding, GenerationRunEvent, UploadedImage
from app.services import design_version_service, generation_run_service
from evals.real_world import EvaluationInputError, load_case_manifest
from evals.run_real_world_eval import build_evaluation_report, compare_evaluation_reports
from evals.trusted_evidence import (
    RunBinding,
    bind_evaluation_run,
    collect_trusted_evidence,
    dataset_fingerprint,
    verify_trusted_evidence,
)
from tests.real_world_fixtures import (
    frozen_catalog_quote_line,
    frozen_catalog_suggestion,
    write_v2_manifest,
)
from tests.scene_fixtures import attach_scene_versions


SIGNING_KEY = "split-test-signing-key-that-is-longer-than-32-bytes"


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _dataset(tmp_path: Path, splits: tuple[str, ...]):
    cases = []
    for index, split in enumerate(splits, start=1):
        asset = tmp_path / f"room-{index}.png"
        asset.write_bytes(f"authorized-room-{index}".encode())
        cases.append(
            {
                "id": f"case-{index}",
                "name": "匿名案例",
                "split": split,
                "origin": "private_real",
                "asset_path": asset.name,
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
                    "image_context": [],
                },
            }
        )
    manifest = write_v2_manifest(
        tmp_path,
        filename="manifest.json",
        dataset_version="dataset-v1",
        cases=cases,
    )
    return load_case_manifest(manifest)


def _task(db: Session, case) -> DesignTask:
    task = DesignTask(
        status="confirmed",
        progress=50,
        raw_user_input="需要现代客厅",
        confirmed_requirement_json={"style": "现代"},
        space_type="客厅",
        style="现代",
        budget_min=10000,
        budget_max=20000,
    )
    db.add(task)
    db.flush()
    db.add(
        UploadedImage(
            task_id=task.id,
            file_url=f"/uploads/{case.id}.png",
            content_digest=f"sha256:{case.asset_sha256}",
        )
    )
    db.commit()
    return task


def _finish_success(db: Session, run, task: DesignTask) -> None:
    now = datetime.now(timezone.utc)
    run.attempt_count = 1
    run.started_at = now
    run.output_snapshot = {
        "plan_count": 1,
        "plans": [{"furniture_count": 2}],
    }
    suggestion = frozen_catalog_suggestion()
    revision = design_version_service.persist_generation(
        db,
        task=task,
        generator="llm",
        plans=[
            {
                "id": "plan-eval",
                "name": "匿名方案",
                "style": "现代",
                "furnitureSuggestions": [suggestion],
                "shopQuote": {
                    "furnitureTotal": 10000,
                    "customTotal": 0,
                    "total": 10000,
                    "lineItems": [
                        frozen_catalog_quote_line(suggestion)
                    ],
                    "customLineItems": [],
                },
            }
        ],
    )
    attach_scene_versions(db, revision)
    for node, source in (
        ("prepare_context", None),
        ("generate_plans", "llm"),
        ("calculate_quote", "deterministic"),
        ("validate_quality", "deterministic"),
    ):
        db.add(
            GenerationRunEvent(
                run_id=run.id,
                node=node,
                status="completed",
                progress=100,
                source=source,
            )
        )
    assert generation_run_service.mark_completed(
        db,
        run=run,
        generator="llm",
        result_revision_id=revision.id,
        now=now,
    )


def _finish_failure(db: Session, run, task: DesignTask) -> None:
    now = datetime.now(timezone.utc)
    run.status = "cost_limit_exceeded"
    run.current_node = "cost_limit_exceeded"
    run.attempt_count = 1
    run.started_at = now
    run.completed_at = now
    task.status = "needs_human"
    db.commit()


def _finish_cancelled(db: Session, run, task: DesignTask) -> None:
    assert generation_run_service.request_cancel(db, run=run) == "cancelled"
    db.refresh(task)
    assert run.attempt_count == 0
    assert run.started_at is None
    assert task.status == "cancelled"


def test_binding_freezes_split_and_versions_before_worker_execution(db, tmp_path):
    dataset = _dataset(tmp_path, ("regression",))
    case = dataset.eligible_cases("regression")[0]
    task = _task(db, case)

    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )
    binding = db.query(EvaluationRunBinding).filter_by(generation_run_id=run.id).one()

    assert binding.dataset_split == "regression"
    assert run.status == "queued"
    assert run.generator == "llm"
    assert run.model
    assert run.prompt_snapshot
    assert run.input_snapshot
    assert run.prompt_digest.startswith("sha256:")
    assert run.rules_digest.startswith("sha256:")
    assert run.data_digest.startswith("sha256:")
    assert run.input_digest.startswith("sha256:")


def test_trusted_terminal_failure_is_in_generation_success_denominator(db, tmp_path):
    dataset = _dataset(tmp_path, ("regression", "regression"))
    runs = []
    tasks = []
    for case in dataset.eligible_cases("regression"):
        task = _task(db, case)
        run = bind_evaluation_run(
            db,
            dataset=dataset,
            split="regression",
            case_id=case.id,
            task=task,
        )
        runs.append(run)
        tasks.append(task)
    _finish_success(db, runs[0], tasks[0])
    _finish_failure(db, runs[1], tasks[1])

    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=tuple(
            RunBinding(case.id, run.task_id, run.id)
            for case, run in zip(dataset.eligible_cases("regression"), runs)
        ),
        signing_key=SIGNING_KEY,
        key_id="quality-ci",
    )
    evidence = verify_trusted_evidence(
        bundle,
        dataset=dataset,
        split="regression",
        verification_keys={"quality-ci": SIGNING_KEY},
    )
    report = build_evaluation_report(
        dataset=dataset,
        split="regression",
        evidence=evidence,
    )

    assert bundle["split"] == "regression"
    assert sorted(item["status"] for item in bundle["executions"]) == [
        "completed",
        "cost_limit_exceeded",
    ]
    assert report["metrics"]["generation_success_rate"] == 0.5
    assert report["metrics"]["retry_bound_checks"] == 2
    assert report["metrics"]["unbounded_retry_cases"] == 0


def test_cancelled_eval_run_is_counted_as_generation_failure(db, tmp_path):
    dataset = _dataset(tmp_path, ("regression", "regression"))
    cases = dataset.eligible_cases("regression")
    tasks = [_task(db, case) for case in cases]
    runs = [
        bind_evaluation_run(
            db,
            dataset=dataset,
            split="regression",
            case_id=case.id,
            task=task,
        )
        for case, task in zip(cases, tasks)
    ]
    _finish_success(db, runs[0], tasks[0])
    _finish_cancelled(db, runs[1], tasks[1])

    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=tuple(
            RunBinding(case.id, run.task_id, run.id)
            for case, run in zip(cases, runs)
        ),
        signing_key=SIGNING_KEY,
        key_id="quality-ci",
    )
    evidence = verify_trusted_evidence(
        bundle,
        dataset=dataset,
        split="regression",
        verification_keys={"quality-ci": SIGNING_KEY},
    )
    report = build_evaluation_report(
        dataset=dataset,
        split="regression",
        evidence=evidence,
    )

    assert report["metrics"]["generation_success_rate"] == 0.5
    assert report["metrics"]["retry_bound_checks"] == 2
    assert report["metrics"]["unbounded_retry_cases"] == 0
    assert any(item["status"] == "cancelled" for item in bundle["executions"])


def test_retry_boundary_violation_is_derived_from_persisted_attempts(db, tmp_path):
    dataset = _dataset(tmp_path, ("regression",))
    case = dataset.eligible_cases("regression")[0]
    task = _task(db, case)
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )
    _finish_failure(db, run, task)
    run.max_attempts = 3
    run.attempt_count = 4
    db.commit()

    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=(RunBinding(case.id, run.task_id, run.id),),
        signing_key=SIGNING_KEY,
        key_id="quality-ci",
    )
    result = bundle["executions"][0]["result"]

    assert result["retry_bound_checks"] == 1
    assert result["unbounded_retry_detected"] is True


@pytest.mark.parametrize(
    ("max_attempts", "attempt_count"),
    [(0, 1), (3, -1)],
)
def test_retry_boundary_rejects_invalid_persisted_counters(
    db,
    tmp_path,
    max_attempts,
    attempt_count,
):
    dataset = _dataset(tmp_path, ("regression",))
    case = dataset.eligible_cases("regression")[0]
    task = _task(db, case)
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )
    _finish_failure(db, run, task)
    run.max_attempts = max_attempts
    run.attempt_count = attempt_count
    db.commit()

    with pytest.raises(EvaluationInputError, match="重试边界"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            split="regression",
            bindings=(RunBinding(case.id, run.task_id, run.id),),
            signing_key=SIGNING_KEY,
            key_id="quality-ci",
        )


def test_cancelled_before_start_rejects_impossible_persisted_events(db, tmp_path):
    dataset = _dataset(tmp_path, ("regression",))
    case = dataset.eligible_cases("regression")[0]
    task = _task(db, case)
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )
    _finish_cancelled(db, run, task)
    db.add(
        GenerationRunEvent(
            run_id=run.id,
            node="prepare_context",
            status="completed",
            progress=20,
        )
    )
    db.commit()

    with pytest.raises(EvaluationInputError, match="重试事件"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            split="regression",
            bindings=(RunBinding(case.id, run.task_id, run.id),),
            signing_key=SIGNING_KEY,
            key_id="quality-ci",
        )


@pytest.mark.parametrize(
    ("run_status", "task_status"),
    [
        ("completed", "failed"),
        ("failed", "needs_human"),
        ("dead_letter", "completed"),
        ("cost_limit_exceeded", "failed"),
        ("provider_unavailable", "cancelled"),
        ("cancelled", "needs_human"),
    ],
)
def test_collector_rejects_run_and_task_terminal_mismatch(
    db,
    tmp_path,
    run_status,
    task_status,
):
    dataset = _dataset(tmp_path, ("regression",))
    case = dataset.eligible_cases("regression")[0]
    task = _task(db, case)
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )
    now = datetime.now(timezone.utc)
    run.status = run_status
    run.current_node = run_status
    run.attempt_count = 1
    run.started_at = now
    run.completed_at = now
    task.status = task_status
    if run_status == "completed":
        run.output_snapshot = {
            "plan_count": 1,
            "plans": [{"furniture_count": 1}],
        }
    db.commit()

    with pytest.raises(EvaluationInputError, match="终态不一致"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            split="regression",
            bindings=(RunBinding(case.id, task.id, run.id),),
            signing_key=SIGNING_KEY,
            key_id="quality-ci",
        )


def test_split_is_required_and_cannot_be_mixed_or_compared(db, tmp_path):
    dataset = _dataset(tmp_path, ("regression", "blind"))
    regression_case = dataset.eligible_cases("regression")[0]
    blind_case = dataset.eligible_cases("blind")[0]
    regression_task = _task(db, regression_case)

    with pytest.raises(EvaluationInputError, match="split"):
        bind_evaluation_run(
            db,
            dataset=dataset,
            split="regression",
            case_id=blind_case.id,
            task=regression_task,
        )

    assert dataset_fingerprint(dataset, split="regression") != dataset_fingerprint(
        dataset,
        split="blind",
    )

    candidate = {
        "schema_version": "3.0",
        "split": "regression",
        "versions": {"data": "sha256:" + "1" * 64},
        "dataset": {},
        "evidence": {
            "trust_level": "system_execution",
            "signature_verified": True,
            "dataset_fingerprint": "sha256:" + "2" * 64,
            "case_fingerprints": ["sha256:" + "3" * 64],
        },
        "metrics": {},
    }
    baseline = json.loads(json.dumps(candidate))
    baseline["split"] = "blind"

    with pytest.raises(EvaluationInputError, match="split"):
        compare_evaluation_reports(candidate, baseline)


def test_changed_model_version_creates_a_distinct_eval_run(
    db,
    tmp_path,
    monkeypatch,
):
    dataset = _dataset(tmp_path, ("regression",))
    case = dataset.eligible_cases("regression")[0]
    task = _task(db, case)
    first = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )
    first.status = "failed"
    db.commit()

    monkeypatch.setattr(settings, "llm_model", settings.llm_model + "-candidate")
    second = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )

    assert second.id != first.id
    assert second.idempotency_key != first.idempotency_key
    assert second.request_digest != first.request_digest


def test_worker_claim_rejects_generation_artifact_changed_after_binding(
    db,
    tmp_path,
    monkeypatch,
):
    dataset = _dataset(tmp_path, ("regression",))
    case = dataset.eligible_cases("regression")[0]
    task = _task(db, case)
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )

    monkeypatch.setattr(settings, "llm_model", settings.llm_model + "-changed")
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
