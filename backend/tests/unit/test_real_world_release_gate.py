from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.failure_triage_signature import verify_failure_triage_signature
from evals.failure_triage import FailureTriageInputError
from evals.real_world import (
    CaseResult,
    EvaluationInputError,
    EvaluationVersions,
    load_case_manifest,
)
from evals.release_change_detection import classify_release_sensitive_paths
from evals.real_world_release_gate import (
    _generate_candidate_failure_triage_artifacts,
    _publish_failure_triage_artifacts,
    VerifiedReleaseSplit,
    load_release_gate_config,
    main as release_gate_main,
    validate_candidate_runtime_versions,
    validate_candidate_review_coverage,
    validate_release_cohort,
    validate_release_dataset,
    validate_release_evidence,
    validate_release_event,
)
from evals.trusted_evidence import (
    ExecutionProvenance,
    VerifiedEvaluationEvidence,
    _case_fingerprint,
)
from tests.real_world_fixtures import write_v2_manifest


def _manifest(tmp_path: Path, *, origin: str = "private_real"):
    asset = tmp_path / "room.png"
    asset.write_bytes(b"real-room")
    manifest = write_v2_manifest(
        tmp_path,
        filename="manifest.json",
        dataset_version="release-data-1",
        cases=[
            {
                "id": "case-1",
                "name": "真实户型",
                "split": "regression",
                "origin": origin,
                "asset_path": asset.name,
                "consent_status": (
                    "granted" if origin == "private_real" else "not_required"
                ),
                "annotation_status": "ready",
                "label_version": "labels-1",
                "allowed_purposes": ["offline_evaluation"],
                "failure_tags": [],
            }
        ],
    )
    return load_case_manifest(manifest)


def _cohort_datasets(
    tmp_path: Path,
    *,
    counts: dict[str, int],
    duplicate_last: bool = False,
):
    datasets = {}
    case_index = 0
    total = sum(counts.values())
    for split in ("development", "regression", "blind"):
        root = tmp_path / split
        root.mkdir(parents=True)
        cases = []
        for split_index in range(counts[split]):
            payload_index = (
                0
                if duplicate_last and case_index == total - 1
                else case_index
            )
            asset = root / f"room-{split_index}.png"
            asset.write_bytes(f"private-room-{payload_index}".encode())
            cases.append(
                {
                    "id": f"{split}-case-{split_index}",
                    "name": f"{split} 真实案例 {split_index}",
                    "split": split,
                    "origin": "private_real",
                    "asset_path": asset.name,
                    "consent_status": "granted",
                    "annotation_status": "ready",
                    "label_version": "labels-1",
                    "allowed_purposes": ["offline_evaluation"],
                    "failure_tags": [],
                }
            )
            case_index += 1
        manifest = write_v2_manifest(
            root,
            filename="manifest.json",
            dataset_version="release-data-1",
            cases=cases,
        )
        datasets[split] = load_case_manifest(manifest)
    return datasets


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("backend/app/core/config.py", "model"),
        ("backend/app/services/llm_service.py", "prompt"),
        ("backend/app/services/layout_repair.py", "rules"),
        ("backend/data/public_products_ikea_cn_2026-08-30.json", "data"),
        ("backend/app/services/catalog_service.py", "data"),
    ],
)
def test_sensitive_path_changes_require_real_world_regression(path, category):
    changes = classify_release_sensitive_paths([path])

    assert changes.required is True
    assert path in changes.by_category[category]


def test_unrelated_docs_change_does_not_claim_a_quality_pass():
    changes = classify_release_sensitive_paths(["docs/operator-guide.md"])

    assert changes.required is False
    assert changes.status == "not_required"


def test_release_dataset_rejects_synthetic_cases_even_outside_blind(tmp_path):
    dataset = _manifest(tmp_path, origin="synthetic")

    with pytest.raises(EvaluationInputError, match="synthetic"):
        validate_release_dataset(dataset, split="regression")


def test_release_dataset_requires_nonzero_real_case_denominator(tmp_path):
    dataset = _manifest(tmp_path)

    with pytest.raises(EvaluationInputError, match="development.*真实案例"):
        validate_release_dataset(dataset, split="development")


def test_release_dataset_requires_private_real_case_in_every_split(tmp_path):
    dataset = _manifest(tmp_path, origin="public_reference")

    with pytest.raises(EvaluationInputError, match="private_real"):
        validate_release_dataset(dataset, split="regression")


