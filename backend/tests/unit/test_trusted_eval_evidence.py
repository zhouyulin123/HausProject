import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import (
    DesignTask,
    EvaluationRunBinding,
    GenerationRun,
    GenerationRunEvent,
    UploadedImage,
)
from app.services.generation_provenance import canonical_digest
from app.services import design_version_service, generation_run_service
from evals import collect_real_world_evidence
from evals.real_world import load_case_manifest
from evals.run_real_world_eval import (
    EvaluationInputError,
    build_evaluation_report,
    load_case_results,
    main as run_eval_main,
)
from evals.security_access_attestation import (
    AccessTarget,
    HttpObservation,
    collect_security_access_attestation,
)
from evals.trusted_evidence import (
    RunBinding,
    _signature,
    bind_evaluation_run,
    collect_trusted_evidence,
    dataset_fingerprint,
    evaluation_run_idempotency_key,
    verify_trusted_evidence,
)
from tests.real_world_fixtures import write_v2_manifest
from tests.scene_fixtures import attach_scene_versions


SIGNING_KEY = "eval-test-signing-key-that-is-at-least-32-bytes"
SECURITY_SIGNING_KEY = "security-test-signing-key-that-is-at-least-32-bytes"
APP_BUILD_DIGEST = "sha256:" + "a" * 64


def _task_input() -> dict:
    return {
        "raw_user_input": "需要现代客厅",
        "confirmed_requirement": {"style": "现代"},
        "space_type": "客厅",
        "style": "现代",
        "budget_min": 10000,
        "budget_max": 20000,
    }


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
    manifest = write_v2_manifest(
        tmp_path,
        filename="manifest.json",
        dataset_version="data-2026-09-02",
        cases=[
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
                "task_input": _task_input(),
            }
        ],
    )
    return load_case_manifest(manifest)


def _two_case_dataset(tmp_path: Path):
    (tmp_path / "room-a.png").write_bytes(b"private-room-a")
    (tmp_path / "room-b.png").write_bytes(b"private-room-b")
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
                "task_input": _task_input(),
            }
        )
    manifest = write_v2_manifest(
        tmp_path,
        filename="two-cases.json",
        dataset_version="data-2026-09-02",
        cases=cases,
    )
    return load_case_manifest(manifest)


def test_trusted_dataset_requires_manifest_v2_and_binds_annotation_semantics(tmp_path):
    dataset = _dataset(tmp_path)
    case = dataset.cases[0]
    assert case.annotation is not None

    with pytest.raises(EvaluationInputError, match="2.0"):
        dataset_fingerprint(replace(dataset, schema_version="1.0"), split="regression")

    original = dataset_fingerprint(dataset, split="regression")
    changed_annotation = case.annotation.model_copy(
        update={"style_tags": (*case.annotation.style_tags, "轻奢")}
    )
    changed_dataset = replace(
        dataset,
        cases=(replace(case, annotation=changed_annotation),),
    )

    assert dataset_fingerprint(changed_dataset, split="regression") != original


def _completed_system_run(
    db: Session,
    *,
    dataset,
    case_id: str,
    generator: str = "llm",
) -> GenerationRun:
    case = next(item for item in dataset.cases if item.id == case_id)
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
            file_url="/uploads/eval-room.png",
            content_digest=f"sha256:{case.asset_sha256}",
        )
    )
    db.commit()
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case_id,
        task=task,
    )
    revision = design_version_service.persist_generation(
        db,
        task=task,
        generator=generator,
        plans=[
            {
                "id": "plan-eval",
                "name": "匿名方案",
                "style": "现代",
                "private_output": "do not serialize",
                "furnitureSuggestions": [
                    {"id": "SOFA-001"},
                    {"id": "SOFA-001"},
                ],
                "shopQuote": {
                    "furnitureTotal": 10000,
                    "customTotal": 0,
                    "total": 10000,
                    "lineItems": [
                        {"sku": "SOFA-001", "unitPrice": 5000, "quantity": 2}
                    ],
                    "customLineItems": [],
                },
            }
        ],
    )
    attach_scene_versions(db, revision)
    now = datetime.now(timezone.utc)
    run.output_snapshot = {
        "plan_count": 1,
        "plans": [
            {
                "private_output": "do not serialize",
                "furniture_count": 2,
            }
        ],
    }
    run.attempt_count = 1
    run.started_at = now
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
    assert generation_run_service.mark_completed(
        db,
        run=run,
        generator=generator,
        result_revision_id=revision.id,
        now=now,
    )
    db.refresh(run)
    return run


