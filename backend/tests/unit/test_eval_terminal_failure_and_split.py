import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import DesignTask, EvaluationRunBinding, GenerationRunEvent, UploadedImage
from evals.real_world import EvaluationInputError, load_case_manifest
from evals.run_real_world_eval import build_evaluation_report, compare_evaluation_reports
from evals.trusted_evidence import (
    RunBinding,
    bind_evaluation_run,
    collect_trusted_evidence,
    dataset_fingerprint,
    verify_trusted_evidence,
)


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
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "dataset_version": "dataset-v1",
                "cases": cases,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
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
    run.status = "completed"
    run.current_node = "completed"
    run.attempt_count = 1
    run.started_at = now
    run.completed_at = now
    run.output_snapshot = {
        "plan_count": 1,
        "plans": [{"furniture_count": 2}],
    }
    task.status = "completed"
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
    db.commit()


def _finish_failure(db: Session, run, task: DesignTask) -> None:
    now = datetime.now(timezone.utc)
    run.status = "cost_limit_exceeded"
    run.current_node = "cost_limit_exceeded"
    run.attempt_count = 1
    run.started_at = now
    run.completed_at = now
    task.status = "needs_human"
    db.commit()


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
    assert [item["status"] for item in bundle["executions"]] == [
        "completed",
        "cost_limit_exceeded",
    ]
    assert report["metrics"]["generation_success_rate"] == 0.5


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
