import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import DesignTask, GenerationRun, GenerationRunEvent
from evals.real_world import EvaluationVersions, load_case_manifest
from evals.run_real_world_eval import (
    EvaluationInputError,
    build_evaluation_report,
    load_case_results,
    main as run_eval_main,
)
from evals.trusted_evidence import (
    RunBinding,
    collect_trusted_evidence,
    dataset_fingerprint,
)


SIGNING_KEY = "eval-test-signing-key-that-is-at-least-32-bytes"


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _dataset(tmp_path: Path):
    (tmp_path / "room.png").write_bytes(b"private-room-bytes")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "dataset_version": "data-2026-09-02",
                "cases": [
                    {
                        "id": "private-case-alias",
                        "name": "不应进入报告的客户别名",
                        "split": "regression",
                        "origin": "private_real",
                        "asset_path": "room.png",
                        "consent_status": "granted",
                        "annotation_status": "ready",
                        "label_version": "labels-3",
                        "allowed_purposes": ["offline_evaluation"],
                        "failure_tags": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return load_case_manifest(manifest)


def _two_case_dataset(tmp_path: Path):
    (tmp_path / "room-a.png").write_bytes(b"private-room-a")
    (tmp_path / "room-b.png").write_bytes(b"private-room-b")
    manifest = tmp_path / "two-cases.json"
    cases = []
    for case_id, suffix in (("private-a", "a"), ("private-b", "b")):
        cases.append(
            {
                "id": case_id,
                "name": "匿名案例",
                "split": "regression",
                "origin": "private_real",
                "asset_path": f"room-{suffix}.png",
                "consent_status": "granted",
                "annotation_status": "ready",
                "label_version": "labels-3",
                "allowed_purposes": ["offline_evaluation"],
                "failure_tags": [],
            }
        )
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "dataset_version": "data-2026-09-02",
                "cases": cases,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return load_case_manifest(manifest)


def _completed_system_run(db: Session, *, generator: str = "llm") -> GenerationRun:
    task = DesignTask(status="completed", progress=100)
    db.add(task)
    db.flush()
    now = datetime.now(timezone.utc)
    run = GenerationRun(
        task_id=task.id,
        attempt=1,
        status="completed",
        progress=100,
        current_node="completed",
        generator=generator,
        model="model-prod-7",
        prompt_snapshot="private prompt content",
        input_snapshot={"private_requirement": "do not serialize"},
        output_snapshot={"plans": [{"private_output": "do not serialize"}]},
        worker_id=None,
        attempt_count=1,
        max_attempts=3,
        started_at=now,
        completed_at=now,
    )
    db.add(run)
    db.flush()
    for index, node in enumerate(
        ("prepare_context", "generate_plans", "calculate_quote", "validate_quality"),
        start=1,
    ):
        db.add(
            GenerationRunEvent(
                run_id=run.id,
                node=node,
                status="completed",
                progress=index * 20,
                source="worker",
            )
        )
    db.commit()
    db.refresh(run)
    return run


def _write_bundle(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_dataset_fingerprint_binds_asset_bytes_and_case_governance(tmp_path):
    dataset = _dataset(tmp_path)
    first = dataset_fingerprint(dataset)

    dataset.cases[0].asset_path.write_bytes(b"changed-room-bytes")
    second = dataset_fingerprint(dataset)

    assert first.startswith("sha256:")
    assert first != second


def test_collector_binds_real_run_versions_and_redacts_private_payload(db, tmp_path):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(db)

    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        bindings=(
            RunBinding(
                case_id="private-case-alias",
                task_id=run.task_id,
                system_run_id=run.id,
            ),
        ),
        versions=EvaluationVersions(
            model="model-prod-7",
            prompt="prompt-12",
            rules="rules-8",
            data=dataset.dataset_version,
        ),
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
    )

    serialized = json.dumps(bundle, ensure_ascii=False)
    execution = bundle["executions"][0]
    assert bundle["schema_version"] == "2.0"
    assert bundle["dataset_fingerprint"] == dataset_fingerprint(dataset)
    assert execution["task_id"] == run.task_id
    assert execution["system_run_id"] == run.id
    assert execution["model"] == run.model
    assert execution["output_digest"].startswith("sha256:")
    assert execution["result_digest"].startswith("sha256:")
    assert "private-case-alias" not in serialized
    assert "private prompt content" not in serialized
    assert "private_requirement" not in serialized
    assert "private_output" not in serialized


@pytest.mark.parametrize(
    "generator",
    ["manual", "mock", "test", "synthetic", "demo", "template"],
)
def test_collector_rejects_non_system_execution_sources(db, tmp_path, generator):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(db, generator=generator)

    with pytest.raises(EvaluationInputError, match="不可信的执行来源"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
            versions=EvaluationVersions(
                model="model-prod-7",
                prompt="prompt-12",
                rules="rules-8",
                data=dataset.dataset_version,
            ),
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )


def test_collector_rejects_task_mismatch_incomplete_run_and_run_replay(db, tmp_path):
    dataset = _two_case_dataset(tmp_path)
    run = _completed_system_run(db)
    versions = EvaluationVersions(
        model="model-prod-7",
        prompt="prompt-12",
        rules="rules-8",
        data=dataset.dataset_version,
    )

    with pytest.raises(EvaluationInputError, match="不属于任务"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            bindings=(RunBinding("private-a", run.task_id + 1, run.id),),
            versions=versions,
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )

    run.status = "running"
    db.commit()
    with pytest.raises(EvaluationInputError, match="未完成"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            bindings=(RunBinding("private-a", run.task_id, run.id),),
            versions=versions,
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )

    run.status = "completed"
    db.commit()
    with pytest.raises(EvaluationInputError, match="重复绑定"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            bindings=(
                RunBinding("private-a", run.task_id, run.id),
                RunBinding("private-b", run.task_id, run.id),
            ),
            versions=versions,
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )


def test_loader_rejects_legacy_hand_written_case_results(tmp_path):
    dataset = _dataset(tmp_path)
    path = _write_bundle(
        tmp_path,
        {
            "schema_version": "1.0",
            "versions": {
                "model": "fake",
                "prompt": "fake",
                "rules": "fake",
                "data": dataset.dataset_version,
            },
            "results": [
                {
                    "case_id": "private-case-alias",
                    "requirement_correct": 100,
                    "requirement_total": 100,
                    "generation_succeeded": True,
                }
            ],
        },
    )

    with pytest.raises(EvaluationInputError, match="不接受手工结果"):
        load_case_results(path, dataset=dataset, verification_keys={})


def test_loader_rejects_tampered_signed_result(db, tmp_path):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(db)
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
        versions=EvaluationVersions(
            model="model-prod-7",
            prompt="prompt-12",
            rules="rules-8",
            data=dataset.dataset_version,
        ),
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
    )
    bundle["executions"][0]["result"]["generation_succeeded"] = False
    path = _write_bundle(tmp_path, bundle)

    with pytest.raises(EvaluationInputError, match="签名无效"):
        load_case_results(
            path,
            dataset=dataset,
            verification_keys={"quality-ci-1": SIGNING_KEY},
        )


def test_loader_and_cli_fail_closed_without_verification_key(
    db,
    tmp_path,
    monkeypatch,
):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(db)
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
        versions=EvaluationVersions(
            model="model-prod-7",
            prompt="prompt-12",
            rules="rules-8",
            data=dataset.dataset_version,
        ),
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
    )
    path = _write_bundle(tmp_path, bundle)

    with pytest.raises(EvaluationInputError, match="缺少验签密钥"):
        load_case_results(path, dataset=dataset, verification_keys={})

    monkeypatch.delenv("EVAL_EVIDENCE_HMAC_KEY", raising=False)
    output_dir = tmp_path / "reports"
    exit_code = run_eval_main(
        [
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--results",
            str(path),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 2
    assert not output_dir.exists()


def test_verified_report_contains_only_anonymous_execution_provenance(db, tmp_path):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(db)
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
        versions=EvaluationVersions(
            model="model-prod-7",
            prompt="prompt-12",
            rules="rules-8",
            data=dataset.dataset_version,
        ),
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
    )
    evidence = load_case_results(
        _write_bundle(tmp_path, bundle),
        dataset=dataset,
        verification_keys={"quality-ci-1": SIGNING_KEY},
    )
    report = build_evaluation_report(dataset=dataset, evidence=evidence)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["evidence"]["trust_level"] == "system_execution"
    assert report["evidence"]["execution_count"] == 1
    assert report["evidence"]["dataset_fingerprint"] == dataset_fingerprint(dataset)
    assert "private-case-alias" not in serialized
    assert "不应进入报告的客户别名" not in serialized
    assert "private prompt content" not in serialized
    assert "private_output" not in serialized
