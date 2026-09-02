import json
from pathlib import Path

import pytest

from evals.real_world import DatasetValidationError, load_case_manifest
from evals.run_real_world_eval import (
    EvaluationInputError,
    build_evaluation_report,
    compare_evaluation_reports,
    load_case_results,
    main as run_eval_main,
    render_markdown,
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


def _result(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "requirement_correct": 20,
        "requirement_total": 20,
        "low_confidence_facts": 1,
        "low_confidence_confirmed": 1,
        "recommended_skus": 3,
        "valid_skus": 3,
        "quote_checks": 1,
        "quote_consistent": 1,
        "layout_checks": 1,
        "layout_hard_passes": 1,
        "generation_succeeded": True,
        "cross_user_access_checks": 1,
        "severe_cross_user_access": 0,
        "retry_bound_checks": 1,
        "unbounded_retry_detected": False,
    }


def test_results_must_cover_exact_eligible_case_ids(tmp_path):
    dataset = _manifest(tmp_path)
    result_path = _write_json(
        tmp_path / "results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m1",
                "prompt": "p1",
                "rules": "r1",
                "data": "data-1",
            },
            "results": [_result("case-a"), _result("unknown")],
        },
    )

    with pytest.raises(EvaluationInputError) as error:
        load_case_results(result_path, dataset=dataset)

    assert "缺少案例结果：case-b" in str(error.value)
    assert "未知案例结果：unknown" in str(error.value)


def test_result_data_version_must_match_manifest(tmp_path):
    dataset = _manifest(tmp_path)
    result_path = _write_json(
        tmp_path / "results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m1",
                "prompt": "p1",
                "rules": "r1",
                "data": "old-data",
            },
            "results": [_result("case-a"), _result("case-b")],
        },
    )

    with pytest.raises(EvaluationInputError, match="数据版本不一致"):
        load_case_results(result_path, dataset=dataset)


def test_report_serializes_versioned_metrics_and_gate_evidence(tmp_path):
    dataset = _manifest(tmp_path)
    result_path = _write_json(
        tmp_path / "results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m1",
                "prompt": "p1",
                "rules": "r1",
                "data": "data-1",
            },
            "results": [_result("case-a"), _result("case-b")],
        },
    )

    evidence = load_case_results(result_path, dataset=dataset)
    report = build_evaluation_report(dataset=dataset, evidence=evidence)
    markdown = render_markdown(report)

    assert report["gate_passed"] is True
    assert report["dataset"]["eligible_case_count"] == 2
    assert report["versions"] == {
        "model": "m1",
        "prompt": "p1",
        "rules": "r1",
        "data": "data-1",
    }
    assert "模型版本 | m1" in markdown
    assert "整体门禁 | PASS" in markdown
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
    result_path = _write_json(
        tmp_path / "results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m1",
                "prompt": "p1",
                "rules": "r1",
                "data": "data-1",
            },
            "results": [],
        },
    )

    evidence = load_case_results(result_path, dataset=dataset)
    report = build_evaluation_report(dataset=dataset, evidence=evidence)

    assert report["gate_passed"] is False
    assert report["dataset"]["eligible_case_count"] == 0
    assert report["dataset"]["ineligible_cases"]["pending"] == [
        "consent_not_granted",
        "annotation_not_ready",
        "purpose_not_allowed",
        "split_not_assigned",
    ]