def _write_bundle(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_dataset_fingerprint_binds_asset_bytes_and_case_governance(tmp_path):
    dataset = _dataset(tmp_path)
    first = dataset_fingerprint(dataset, split="regression")

    dataset.cases[0].asset_path.write_bytes(b"changed-room-bytes")
    second = dataset_fingerprint(dataset, split="regression")

    assert first.startswith("sha256:")
    assert first != second


def test_collector_binds_real_run_versions_and_redacts_private_payload(db, tmp_path):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-case-alias",
    )

    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
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
    assert bundle["schema_version"] == "5.0"
    assert bundle["dataset_fingerprint"] == dataset_fingerprint(
        dataset,
        split="regression",
    )
    assert execution["execution_ref"].startswith("exec-hmac-sha256:")
    assert "task_id" not in execution
    assert "system_run_id" not in execution
    assert execution["model"] == run.model
    assert bundle["versions"] == {
        "model": run.model,
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


def test_execution_ref_is_stable_per_deployment_key_and_domain_isolated(
    db,
    tmp_path,
):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-case-alias",
    )
    bindings = (RunBinding("private-case-alias", run.task_id, run.id),)

    first = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=bindings,
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
    )
    second = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=bindings,
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
    )
    other_domain = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=bindings,
        signing_key="different-deployment-key-that-is-at-least-32-bytes",
        key_id="quality-ci-2",
    )

    assert first["executions"][0]["execution_ref"] == second["executions"][0][
        "execution_ref"
    ]
    assert first["executions"][0]["execution_ref"] != other_domain["executions"][
        0
    ]["execution_ref"]


def test_verifier_rejects_raw_database_ids_and_duplicate_execution_refs(
    db,
    tmp_path,
):
    dataset = _two_case_dataset(tmp_path)
    run_a = _completed_system_run(db, dataset=dataset, case_id="private-a")
    run_b = _completed_system_run(db, dataset=dataset, case_id="private-b")
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=(
            RunBinding("private-a", run_a.task_id, run_a.id),
            RunBinding("private-b", run_b.task_id, run_b.id),
        ),
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
    )

    raw_ids = json.loads(json.dumps(bundle))
    raw_execution = raw_ids["executions"][0]
    raw_execution["task_id"] = run_a.task_id
    raw_execution["system_run_id"] = run_a.id
    unsigned = {key: value for key, value in raw_ids.items() if key != "attestation"}
    raw_ids["attestation"]["signature"] = _signature(unsigned, SIGNING_KEY)
    with pytest.raises(EvaluationInputError, match="execution 字段不合法"):
        verify_trusted_evidence(
            raw_ids,
            dataset=dataset,
            split="regression",
            verification_keys={"quality-ci-1": SIGNING_KEY},
        )

    duplicate = json.loads(json.dumps(bundle))
    duplicate["executions"][1]["execution_ref"] = duplicate["executions"][0][
        "execution_ref"
    ]
    unsigned = {key: value for key, value in duplicate.items() if key != "attestation"}
    duplicate["attestation"]["signature"] = _signature(unsigned, SIGNING_KEY)
    with pytest.raises(EvaluationInputError, match="execution_ref"):
        verify_trusted_evidence(
            duplicate,
            dataset=dataset,
            split="regression",
            verification_keys={"quality-ci-1": SIGNING_KEY},
        )


@pytest.mark.parametrize(
    "generator",
    ["manual", "mock", "test", "synthetic", "demo", "template"],
)
def test_collector_rejects_non_system_execution_sources(db, tmp_path, generator):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-case-alias",
        generator=generator,
    )

    with pytest.raises(EvaluationInputError, match="不可信的执行来源"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            split="regression",
            bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )


def test_collector_rejects_task_mismatch_incomplete_run_and_run_replay(db, tmp_path):
    dataset = _two_case_dataset(tmp_path)
    run = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-a",
    )
    second_run = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-b",
    )
    with pytest.raises(EvaluationInputError, match="不属于任务"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            split="regression",
            bindings=(
                RunBinding("private-a", run.task_id + 1, run.id),
                RunBinding("private-b", second_run.task_id, second_run.id),
            ),
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )

    run.status = "running"
    db.commit()
    with pytest.raises(EvaluationInputError, match="可信终态"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            split="regression",
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
            split="regression",
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
        dataset=dataset,
        case_id="private-a",
    )
    run_b = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-b",
    )

    with pytest.raises(EvaluationInputError, match="不属于当前案例"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            split="regression",
            bindings=(
                RunBinding("private-a", run_b.task_id, run_b.id),
                RunBinding("private-b", run_a.task_id, run_a.id),
            ),
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )


def test_eval_idempotency_key_is_persisted_and_does_not_expose_case_id(db, tmp_path):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-case-alias",
    )
    key = evaluation_run_idempotency_key(
        db,
        dataset=dataset,
        split="regression",
        case_id="private-case-alias",
        task=db.get(DesignTask, run.task_id),
    )

    assert run.idempotency_key == key
    assert key.startswith("eval-v1:")
    assert "private-case-alias" not in key


def test_collector_rejects_historical_missing_or_mixed_runtime_versions(db, tmp_path):
    dataset = _two_case_dataset(tmp_path)
    run_a = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-a",
    )
    run_b = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-b",
    )
    bindings = (
        RunBinding("private-a", run_a.task_id, run_a.id),
        RunBinding("private-b", run_b.task_id, run_b.id),
    )

    run_a.prompt_digest = None
    db.commit()
    with pytest.raises(EvaluationInputError, match="执行前评测绑定"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            split="regression",
            bindings=bindings,
            signing_key=SIGNING_KEY,
            key_id="quality-ci-1",
        )

    run_a.prompt_digest = canonical_digest(run_a.prompt_snapshot)
    run_b.rules_digest = "sha256:" + "9" * 64
    db.query(EvaluationRunBinding).filter_by(
        generation_run_id=run_b.id
    ).one().rules_digest = run_b.rules_digest
    db.commit()
    with pytest.raises(EvaluationInputError, match="幂等键不一致"):
        collect_trusted_evidence(
            db,
            dataset=dataset,
            split="regression",
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
        load_case_results(
            path,
            dataset=dataset,
            split="regression",
            verification_keys={},
        )


def test_loader_rejects_tampered_signed_result(db, tmp_path):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-case-alias",
    )
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
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
            split="regression",
            verification_keys={"quality-ci-1": SIGNING_KEY},
        )


def test_verifier_rejects_self_reported_cross_user_metrics_without_security_evidence(
    db,
    tmp_path,
):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-case-alias",
    )
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
    )
    result = bundle["executions"][0]["result"]
    result["cross_user_access_checks"] = 1
    result["severe_cross_user_access"] = 0
    bundle["executions"][0]["result_digest"] = canonical_digest(result)
    unsigned = {key: value for key, value in bundle.items() if key != "attestation"}
    bundle["attestation"]["signature"] = _signature(unsigned, SIGNING_KEY)

    with pytest.raises(EvaluationInputError, match="独立安全证据"):
        verify_trusted_evidence(
            bundle,
            dataset=dataset,
            split="regression",
            verification_keys={"quality-ci-1": SIGNING_KEY},
        )