def test_release_cohort_requires_twenty_unique_private_real_cases(tmp_path):
    too_small = _cohort_datasets(
        tmp_path / "too-small",
        counts={"development": 7, "regression": 6, "blind": 6},
    )
    with pytest.raises(EvaluationInputError, match=r"20.*private_real"):
        validate_release_cohort(too_small)

    duplicated = _cohort_datasets(
        tmp_path / "duplicated",
        counts={"development": 7, "regression": 7, "blind": 6},
        duplicate_last=True,
    )
    with pytest.raises(EvaluationInputError, match="重复物理案例"):
        validate_release_cohort(duplicated)

    valid = _cohort_datasets(
        tmp_path / "valid",
        counts={"development": 7, "regression": 7, "blind": 6},
    )
    validate_release_cohort(valid)


def test_candidate_requires_nonzero_execution_review_coverage():
    evidence = VerifiedEvaluationEvidence(
        schema_version="6.0",
        versions=EvaluationVersions("model", "prompt", "rules", "data"),
        dataset_fingerprint="sha256:" + "1" * 64,
        evidence_digest="sha256:" + "2" * 64,
        split="regression",
        results=(CaseResult(case_id="case-1", generation_succeeded=True),),
        executions=(),
        key_id="eval-key",
    )

    with pytest.raises(EvaluationInputError, match="execution_review"):
        validate_candidate_review_coverage(evidence, split="regression")

    reviewed = VerifiedEvaluationEvidence(
        **{
            **evidence.__dict__,
            "results": (
                CaseResult(
                    case_id="case-1",
                    human_review_count=1,
                    human_rating_count=1,
                    human_rating_sum=4,
                    generation_succeeded=True,
                ),
            ),
        }
    )
    assert validate_candidate_review_coverage(reviewed, split="regression") == 1

    partially_reviewed = VerifiedEvaluationEvidence(
        **{
            **evidence.__dict__,
            "results": (
                reviewed.results[0],
                CaseResult(case_id="case-2", generation_succeeded=True),
            ),
        }
    )
    with pytest.raises(EvaluationInputError, match="每个成功运行"):
        validate_candidate_review_coverage(partially_reviewed, split="regression")


def test_only_controlled_manual_workflow_can_issue_release_proof():
    validate_release_event("workflow_dispatch", ("development", "regression", "blind"))

    with pytest.raises(EvaluationInputError, match="workflow_dispatch"):
        validate_release_event("push", ("development", "regression"))
    with pytest.raises(EvaluationInputError, match="PR.*blind"):
        validate_release_event("pull_request", ("blind",))


def test_release_evidence_requires_6_0_and_independent_security_build_binding():
    evidence = VerifiedEvaluationEvidence(
        schema_version="6.0",
        versions=EvaluationVersions("model", "prompt", "rules", "data"),
        dataset_fingerprint="sha256:" + "1" * 64,
        evidence_digest="sha256:" + "2" * 64,
        split="regression",
        results=(),
        executions=(),
        key_id="eval-key",
        security_evidence_digest="sha256:" + "3" * 64,
        security_key_id="security-key",
        app_build_digest="sha256:" + "4" * 64,
    )

    validate_release_evidence(
        evidence,
        expected_build_digest="sha256:" + "4" * 64,
        label="候选",
    )

    with pytest.raises(EvaluationInputError, match="匹配构建"):
        validate_release_evidence(
            evidence,
            expected_build_digest="sha256:" + "5" * 64,
            label="候选",
        )


def test_candidate_versions_must_match_checked_out_prompt_rules_and_model():
    actual = EvaluationVersions(
        model="model-v1",
        prompt="sha256:" + "1" * 64,
        rules="sha256:" + "2" * 64,
        data="sha256:" + "3" * 64,
    )
    validate_candidate_runtime_versions(
        actual,
        expected_model="model-v1",
        expected_prompt="sha256:" + "1" * 64,
        expected_rules="sha256:" + "2" * 64,
    )

    with pytest.raises(EvaluationInputError, match="规则版本.*目标提交"):
        validate_candidate_runtime_versions(
            actual,
            expected_model="model-v1",
            expected_prompt="sha256:" + "1" * 64,
            expected_rules="sha256:" + "4" * 64,
        )


def test_gate_config_requires_all_splits_and_never_accepts_inline_secrets(tmp_path):
    config = {
        "schema_version": "1.0",
        "splits": {
            split: {
                "manifest": f"private/{split}/manifest.json",
                "asset_root": f"private/{split}",
                "run_bindings": f"private/{split}/bindings.json",
                "security_targets": f"private/{split}/security-targets.json",
                "baseline_evidence": f"private/{split}/baseline.evidence.json",
                "deployment_base_url": "https://eval.example.test",
            }
            for split in ("development", "regression", "blind")
        },
    }
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    loaded = load_release_gate_config(path)

    assert tuple(loaded) == ("development", "regression", "blind")

    config["eval_hmac_key"] = "must-not-be-here"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(EvaluationInputError, match="未知字段"):
        load_release_gate_config(path)


