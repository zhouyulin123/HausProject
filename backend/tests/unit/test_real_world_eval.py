import json
from pathlib import Path

import pytest

from evals.real_world import (
    CaseResult,
    DatasetValidationError,
    EvaluationVersions,
    QualityThresholds,
    aggregate_quality_metrics,
    evaluate_quality_gates,
    load_case_manifest,
)


def _write_manifest(tmp_path: Path, cases: list[dict]) -> Path:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "dataset_version": "2026-09-01.1",
                "cases": cases,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest


def _case(**overrides) -> dict:
    value = {
        "id": "rw-001",
        "name": "脱敏客厅案例",
        "split": "regression",
        "origin": "private_real",
        "asset_path": "assets/room.png",
        "consent_status": "granted",
        "annotation_status": "ready",
        "label_version": "label-1",
        "allowed_purposes": ["offline_evaluation"],
        "failure_tags": [],
    }
    value.update(overrides)
    return value


def test_manifest_only_selects_consented_annotated_evaluation_cases(tmp_path):
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    (asset_dir / "room.png").write_bytes(b"not-a-real-image")

    path = _write_manifest(
        tmp_path,
        [
            _case(id="ready"),
            _case(id="pending-consent", consent_status="pending"),
            _case(id="pending-label", annotation_status="pending"),
        ],
    )

    dataset = load_case_manifest(path)

    assert [case.id for case in dataset.eligible_cases()] == ["ready"]
    assert dataset.ineligible_reasons == {
        "pending-consent": ["consent_not_granted"],
        "pending-label": ["annotation_not_ready"],
    }


def test_manifest_rejects_synthetic_case_in_blind_split(tmp_path):
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    (asset_dir / "room.png").write_bytes(b"synthetic")
    path = _write_manifest(
        tmp_path,
        [_case(split="blind", origin="synthetic", consent_status="not_required")],
    )

    with pytest.raises(DatasetValidationError, match="盲测集不能包含 synthetic"):
        load_case_manifest(path)


def test_manifest_rejects_duplicate_ids_and_paths_outside_dataset(tmp_path):
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"outside")
    path = _write_manifest(
        tmp_path,
        [
            _case(id="same", asset_path="../outside.png"),
            _case(id="same", asset_path="../outside.png"),
        ],
    )

    with pytest.raises(DatasetValidationError) as error:
        load_case_manifest(path)

    message = str(error.value)
    assert "重复案例 ID" in message
    assert "数据集目录之外" in message


def test_manifest_rejects_same_physical_asset_under_different_case_ids(tmp_path):
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    (asset_dir / "development.png").write_bytes(b"same-room-evidence")
    (asset_dir / "blind-copy.png").write_bytes(b"same-room-evidence")
    path = _write_manifest(
        tmp_path,
        [
            _case(
                id="development-copy",
                split="development",
                asset_path="assets/development.png",
            ),
            _case(
                id="blind-copy",
                split="blind",
                asset_path="assets/blind-copy.png",
            ),
        ],
    )

    with pytest.raises(DatasetValidationError, match="重复物理资产"):
        load_case_manifest(path)