def test_collector_and_verifier_fill_cross_user_metrics_only_from_security_attestation(
    db,
    tmp_path,
):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-case-alias",
    )
    versions = {
        "model": run.model,
        "prompt": run.prompt_digest,
        "rules": run.rules_digest,
        "data": run.data_digest,
    }
    owner_session = "00000000-0000-0000-0000-000000000001"
    foreign_session = "10000000-0000-0000-0000-000000000001"

    class DeploymentTransport:
        def get(self, url, *, headers):
            common = {"x-app-build-digest": APP_BUILD_DIGEST}
            if url.endswith("/health"):
                return HttpObservation(200, common, {"environment": "staging"})
            task_id = int(url.split("/api/design/tasks/", 1)[1].split("/", 1)[0])
            session_id = headers["X-Session-ID"]
            if session_id == owner_session and task_id == run.task_id:
                return HttpObservation(200, common, {"run_id": run.id})
            if session_id == foreign_session and task_id == run.task_id + 1000:
                return HttpObservation(200, common, {"run_id": run.id + 1000})
            return HttpObservation(404, common, {"detail": "not found"})

    from evals.real_world import EvaluationVersions

    security_bundle = collect_security_access_attestation(
        dataset=dataset,
        split="regression",
        targets=(
            AccessTarget(
                case_id="private-case-alias",
                task_id=run.task_id,
                foreign_control_task_id=run.task_id + 1000,
                owner_session_env="OWNER_SESSION",
                foreign_session_env="FOREIGN_SESSION",
            ),
        ),
        versions=EvaluationVersions(**versions),
        base_url="https://controlled.example",
        app_build_digest=APP_BUILD_DIGEST,
        credentials={
            "OWNER_SESSION": owner_session,
            "FOREIGN_SESSION": foreign_session,
        },
        transport=DeploymentTransport(),
        signing_key=SECURITY_SIGNING_KEY,
        key_id="security-ci-1",
    )
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
        security_access_attestation=security_bundle,
        security_verification_keys={"security-ci-1": SECURITY_SIGNING_KEY},
        expected_app_build_digest=APP_BUILD_DIGEST,
    )
    evidence = verify_trusted_evidence(
        bundle,
        dataset=dataset,
        split="regression",
        verification_keys={"quality-ci-1": SIGNING_KEY},
        security_verification_keys={"security-ci-1": SECURITY_SIGNING_KEY},
        expected_app_build_digest=APP_BUILD_DIGEST,
    )
    report = build_evaluation_report(
        dataset=dataset,
        split="regression",
        evidence=evidence,
    )

    assert evidence.results[0].cross_user_access_checks == 1
    assert evidence.results[0].severe_cross_user_access == 0
    assert report["metrics"]["cross_user_access_checks"] == 1
    assert report["metrics"]["severe_cross_user_access"] == 0
    assert report["evidence"]["security_access"]["signature_verified"] is True
    assert report["evidence"]["security_access"]["app_build_digest"] == (
        APP_BUILD_DIGEST
    )
    assert report["evidence_gaps"] == []


def test_loader_and_cli_fail_closed_without_verification_key(
    db,
    tmp_path,
    monkeypatch,
):
    dataset = _dataset(tmp_path)
    run = _completed_system_run(
        db,
        dataset=dataset,
        case_id="private-case-alias",
    )
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
    )
    path = _write_bundle(tmp_path, bundle)

    with pytest.raises(EvaluationInputError, match="缺少验签密钥"):
        load_case_results(
            path,
            dataset=dataset,
            split="regression",
            verification_keys={},
        )

    monkeypatch.delenv("EVAL_EVIDENCE_HMAC_KEY", raising=False)
    output_dir = tmp_path / "reports"
    exit_code = run_eval_main(
        [
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--split",
            "regression",
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
        dataset=dataset,
        case_id="private-case-alias",
    )
    bundle = collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=(RunBinding("private-case-alias", run.task_id, run.id),),
        signing_key=SIGNING_KEY,
        key_id="quality-ci-1",
    )
    evidence = load_case_results(
        _write_bundle(tmp_path, bundle),
        dataset=dataset,
        split="regression",
        verification_keys={"quality-ci-1": SIGNING_KEY},
    )
    report = build_evaluation_report(
        dataset=dataset,
        split="regression",
        evidence=evidence,
    )
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["evidence"]["trust_level"] == "system_execution"
    assert report["evidence"]["execution_count"] == 1
    assert report["evidence"]["dataset_fingerprint"] == dataset_fingerprint(
        dataset,
        split="regression",
    )
    assert report["metrics"]["severe_cross_user_access"] is None
    assert report["metrics"]["retry_bound_checks"] == 1
    assert report["metrics"]["unbounded_retry_cases"] == 0
    assert report["evidence_gaps"] == [
        {
            "metric": "severe_cross_user_access",
            "status": "missing",
            "code": "independent_signed_security_regression_evidence_missing",
            "required_evidence": "independently_signed_cross_user_access_regression",
            "gate_impact": "fail_closed",
            "description": "缺少独立签名的跨用户访问安全回归证据",
        }
    ]
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
        dataset=dataset,
        case_id="private-case-alias",
    )
    bindings_path = tmp_path / "run-bindings.json"
    bindings_path.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "split": "regression",
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
            "--split",
            "regression",
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
            "--split",
            "regression",
            "--results",
            str(evidence_path),
            "--establish-baseline",
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
