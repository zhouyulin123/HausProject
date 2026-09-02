import copy
import hashlib
import json
from pathlib import Path

import pytest

from evals.real_world import CaseResult, EvaluationVersions, load_case_manifest
from evals.run_real_world_eval import (
    EvaluationInputError,
    build_evaluation_report,
    compare_evaluation_reports,
    render_markdown,
)
from evals.trusted_evidence import (
    ExecutionProvenance,
    VerifiedEvaluationEvidence,
    dataset_fingerprint,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _manifest(tmp_path: Path):
    (tmp_path / "room-a.png").write_bytes(b"a")
    (tmp_path / "room-b.png").write_bytes(b"b")
    path = _write_json(
        tmp_path / "manifest.json",
        {
            "schema_version": "1.0",
            "dataset_version": "data-1",
            "cases": [
                {
                    "id": case_id,
                    "name": case_id,
                    "split": "regression",
                    "origin": "private_real",
                    "asset_path": f"room-{suffix}.png",
                    "consent_status": "granted",
                    "annotation_status": "ready",
                    "label_version": "labels-1",
                    "allowed_purposes": ["offline_evaluation"],
                    "failure_tags": [],
                }
                for case_id, suffix in (("case-a", "a"), ("case-b", "b"))
            ],
        },
    )
    return load_case_manifest(path)


def _result(case_id: str, *, requirement_correct: int = 20) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        requirement_correct=requirement_correct,
        requirement_total=20,
        low_confidence_facts=1,
        low_confidence_confirmed=1,
        recommended_skus=3,
        valid_skus=3,
        quote_checks=1,
        quote_consistent=1,
        layout_checks=1,
        layout_hard_passes=1,
        generation_succeeded=True,
        cross_user_access_checks=1,
        retry_bound_checks=1,
    )


def _evidence(dataset, *, model: str, results: tuple[CaseResult, ...]):
    versions = EvaluationVersions(
        model=model,
        prompt=f"prompt-{model}",
        rules=f"rules-{model}",
        data=dataset.dataset_version,
    )
    digest = dataset_fingerprint(dataset)
    executions = tuple(
        ExecutionProvenance(
            case_fingerprint="sha256:"
            + hashlib.sha256(
                f"{digest}:{result.case_id}".encode("utf-8")
            ).hexdigest(),
            task_id=index,
            system_run_id=index,
            source="generation_worker",
            generator="llm",
            model=model,
            prompt_digest="sha256:" + "1" * 64,
            input_digest="sha256:" + "2" * 64,
            output_digest="sha256:" + "3" * 64,
            result_digest="sha256:" + "4" * 64,
        )
        for index, result in enumerate(results, start=1)
    )
    return VerifiedEvaluationEvidence(
        schema_version="2.0",
        versions=versions,
        dataset_fingerprint=digest,
        results=results,
        executions=executions,
        key_id="test-key",
    )


def test_report_serializes_versioned_metrics_and_verified_evidence(tmp_path):
    dataset = _manifest(tmp_path)
    evidence = _evidence(
        dataset,
        model="m1",
        results=(_result("case-a"), _result("case-b")),
    )

    report = build_evaluation_report(dataset=dataset, evidence=evidence)
    markdown = render_markdown(report)

    assert report["schema_version"] == "2.0"
    assert report["gate_passed"] is True
    assert report["dataset"]["eligible_case_count"] == 2
    assert report["evidence"]["signature_verified"] is True
    assert report["evidence"]["schema_version"] == "2.0"
    assert report["versions"] == {
        "model": "m1",
        "prompt": "prompt-m1",
        "rules": "rules-m1",
        "data": "data-1",
    }
    assert "证据验证 | PASS" in markdown
    assert "requirement_accuracy" in markdown


def test_manifest_with_no_eligible_cases_cannot_produce_passing_report(tmp_path):
    (tmp_path / "room.png").write_bytes(b"a")
    manifest_path = _write_json(
        tmp_path / "manifest.json",
        {
            "schema_version": "1.0",
            "dataset_version": "data-1",
            "cases": [
                {
                    "id": "pending",
                    "name": "待标注",
                    "split": "unassigned",
                    "origin": "private_real",
                    "asset_path": "room.png",
                    "consent_status": "pending",
                    "annotation_status": "pending",
                    "label_version": None,
                    "allowed_purposes": [],
                    "failure_tags": [],
                }
            ],
        },
    )
    dataset = load_case_manifest(manifest_path)
    evidence = _evidence(dataset, model="m1", results=())

    report = build_evaluation_report(dataset=dataset, evidence=evidence)

    assert report["gate_passed"] is False
    assert report["dataset"]["eligible_case_count"] == 0
    assert report["dataset"]["ineligible_case_count"] == 1
    assert report["dataset"]["ineligible_reason_counts"] == {
        "consent_not_granted": 1,
        "annotation_not_ready": 1,
        "purpose_not_allowed": 1,
        "split_not_assigned": 1,
    }


def test_regression_comparison_fails_when_quality_drops_on_same_cases(tmp_path):
    dataset = _manifest(tmp_path)
    baseline = build_evaluation_report(
        dataset=dataset,
        evidence=_evidence(
            dataset,
            model="m1",
            results=(_result("case-a"), _result("case-b")),
        ),
    )
    candidate_bad = _result("case-b", requirement_correct=18)
    candidate_bad = CaseResult(
        **{**candidate_bad.__dict__, "severe_cross_user_access": 1}
    )
    candidate = build_evaluation_report(
        dataset=dataset,
        evidence=_evidence(
            dataset,
            model="m2",
            results=(_result("case-a"), candidate_bad),
        ),
    )

    comparison = compare_evaluation_reports(candidate, baseline)

    assert comparison["passed"] is False
    assert comparison["baseline_versions"]["model"] == "m1"
    by_metric = {item["metric"]: item for item in comparison["items"]}
    assert by_metric["requirement_accuracy"]["regressed"] is True
    assert by_metric["severe_cross_user_access"]["regressed"] is True
    assert by_metric["quote_consistency_rate"]["regressed"] is False


def test_regression_comparison_rejects_different_dataset_or_case_set(tmp_path):
    dataset = _manifest(tmp_path)
    report = build_evaluation_report(
        dataset=dataset,
        evidence=_evidence(
            dataset,
            model="m1",
            results=(_result("case-a"), _result("case-b")),
        ),
    )
    wrong_data = copy.deepcopy(report)
    wrong_data["versions"]["data"] = "data-2"
    with pytest.raises(EvaluationInputError, match="数据版本"):
        compare_evaluation_reports(report, wrong_data)

    wrong_dataset = copy.deepcopy(report)
    wrong_dataset["evidence"]["dataset_fingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(EvaluationInputError, match="数据集指纹"):
        compare_evaluation_reports(report, wrong_dataset)

    wrong_cases = copy.deepcopy(report)
    wrong_cases["evidence"]["case_fingerprints"] = [
        report["evidence"]["case_fingerprints"][0]
    ]
    with pytest.raises(EvaluationInputError, match="案例集合"):
        compare_evaluation_reports(report, wrong_cases)