def test_quality_metrics_and_gates_match_phase_four_acceptance_lines():
    versions = EvaluationVersions(
        model="model-a",
        prompt="prompt-3",
        rules="rules-7",
        data="2026-09-01.1",
    )
    results = [
        CaseResult(
            case_id="a",
            requirement_correct=19,
            requirement_total=20,
            low_confidence_facts=2,
            low_confidence_confirmed=2,
            recommended_skus=8,
            valid_skus=8,
            quote_checks=3,
            quote_consistent=3,
            layout_checks=1,
            layout_hard_passes=1,
            generation_succeeded=True,
            cross_user_access_checks=1,
            severe_cross_user_access=0,
            retry_bound_checks=1,
            unbounded_retry_detected=False,
        ),
        CaseResult(
            case_id="b",
            requirement_correct=19,
            requirement_total=20,
            low_confidence_facts=1,
            low_confidence_confirmed=1,
            recommended_skus=4,
            valid_skus=4,
            quote_checks=2,
            quote_consistent=2,
            layout_checks=1,
            layout_hard_passes=1,
            generation_succeeded=True,
            cross_user_access_checks=1,
            severe_cross_user_access=0,
            retry_bound_checks=1,
            unbounded_retry_detected=False,
        ),
    ]

    report = aggregate_quality_metrics(results, versions=versions)
    gates = evaluate_quality_gates(report, QualityThresholds())

    assert report.versions == versions
    assert report.case_count == 2
    assert report.metrics["requirement_accuracy"] == pytest.approx(0.95)
    assert report.metrics["low_confidence_confirmation_rate"] == 1.0
    assert report.metrics["valid_sku_rate"] == 1.0
    assert report.metrics["quote_consistency_rate"] == 1.0
    assert report.metrics["layout_hard_constraint_pass_rate"] == 1.0
    assert report.metrics["generation_success_rate"] == 1.0
    assert gates.passed is True
    assert all(item.passed for item in gates.items)


def test_quality_gates_fail_closed_when_denominator_is_missing():
    report = aggregate_quality_metrics(
        [
            CaseResult(
                case_id="empty-evidence",
                generation_succeeded=False,
            )
        ],
        versions=EvaluationVersions(
            model="model-a",
            prompt="prompt-a",
            rules="rules-a",
            data="data-a",
        ),
    )

    gates = evaluate_quality_gates(report, QualityThresholds())

    by_name = {item.metric: item for item in gates.items}
    assert by_name["requirement_accuracy"].passed is False
    assert by_name["valid_sku_rate"].passed is False
    assert by_name["quote_consistency_rate"].passed is False
    assert by_name["layout_hard_constraint_pass_rate"].passed is False
    assert by_name["generation_success_rate"].passed is False
    assert by_name["severe_cross_user_access"].passed is False
    assert by_name["severe_cross_user_access"].actual is None
    assert by_name["unbounded_retry_cases"].passed is False
    assert by_name["unbounded_retry_cases"].actual is None
    assert gates.passed is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"severe_cross_user_access": 1},
        {"unbounded_retry_detected": True},
    ],
)
def test_case_result_rejects_security_or_retry_failures_without_checks(overrides):
    with pytest.raises(ValueError, match="检查证据"):
        CaseResult(case_id="missing-check-evidence", **overrides)


def test_quality_report_includes_phase_four_baseline_only_metrics():
    report = aggregate_quality_metrics(
        [
            CaseResult(
                case_id="real-a",
                space_fact_correct=9,
                space_fact_total=10,
                budget_checks=2,
                budget_within_limit=2,
                product_match_checks=5,
                product_match_accepted=4,
                style_checks=3,
                style_consistent=2,
                human_rating_count=2,
                human_rating_sum=9,
            ),
            CaseResult(
                case_id="real-b",
                space_fact_correct=8,
                space_fact_total=10,
                budget_checks=1,
                budget_within_limit=0,
                product_match_checks=3,
                product_match_accepted=2,
                style_checks=1,
                style_consistent=1,
                human_rating_count=1,
                human_rating_sum=3,
            ),
        ],
        versions=EvaluationVersions(
            model="model-a",
            prompt="prompt-a",
            rules="rules-a",
            data="data-a",
        ),
    )

    assert report.metrics["space_fact_accuracy"] == pytest.approx(0.85)
    assert report.metrics["budget_compliance_rate"] == pytest.approx(2 / 3)
    assert report.metrics["product_match_acceptance_rate"] == pytest.approx(0.75)
    assert report.metrics["style_consistency_rate"] == pytest.approx(0.75)
    assert report.metrics["human_satisfaction_mean"] == pytest.approx(4.0)
    assert report.metrics["human_satisfaction_count"] == 3


def test_case_result_rejects_invalid_human_rating_aggregate():
    with pytest.raises(ValueError, match="人工满意度"):
        CaseResult(
            case_id="invalid-rating",
            human_rating_count=2,
            human_rating_sum=11,
        )
