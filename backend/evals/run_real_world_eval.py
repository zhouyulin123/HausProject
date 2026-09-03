"""阶段 4 真实案例离线回归与质量门禁入口。

本模块不调用在线模型。受控收集器从已完成的系统运行签发证据包，
这里负责验签、校验案例覆盖、聚合确定性指标并以退出码执行质量门禁。
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from evals.real_world import (
    EvaluationSplit,
    EvaluationInputError,
    QualityThresholds,
    RealWorldDataset,
    aggregate_quality_metrics,
    evaluate_quality_gates,
    load_case_manifest,
    validate_evaluation_split,
)
from evals.trusted_evidence import (
    VerifiedEvaluationEvidence,
    verify_trusted_evidence,
)


EvaluationEvidence = VerifiedEvaluationEvidence


_HIGHER_IS_BETTER = (
    "requirement_accuracy",
    "space_fact_accuracy",
    "low_confidence_confirmation_rate",
    "valid_sku_rate",
    "product_match_acceptance_rate",
    "quote_consistency_rate",
    "budget_compliance_rate",
    "layout_hard_constraint_pass_rate",
    "style_consistency_rate",
    "human_satisfaction_mean",
    "generation_success_rate",
)
_LOWER_IS_BETTER = (
    "severe_cross_user_access",
    "unbounded_retry_cases",
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationInputError(f"无法读取评测结果：{exc}") from exc
    if not isinstance(payload, dict):
        raise EvaluationInputError("评测结果根节点必须是对象")
    return payload


def load_case_results(
    result_path: Path | str,
    *,
    dataset: RealWorldDataset,
    split: EvaluationSplit,
    verification_keys: Mapping[str, str] | None = None,
) -> EvaluationEvidence:
    payload = _read_json(Path(result_path).resolve())
    return verify_trusted_evidence(
        payload,
        dataset=dataset,
        split=split,
        verification_keys=verification_keys or {},
    )


def build_evaluation_report(
    *,
    dataset: RealWorldDataset,
    split: EvaluationSplit,
    evidence: EvaluationEvidence,
    thresholds: QualityThresholds | None = None,
) -> dict[str, Any]:
    normalized_split = validate_evaluation_split(split)
    if evidence.split != normalized_split:
        raise EvaluationInputError("已验签证据 split 与报告 split 不一致")
    quality_report = aggregate_quality_metrics(
        list(evidence.results),
        versions=evidence.versions,
    )
    gate_result = evaluate_quality_gates(
        quality_report,
        thresholds or QualityThresholds(),
    )
    split_counts: dict[str, int] = {}
    origin_counts: dict[str, int] = {}
    for case in dataset.eligible_cases(normalized_split):
        split_counts[case.split] = split_counts.get(case.split, 0) + 1
        origin_counts[case.origin] = origin_counts.get(case.origin, 0) + 1
    ineligible_reason_counts: dict[str, int] = {}
    selected_case_ids = {
        case.id for case in dataset.cases if case.split == normalized_split
    }
    selected_ineligible = {
        case_id: reasons
        for case_id, reasons in dataset.ineligible_reasons.items()
        if case_id in selected_case_ids
    }
    for reasons in selected_ineligible.values():
        for reason in reasons:
            ineligible_reason_counts[reason] = (
                ineligible_reason_counts.get(reason, 0) + 1
            )
    evidence_gaps: list[dict[str, str]] = []
    if quality_report.metrics["severe_cross_user_access"] is None:
        evidence_gaps.append(
            {
                "metric": "severe_cross_user_access",
                "status": "missing",
                "code": "independent_signed_security_regression_evidence_missing",
                "required_evidence": (
                    "independently_signed_cross_user_access_regression"
                ),
                "gate_impact": "fail_closed",
                "description": "缺少独立签名的跨用户访问安全回归证据",
            }
        )
    return {
        "schema_version": "3.0",
        "split": normalized_split,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "versions": asdict(evidence.versions),
        "evidence": {
            "schema_version": evidence.schema_version,
            "trust_level": "system_execution",
            "signature_verified": evidence.signature_verified,
            "key_id": evidence.key_id,
            "dataset_fingerprint": evidence.dataset_fingerprint,
            "execution_count": len(evidence.executions),
            "case_fingerprints": sorted(
                item.case_fingerprint for item in evidence.executions
            ),
        },
        "dataset": {
            "schema_version": dataset.schema_version,
            "dataset_version": dataset.dataset_version,
            "fingerprint": evidence.dataset_fingerprint,
            "case_count": len(
                [case for case in dataset.cases if case.split == normalized_split]
            ),
            "eligible_case_count": len(dataset.eligible_cases(normalized_split)),
            "split_counts": split_counts,
            "origin_counts": origin_counts,
            "ineligible_case_count": len(selected_ineligible),
            "ineligible_reason_counts": ineligible_reason_counts,
        },
        "metrics": quality_report.metrics,
        "evidence_gaps": evidence_gaps,
        "gates": [asdict(item) for item in gate_result.items],
        "gate_passed": gate_result.passed,
    }


def _report_comparison_identity(
    report: dict[str, Any],
    *,
    label: str,
) -> tuple[str, str, str, tuple[str, ...]]:
    if report.get("schema_version") != "3.0":
        raise EvaluationInputError(f"{label}报告 schema_version 不受支持")
    versions = report.get("versions")
    dataset = report.get("dataset")
    evidence = report.get("evidence")
    if (
        not isinstance(versions, dict)
        or not isinstance(dataset, dict)
        or not isinstance(evidence, dict)
    ):
        raise EvaluationInputError(f"{label}报告缺少 versions、dataset 或 evidence")
    if (
        evidence.get("trust_level") != "system_execution"
        or evidence.get("signature_verified") is not True
    ):
        raise EvaluationInputError(f"{label}报告没有通过系统执行证据验证")
    data_version = versions.get("data")
    split = report.get("split")
    dataset_digest = evidence.get("dataset_fingerprint")
    case_ids = evidence.get("case_fingerprints")
    if split not in {"development", "regression", "blind"}:
        raise EvaluationInputError(f"{label}报告缺少合法 split")
    if not isinstance(data_version, str) or not data_version.strip():
        raise EvaluationInputError(f"{label}报告缺少数据版本")
    if not isinstance(dataset_digest, str) or not dataset_digest.startswith("sha256:"):
        raise EvaluationInputError(f"{label}报告缺少数据集指纹")
    if not isinstance(case_ids, list) or any(
        not isinstance(case_id, str) or not case_id.strip()
        for case_id in case_ids
    ):
        raise EvaluationInputError(f"{label}报告缺少可比较的案例集合")
    normalized_ids = tuple(sorted(case_id.strip() for case_id in case_ids))
    if len(set(normalized_ids)) != len(normalized_ids):
        raise EvaluationInputError(f"{label}报告的案例集合包含重复 ID")
    return split, data_version.strip(), dataset_digest, normalized_ids


def _metric_value(
    metrics: dict[str, Any],
    metric: str,
    *,
    label: str,
) -> float | int | None:
    value = metrics.get(metric)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationInputError(f"{label}报告的指标 {metric} 不合法")
    return value


def compare_evaluation_reports(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """只在相同数据版本和案例集合上比较候选与基线。"""
    candidate_split, candidate_data, candidate_dataset, candidate_cases = (
        _report_comparison_identity(
            candidate,
            label="候选",
        )
    )
    baseline_split, baseline_data, baseline_dataset, baseline_cases = (
        _report_comparison_identity(
            baseline,
            label="基线",
        )
    )
    if candidate_split != baseline_split:
        raise EvaluationInputError(
            f"基线与候选 split 不一致：{baseline_split} != {candidate_split}"
        )
    if candidate_data != baseline_data:
        raise EvaluationInputError(
            f"基线与候选数据版本不一致：{baseline_data} != {candidate_data}"
        )
    if candidate_dataset != baseline_dataset:
        raise EvaluationInputError("基线与候选数据集指纹不一致")
    if candidate_cases != baseline_cases:
        raise EvaluationInputError("基线与候选案例集合不一致")
    candidate_metrics = candidate.get("metrics")
    baseline_metrics = baseline.get("metrics")
    if not isinstance(candidate_metrics, dict) or not isinstance(
        baseline_metrics, dict
    ):
        raise EvaluationInputError("基线或候选报告缺少 metrics")

    items: list[dict[str, Any]] = []
    for metric in (*_HIGHER_IS_BETTER, *_LOWER_IS_BETTER):
        candidate_value = _metric_value(
            candidate_metrics,
            metric,
            label="候选",
        )
        baseline_value = _metric_value(
            baseline_metrics,
            metric,
            label="基线",
        )
        higher_is_better = metric in _HIGHER_IS_BETTER
        if baseline_value is None:
            regressed = False
        elif candidate_value is None:
            regressed = True
        elif higher_is_better:
            regressed = candidate_value < baseline_value
        else:
            regressed = candidate_value > baseline_value
        delta = (
            candidate_value - baseline_value
            if candidate_value is not None and baseline_value is not None
            else None
        )
        items.append(
            {
                "metric": metric,
                "direction": "higher" if higher_is_better else "lower",
                "baseline": baseline_value,
                "candidate": candidate_value,
                "delta": delta,
                "regressed": regressed,
            }
        )
    return {
        "passed": not any(item["regressed"] for item in items),
        "baseline_versions": baseline["versions"],
        "candidate_versions": candidate["versions"],
        "data_version": candidate_data,
        "split": candidate_split,
        "dataset_fingerprint": candidate_dataset,
        "case_fingerprints": list(candidate_cases),
        "items": items,
    }


def _format_metric(value: float | int | None) -> str:
    if value is None:
        return "NO EVIDENCE"
    if isinstance(value, float):
        return f"{value * 100:.2f}%"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    versions = report["versions"]
    dataset = report["dataset"]
    lines = [
        "# 真实案例质量门禁报告",
        "",
        "| 项目 | 值 |",
        "| --- | --- |",
        f"| 整体门禁 | {'PASS' if report.get('overall_passed', report['gate_passed']) else 'FAIL'} |",
        f"| 绝对质量门禁 | {'PASS' if report['gate_passed'] else 'FAIL'} |",
        f"| 模型版本 | {versions['model']} |",
        f"| Prompt 版本 | {versions['prompt']} |",
        f"| 规则版本 | {versions['rules']} |",
        f"| 数据版本 | {versions['data']} |",
        f"| 评测分组 | {report['split']} |",
        f"| 证据验证 | {'PASS' if report['evidence']['signature_verified'] else 'FAIL'} |",
        f"| 证据格式 | {report['evidence']['schema_version']} |",
        f"| 可评测案例 | {dataset['eligible_case_count']} / {dataset['case_count']} |",
        "",
        "## 指标门禁",
        "",
        "| 指标 | 实际 | 条件 | 目标 | 结果 |",
        "| --- | ---: | :---: | ---: | :---: |",
    ]
    for gate in report["gates"]:
        lines.append(
            f"| {gate['metric']} | {_format_metric(gate['actual'])} | "
            f"{gate['operator']} | {_format_metric(gate['target'])} | "
            f"{'PASS' if gate['passed'] else 'FAIL'} |"
        )
    evidence_gaps = report.get("evidence_gaps") or []
    if evidence_gaps:
        lines.extend(["", "## 证据缺口", ""])
        for gap in evidence_gaps:
            lines.append(
                f"- {gap['description']}（{gap['metric']}，"
                f"门禁策略：{gap['gate_impact']}）"
            )
    comparison = report.get("regression_comparison")
    if comparison is not None:
        lines.extend(
            [
                "",
                "## 版本回归",
                "",
                f"版本回归 | {'PASS' if comparison['passed'] else 'FAIL'}",
                "",
                "| 指标 | 基线 | 候选 | 变化 | 结果 |",
                "| --- | ---: | ---: | ---: | :---: |",
            ]
        )
        for item in comparison["items"]:
            lines.append(
                f"| {item['metric']} | {_format_metric(item['baseline'])} | "
                f"{_format_metric(item['candidate'])} | "
                f"{_format_metric(item['delta'])} | "
                f"{'FAIL' if item['regressed'] else 'PASS'} |"
            )
    if dataset["ineligible_case_count"]:
        lines.extend(["", "## 未进入评测的案例", ""])
        lines.append(f"- 未准入案例数：{dataset['ineligible_case_count']}")
        for reason, count in sorted(dataset["ineligible_reason_counts"].items()):
            lines.append(f"- `{reason}`: {count}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行真实案例离线质量门禁")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--split",
        choices=("development", "regression", "blind"),
        required=True,
    )
    parser.add_argument("--results", type=Path, required=True)
    baseline_group = parser.add_mutually_exclusive_group()
    baseline_group.add_argument(
        "--baseline-results",
        type=Path,
        help="同一数据集的已签名基线证据包",
    )
    baseline_group.add_argument(
        "--establish-baseline",
        action="store_true",
        help="显式建立首个可信基线；后续候选必须提供签名基线证据",
    )
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        signing_key = os.getenv("EVAL_EVIDENCE_HMAC_KEY", "")
        key_id = os.getenv("EVAL_EVIDENCE_KEY_ID", "")
        if not signing_key or not key_id:
            raise EvaluationInputError(
                "缺少验签密钥：必须配置 EVAL_EVIDENCE_HMAC_KEY 和 EVAL_EVIDENCE_KEY_ID"
            )
        dataset = load_case_manifest(args.manifest, asset_root=args.asset_root)
        evidence = load_case_results(
            args.results,
            dataset=dataset,
            split=args.split,
            verification_keys={key_id: signing_key},
        )
        report = build_evaluation_report(
            dataset=dataset,
            split=args.split,
            evidence=evidence,
        )
        if dataset.eligible_cases(args.split) and (
            args.baseline_results is None and not args.establish_baseline
        ):
            raise EvaluationInputError(
                "存在准入案例时必须提供 --baseline-results，"
                "首次建基线需显式使用 --establish-baseline"
            )
        comparison = None
        if args.baseline_results is not None:
            baseline_evidence = load_case_results(
                args.baseline_results,
                dataset=dataset,
                split=args.split,
                verification_keys={key_id: signing_key},
            )
            baseline_report = build_evaluation_report(
                dataset=dataset,
                split=args.split,
                evidence=baseline_evidence,
            )
            comparison = compare_evaluation_reports(report, baseline_report)
        report["baseline_mode"] = (
            "compared"
            if comparison is not None
            else "established"
            if args.establish_baseline
            else "no_eligible_cases"
        )
        report["regression_comparison"] = comparison
        report["overall_passed"] = bool(
            report["gate_passed"]
            and (comparison is None or comparison["passed"])
        )
    except (EvaluationInputError, ValueError) as exc:
        print(f"EVAL_INPUT_ERROR: {exc}")
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "real_world_eval.json"
    markdown_path = args.output_dir / "real_world_eval.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    status = "PASS" if report["overall_passed"] else "FAIL"
    print(f"REAL_WORLD_EVAL={status}")
    print(f"REPORT_JSON={json_path.resolve()}")
    print(f"REPORT_MARKDOWN={markdown_path.resolve()}")
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
