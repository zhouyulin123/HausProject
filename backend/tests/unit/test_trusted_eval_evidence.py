import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import DesignTask, GenerationRun, GenerationRunEvent
from app.services import generation_run_service
from app.services.generation_provenance import canonical_digest
from evals import collect_real_world_evidence
from evals.real_world import load_case_manifest
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
    evaluation_run_idempotency_key,
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


def _completed_system_run(
    db: Session,
    *,
    generator: str = "llm",
    idempotency_key: str | None = None,
) -> GenerationRun:
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
        prompt_digest=canonical_digest("private prompt content"),
        rules_digest="sha256:" + "2" * 64,
        data_digest="sha256:" + "3" * 64,
        input_snapshot={"private_requirement": "do not serialize"},
        output_snapshot={
            "plan_count": 1,
            "plans": [
                {
                    "private_output": "do not serialize",
                    "furniture_count": 2,
                }
            ],
        },
        worker_id=None,
        attempt_count=1,
        max_attempts=3,
        idempotency_key=idempotency_key,
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
                source={
                    "generate_plans": "llm",
                    "calculate_quote": "deterministic",
                    "validate_quality": "deterministic",
                }.get(node),
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
    run = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(
            dataset, "private-case-alias"
        ),
    )

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
    assert bundle["versions"] == {
        "model": "model-prod-7",
        "prompt": run.prompt_digest,
        "rules": run.rules_digest,
        "data": run.data_digest,
    }
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
    run = _completed_system_run(
        db,
        generator=generator,
        idempotency_key=evaluation_run_idempotency_key(
            dataset, "private-case-alias"
        ),
    )

    with pytest.raises(EvaluationInputError, match="不可信的执行来源"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )


def test_collector_rejects_task_mismatch_incomplete_run_and_run_replay(db, tmp_path):
    dataset = _two_case_dataset(tmp_path)
    run = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(dataset, "private-a"),
    )
    second_run = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(dataset, "private-b"),
    )
    with pytest.raises(EvaluationInputError, match="不属于任务"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            bindings=(
                RunBinding("private-a", run.task_id + 1, run.id),
                RunBinding("private-b", second_run.task_id, second_run.id),
            ),
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )

    run.status = "running"
    db.commit()
    with pytest.raises(EvaluationInputError, match="未完成"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            bindings=(
                RunBinding("private-a", run.task_id, run.id),
                RunBinding("private-b", second_run.task_id, second_run.id),
            ),
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
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )


def test_run_is_bound_to_dataset_case_before_execution_and_cannot_be_swapped(
    db,
    tmp_path,
):
    dataset = _two_case_dataset(tmp_path)
    run_a = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(dataset, "private-a"),
    )
    run_b = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(dataset, "private-b"),
    )

    with pytest.raises(EvaluationInputError, match="执行前绑定"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            bindings=(
                RunBinding("private-a", run_b.task_id, run_b.id),
                RunBinding("private-b", run_a.task_id, run_a.id),
            ),
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )


def test_eval_idempotency_key_is_persisted_and_does_not_expose_case_id(db, tmp_path):
    dataset = _dataset(tmp_path)
    key = evaluation_run_idempotency_key(dataset, "private-case-alias")
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()

    run = generation_run_service.create_run(db, task=task, idempotency_key=key)

    assert run.idempotency_key == key
    assert key.startswith("eval-v1:")
    assert "private-case-alias" not in key


def test_collector_rejects_historical_missing_or_mixed_runtime_versions(db, tmp_path):
    dataset = _two_case_dataset(tmp_path)
    run_a = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(dataset, "private-a"),
    )
    run_b = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(dataset, "private-b"),
    )
    bindings = (
        RunBinding("private-a", run_a.task_id, run_a.id),
        RunBinding("private-b", run_b.task_id, run_b.id),
    )

    run_a.prompt_digest = None
    db.commit()
    with pytest.raises(EvaluationInputError, match="版本摘要"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            bindings=bindings,
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )

    run_a.prompt_digest = canonical_digest(run_a.prompt_snapshot)
    run_b.rules_digest = "sha256:" + "9" * 64
    db.commit()
    with pytest.raises(EvaluationInputError, match="版本不一致"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            bindings=bindings,
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
    run = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(
            dataset, "private-case-alias"
        ),
    )
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
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
    run = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(
            dataset, "private-case-alias"
        ),
    )
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
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
    run = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(
            dataset, "private-case-alias"
        ),
    )
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
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
    assert report["metrics"]["severe_cross_user_access"] is None
    assert report["metrics"]["unbounded_retry_cases"] is None
    assert report["gate_passed"] is False
    assert "private-case-alias" not in serialized
    assert "不应进入报告的客户别名" not in serialized
    assert "private prompt content" not in serialized
    assert "private_output" not in serialized


def test_collector_and_evaluator_cli_use_the_same_fail_closed_contract(
    db,
    tmp_path,
    monkeypatch,
):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(
        db,
        idempotency_key=evaluation_run_idempotency_key(
            dataset, "private-case-alias"
        ),
    )
    bindings_path = tmp_path / "run-bindings.json"
    bindings_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "bindings": [
                    {
                        "case_id": "private-case-alias",
                        "task_id": run.task_id,
                        "system_run_id": run.id,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "trusted-evidence.json"
    monkeypatch.setenv("EVAL_EVIDENCE_HMAC_KEY", SIGNING_KEY)
    monkeypatch.setenv("EVAL_EVIDENCE_KEY_ID", "quality-ci-1")
    monkeypatch.setattr(collect_real_world_evidence, "SessionLocal", lambda: db)

    collect_exit = collect_real_world_evidence.main(
        [
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--run-bindings",
            str(bindings_path),
            "--output",
            str(evidence_path),
        ]
    )
    report_dir = tmp_path / "cli-report"
    eval_exit = run_eval_main(
        [
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--results",
            str(evidence_path),
            "--output-dir",
            str(report_dir),
        ]
    )

    assert collect_exit == 0
    assert eval_exit == 1
    report = json.loads(
        (report_dir / "real_world_eval.json").read_text(encoding="utf-8")
    )
    assert report["evidence"]["signature_verified"] is True
    assert report["evidence"]["execution_count"] == 1
    assert report["gate_passed"] is False


def test_collector_cli_no_longer_accepts_self_reported_versions():
    with pytest.raises(SystemExit) as error:
        collect_real_world_evidence.main(
            [
                "--manifest",
                "manifest.json",
                "--run-bindings",
                "bindings.json",
                "--prompt-version",
                "self-reported",
                "--rules-version",
                "self-reported",
                "--output",
                "evidence.json",
            ]
        )

    assert error.value.code == 2