def test_controlled_workflow_contract_is_fail_closed():
    repo_root = Path(__file__).resolve().parents[3]
    workflow = (
        repo_root / ".github/workflows/real-world-release-gate.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "runs-on: [self-hosted" in workflow
    assert "environment: real-world-evaluation" in workflow
    assert "EVAL_EVIDENCE_HMAC_KEY: ${{ secrets." in workflow
    assert "SECURITY_EVIDENCE_HMAC_KEY: ${{ secrets." in workflow
    assert "EVAL_CASE_ID_SALT: ${{ secrets." in workflow
    assert "EVAL_CASE_ID_SALT_ID: ${{ secrets." in workflow
    assert "EVAL_REPORT_SIGNING_KEY: ${{ secrets." in workflow
    assert "EVAL_REPORT_SIGNING_KEY_ID: ${{ secrets." in workflow
    assert "python -m evals.real_world_release_gate" in workflow
    run_output_dir = (
        ".test_artifacts/real-world-release-gate/"
        "${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert f"REAL_WORLD_RELEASE_GATE_OUTPUT_DIR: {run_output_dir}" in workflow
    assert (
        "--output-dir ${{ env.REAL_WORLD_RELEASE_GATE_OUTPUT_DIR }}" in workflow
    )
    assert (
        "${{ env.REAL_WORLD_RELEASE_GATE_OUTPUT_DIR }}/"
        "real_world_release_gate.json" in workflow
    )
    assert (
        "${{ env.REAL_WORLD_RELEASE_GATE_OUTPUT_DIR }}/"
        "failure-triage/*.failure_triage.json" in workflow
    )
    assert "--output-dir .test_artifacts/real-world-release-gate" not in workflow
    assert "if-no-files-found: error" in workflow
    assert "real_world_release_gate.json" in workflow
    assert "failure-triage/*.failure_triage.json" in workflow
    assert "failure-triage/*.failure_triage.md" in workflow


def _candidate_evidence(dataset, *, signature_verified: bool = True):
    manifest_digest = dataset.fingerprint
    output_digest = "sha256:" + "a" * 64
    return VerifiedEvaluationEvidence(
        schema_version="6.0",
        versions=EvaluationVersions(
            "model-v1",
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
            "sha256:" + "3" * 64,
        ),
        dataset_fingerprint=manifest_digest,
        evidence_digest="sha256:" + "4" * 64,
        split="regression",
        results=(
            CaseResult(
                case_id="case-1",
                recommended_skus=2,
                valid_skus=1,
                generation_succeeded=True,
            ),
        ),
        executions=(
            ExecutionProvenance(
                case_fingerprint=_case_fingerprint(manifest_digest, "case-1"),
                execution_ref="exec-hmac-sha256:" + "5" * 64,
                source="generation_worker",
                generator="llm",
                status="completed",
                model="model-v1",
                prompt_digest="sha256:" + "1" * 64,
                rules_digest="sha256:" + "2" * 64,
                data_digest="sha256:" + "3" * 64,
                input_digest="sha256:" + "6" * 64,
                prediction_digest="sha256:" + "7" * 64,
                output_digest=output_digest,
                result_digest="sha256:" + "8" * 64,
            ),
        ),
        key_id="eval-key-v1",
        signature_verified=signature_verified,
    )


def test_verified_candidate_generates_signed_redacted_triage_artifacts(tmp_path):
    dataset = _manifest(tmp_path)
    output_dir = tmp_path / "artifacts"

    summary = _generate_candidate_failure_triage_artifacts(
        dataset=dataset,
        evidence=_candidate_evidence(dataset),
        split="regression",
        output_dir=output_dir,
        candidate_version="a" * 40,
        anonymization_salt="case-alias-secret-at-least-16",
        salt_id="case-alias-v1",
        signing_key_id="triage-signing-v1",
        signing_key="triage-signing-secret-at-least-32-bytes",
    )

    json_path = output_dir / "regression.failure_triage.json"
    markdown_path = output_dir / "regression.failure_triage.md"
    report = json.loads(json_path.read_text(encoding="utf-8"))
    serialized = json.dumps(report, ensure_ascii=False)
    assert summary["failure_count"] == 1
    assert summary["report_digest"].startswith("sha256:")
    assert report["summary"]["failure_count"] == 1
    assert verify_failure_triage_signature(
        report["sync_payload"],
        signing_key="triage-signing-secret-at-least-32-bytes",
    )
    assert "case-1" not in serialized
    assert "case-1" not in markdown_path.read_text(encoding="utf-8")


def test_candidate_triage_fails_closed_before_writing_unverified_evidence(tmp_path):
    dataset = _manifest(tmp_path)
    output_dir = tmp_path / "artifacts"

    with pytest.raises(FailureTriageInputError, match="已验签"):
        _generate_candidate_failure_triage_artifacts(
            dataset=dataset,
            evidence=_candidate_evidence(dataset, signature_verified=False),
            split="regression",
            output_dir=output_dir,
            candidate_version="a" * 40,
            anonymization_salt="case-alias-secret-at-least-16",
            salt_id="case-alias-v1",
            signing_key_id="triage-signing-v1",
            signing_key="triage-signing-secret-at-least-32-bytes",
        )

    assert not output_dir.exists()


def _verified_release_splits(dataset):
    return tuple(
        VerifiedReleaseSplit(
            split=split,
            dataset=dataset,
            candidate=_candidate_evidence(dataset),
            report={"split": split},
        )
        for split in ("development", "regression", "blind")
    )


def test_triage_artifacts_publish_atomically_after_all_splits_succeed(
    tmp_path,
    monkeypatch,
):
    from evals import real_world_release_gate

    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    dataset = _manifest(dataset_root)
    output_dir = tmp_path / "release"
    candidate_version = "a" * 40
    calls = []

    def generate(**kwargs):
        calls.append((kwargs["split"], kwargs["candidate_version"]))
        target = kwargs["output_dir"]
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{kwargs['split']}.failure_triage.json").write_text(
            "{}",
            encoding="utf-8",
        )
        (target / f"{kwargs['split']}.failure_triage.md").write_text(
            "# redacted\n",
            encoding="utf-8",
        )
        return {"failure_count": 0, "report_digest": "sha256:" + "f" * 64}

    monkeypatch.setattr(
        real_world_release_gate,
        "_generate_candidate_failure_triage_artifacts",
        generate,
    )

    summaries = _publish_failure_triage_artifacts(
        verified_splits=_verified_release_splits(dataset),
        output_dir=output_dir,
        candidate_version=candidate_version,
        anonymization_salt="case-alias-secret-at-least-16",
        salt_id="case-alias-v1",
        signing_key_id="triage-signing-v1",
        signing_key="triage-signing-secret-at-least-32-bytes",
    )

    final_dir = output_dir / "failure-triage"
    assert calls == [
        ("development", candidate_version),
        ("regression", candidate_version),
        ("blind", candidate_version),
    ]
    assert tuple(summaries) == ("development", "regression", "blind")
    assert len(list(final_dir.glob("*.failure_triage.json"))) == 3
    assert len(list(final_dir.glob("*.failure_triage.md"))) == 3
    assert not list(output_dir.glob(".failure-triage-staging-*"))


def test_triage_artifact_failure_leaves_no_partial_files(tmp_path, monkeypatch):
    from evals import real_world_release_gate

    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    dataset = _manifest(dataset_root)
    output_dir = tmp_path / "release"

    def fail_second_split(**kwargs):
        target = kwargs["output_dir"]
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{kwargs['split']}.failure_triage.json").write_text(
            "{}",
            encoding="utf-8",
        )
        if kwargs["split"] == "regression":
            raise FailureTriageInputError("private-path-must-not-publish")
        return {"failure_count": 0, "report_digest": "sha256:" + "f" * 64}

    monkeypatch.setattr(
        real_world_release_gate,
        "_generate_candidate_failure_triage_artifacts",
        fail_second_split,
    )

    with pytest.raises(FailureTriageInputError):
        _publish_failure_triage_artifacts(
            verified_splits=_verified_release_splits(dataset),
            output_dir=output_dir,
            candidate_version="a" * 40,
            anonymization_salt="case-alias-secret-at-least-16",
            salt_id="case-alias-v1",
            signing_key_id="triage-signing-v1",
            signing_key="triage-signing-secret-at-least-32-bytes",
        )

    assert not (output_dir / "failure-triage").exists()
    assert not list(output_dir.glob(".failure-triage-staging-*"))


def test_missing_controlled_environment_fails_closed_with_redacted_report(
    tmp_path, monkeypatch
):
    for name in ("GITHUB_SHA", "GITHUB_EVENT_NAME", "REAL_WORLD_BASE_REF"):
        monkeypatch.delenv(name, raising=False)

    exit_code = release_gate_main(
        ["--repo-root", ".", "--output-dir", str(tmp_path)]
    )
    report = json.loads(
        (tmp_path / "real_world_release_gate.json").read_text(encoding="utf-8")
    )

    assert exit_code == 2
    assert report["overall_passed"] is False
    assert report["error_code"] == "release_gate_input_invalid"
    assert "error" not in report


def test_triage_generation_failure_fails_release_gate_with_redacted_report(
    tmp_path,
    monkeypatch,
    capsys,
):
    from evals import real_world_release_gate

    dataset = _manifest(tmp_path)
    environment = {
        "GITHUB_SHA": "a" * 40,
        "REAL_WORLD_BASE_REF": "origin/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "APP_BUILD_DIGEST": "sha256:" + "b" * 64,
        "REAL_WORLD_RELEASE_GATE_CONFIG_PATH": str(tmp_path / "private.json"),
        "EVAL_EVIDENCE_KEY_ID": "eval-v1",
        "EVAL_EVIDENCE_HMAC_KEY": "eval-secret-at-least-thirty-two-bytes",
        "SECURITY_EVIDENCE_KEY_ID": "security-v1",
        "SECURITY_EVIDENCE_HMAC_KEY": "security-secret-at-least-thirty-two-bytes",
        "EVAL_CASE_ID_SALT": "alias-secret-at-least-sixteen",
        "EVAL_CASE_ID_SALT_ID": "alias-v1",
        "EVAL_REPORT_SIGNING_KEY": "triage-secret-at-least-thirty-two-bytes",
        "EVAL_REPORT_SIGNING_KEY_ID": "triage-v1",
    }
    monkeypatch.setattr(
        real_world_release_gate,
        "_required_environment",
        lambda name: environment[name],
    )
    monkeypatch.setattr(
        real_world_release_gate,
        "changed_paths_between",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        real_world_release_gate,
        "load_release_gate_config",
        lambda _path: {
            split: SimpleNamespace(manifest=tmp_path, asset_root=tmp_path)
            for split in real_world_release_gate.REQUIRED_SPLITS
        },
    )
    monkeypatch.setattr(
        real_world_release_gate,
        "load_case_manifest",
        lambda *_args, **_kwargs: dataset,
    )
    monkeypatch.setattr(
        real_world_release_gate,
        "validate_release_dataset",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(real_world_release_gate, "validate_release_cohort", lambda _datasets: 20)

    runtime_versions = EvaluationVersions(
        model=real_world_release_gate.settings.llm_model,
        prompt=real_world_release_gate.canonical_digest(
            real_world_release_gate.generation_prompt_snapshot()
        ),
        rules=real_world_release_gate.current_generation_rules_digest(),
        data="sha256:" + "d" * 64,
    )

    def verified_split(_config, *, split, **_kwargs):
        evidence = _candidate_evidence(dataset)
        evidence = VerifiedEvaluationEvidence(
            **{
                **evidence.__dict__,
                "split": split,
                "versions": runtime_versions,
            }
        )
        return VerifiedReleaseSplit(
            split=split,
            dataset=dataset,
            candidate=evidence,
            report={
                "split": split,
                "candidate_versions": runtime_versions.__dict__,
                "absolute_gate_passed": True,
                "regression_passed": True,
            },
        )

    def fail_triage_publish(**_kwargs):
        raise FailureTriageInputError("sensitive-case-id must not leak")

    monkeypatch.setattr(
        real_world_release_gate,
        "_verify_split",
        verified_split,
    )
    monkeypatch.setattr(
        real_world_release_gate,
        "_publish_failure_triage_artifacts",
        fail_triage_publish,
    )
    output_dir = tmp_path / "release-output"

    exit_code = release_gate_main(
        ["--repo-root", str(tmp_path), "--output-dir", str(output_dir)]
    )
    report_text = (output_dir / "real_world_release_gate.json").read_text(
        encoding="utf-8"
    )
    report = json.loads(report_text)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert report["status"] == "invalid_or_missing_evidence"
    assert report["overall_passed"] is False
    assert "sensitive-case-id" not in report_text
    assert not (output_dir / "failure-triage").exists()
    assert "sensitive-case-id" not in captured.out
    assert str(tmp_path) not in captured.out
    assert "REAL_WORLD_RELEASE_GATE_ERROR=release_gate_input_invalid" in captured.out