def test_regression_comparison_fails_when_quality_drops_on_same_cases(tmp_path):
    dataset = _manifest(tmp_path)
    baseline_path = _write_json(
        tmp_path / "baseline-results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m1",
                "prompt": "p1",
                "rules": "r1",
                "data": "data-1",
            },
            "results": [_result("case-a"), _result("case-b")],
        },
    )
    candidate_result = _result("case-b")
    candidate_result["requirement_correct"] = 18
    candidate_result["severe_cross_user_access"] = 1
    candidate_path = _write_json(
        tmp_path / "candidate-results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m2",
                "prompt": "p2",
                "rules": "r2",
                "data": "data-1",
            },
            "results": [_result("case-a"), candidate_result],
        },
    )
    baseline = build_evaluation_report(
        dataset=dataset,
        evidence=load_case_results(baseline_path, dataset=dataset),
    )
    candidate = build_evaluation_report(
        dataset=dataset,
        evidence=load_case_results(candidate_path, dataset=dataset),
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
    result_path = _write_json(
        tmp_path / "results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m1",
                "prompt": "p1",
                "rules": "r1",
                "data": "data-1",
            },
            "results": [_result("case-a"), _result("case-b")],
        },
    )
    report = build_evaluation_report(
        dataset=dataset,
        evidence=load_case_results(result_path, dataset=dataset),
    )
    wrong_data = json.loads(json.dumps(report))
    wrong_data["versions"]["data"] = "data-2"
    with pytest.raises(EvaluationInputError, match="数据版本"):
        compare_evaluation_reports(report, wrong_data)

    wrong_cases = json.loads(json.dumps(report))
    wrong_cases["dataset"]["eligible_case_ids"] = ["case-a"]
    with pytest.raises(EvaluationInputError, match="案例集合"):
        compare_evaluation_reports(report, wrong_cases)


def test_cli_baseline_report_fails_candidate_that_regresses_above_absolute_gate(
    tmp_path,
):
    dataset = _manifest(tmp_path)
    baseline_results = _write_json(
        tmp_path / "baseline-results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m1",
                "prompt": "p1",
                "rules": "r1",
                "data": "data-1",
            },
            "results": [_result("case-a"), _result("case-b")],
        },
    )
    candidate_case = _result("case-b")
    candidate_case["requirement_correct"] = 19
    candidate_results = _write_json(
        tmp_path / "candidate-results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m2",
                "prompt": "p2",
                "rules": "r1",
                "data": "data-1",
            },
            "results": [_result("case-a"), candidate_case],
        },
    )
    baseline_report = build_evaluation_report(
        dataset=dataset,
        evidence=load_case_results(baseline_results, dataset=dataset),
    )
    baseline_report_path = _write_json(
        tmp_path / "baseline-report.json",
        baseline_report,
    )
    output_dir = tmp_path / "reports"

    exit_code = run_eval_main(
        [
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--results",
            str(candidate_results),
            "--baseline-report",
            str(baseline_report_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    report = json.loads(
        (output_dir / "real_world_eval.json").read_text(encoding="utf-8")
    )
    assert report["gate_passed"] is True
    assert report["regression_comparison"]["passed"] is False
    assert report["overall_passed"] is False
    assert exit_code == 1
    markdown = (output_dir / "real_world_eval.md").read_text(encoding="utf-8")
    assert "版本回归 | FAIL" in markdown
    assert "requirement_accuracy" in markdown


def test_cli_requires_explicit_baseline_mode_for_eligible_cases(tmp_path):
    _manifest(tmp_path)
    results_path = _write_json(
        tmp_path / "results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m1",
                "prompt": "p1",
                "rules": "r1",
                "data": "data-1",
            },
            "results": [_result("case-a"), _result("case-b")],
        },
    )

    exit_code = run_eval_main(
        [
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--results",
            str(results_path),
            "--output-dir",
            str(tmp_path / "reports"),
        ]
    )

    assert exit_code == 2
    assert not (tmp_path / "reports" / "real_world_eval.json").exists()


def test_cli_establish_baseline_is_explicit_and_still_requires_gates(tmp_path):
    _manifest(tmp_path)
    results_path = _write_json(
        tmp_path / "results.json",
        {
            "schema_version": "1.0",
            "versions": {
                "model": "m1",
                "prompt": "p1",
                "rules": "r1",
                "data": "data-1",
            },
            "results": [_result("case-a"), _result("case-b")],
        },
    )
    output_dir = tmp_path / "baseline"

    exit_code = run_eval_main(
        [
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--results",
            str(results_path),
            "--establish-baseline",
            "--output-dir",
            str(output_dir),
        ]
    )

    report = json.loads(
        (output_dir / "real_world_eval.json").read_text(encoding="utf-8")
    )
    assert exit_code == 0
    assert report["baseline_mode"] == "established"
    assert report["overall_passed"] is True
