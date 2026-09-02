"""阶段 4 真实案例离线回归与质量门禁入口。

本模块不调用在线模型。上游执行器须先生成逐例、版本化的结果 JSON，
这里负责校验案例覆盖、聚合确定性指标并以退出码执行质量门禁。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.real_world import (
    CaseResult,
    EvaluationVersions,
    QualityThresholds,
    RealWorldDataset,
    aggregate_quality_metrics,
    evaluate_quality_gates,
    load_case_manifest,
)


class EvaluationInputError(ValueError):
    """逐例结果与已冻结案例集不一致。"""


@dataclass(frozen=True)
class EvaluationEvidence:
    versions: EvaluationVersions
    results: tuple[CaseResult, ...]


_HIGHER_IS_BETTER = (
    "requirement_accuracy",
    "low_confidence_confirmation_rate",
    "valid_sku_rate",
    "quote_consistency_rate",
    "layout_hard_constraint_pass_rate",
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


def _build_versions(raw: Any) -> EvaluationVersions:
    if not isinstance(raw, dict):
        raise EvaluationInputError("versions 必须是对象")
    try:
        return EvaluationVersions(
            model=str(raw.get("model") or ""),
            prompt=str(raw.get("prompt") or ""),
            rules=str(raw.get("rules") or ""),
            data=str(raw.get("data") or ""),
        )
    except (TypeError, ValueError) as exc:
        raise EvaluationInputError(str(exc)) from exc


def _build_case_result(raw: Any, index: int) -> CaseResult:
    if not isinstance(raw, dict):
        raise EvaluationInputError(f"第 {index + 1} 条结果必须是对象")
    allowed = set(CaseResult.__dataclass_fields__)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise EvaluationInputError(
            f"案例 {raw.get('case_id', index)} 含未知字段：{', '.join(unknown)}"
        )
    try:
        return CaseResult(**raw)
    except (TypeError, ValueError) as exc:
        raise EvaluationInputError(f"第 {index + 1} 条结果不合法：{exc}") from exc


def load_case_results(
    result_path: Path | str,
    *,
    dataset: RealWorldDataset,
) -> EvaluationEvidence:
    payload = _read_json(Path(result_path).resolve())
    if payload.get("schema_version") != "1.0":
        raise EvaluationInputError(
            f"不支持的结果 schema_version：{payload.get('schema_version')}"
        )
    versions = _build_versions(payload.get("versions"))
    if versions.data != dataset.dataset_version:
        raise EvaluationInputError(
            f"数据版本不一致：结果={versions.data}，清单={dataset.dataset_version}"
        )
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise EvaluationInputError("results 必须是数组")
    results = tuple(
        _build_case_result(raw, index) for index, raw in enumerate(raw_results)
    )
    result_ids = [result.case_id for result in results]
    if len(set(result_ids)) != len(result_ids):
        raise EvaluationInputError("结果包含重复 case_id")
    eligible_ids = {case.id for case in dataset.eligible_cases()}
    result_id_set = set(result_ids)
    problems: list[str] = []
    missing = sorted(eligible_ids - result_id_set)
    unknown = sorted(result_id_set - eligible_ids)
    if missing:
        problems.append(f"缺少案例结果：{', '.join(missing)}")
    if unknown:
        problems.append(f"未知案例结果：{', '.join(unknown)}")
    if problems:
        raise EvaluationInputError("；".join(problems))
    return EvaluationEvidence(versions=versions, results=results)


def build_evaluation_report(
    *,
    dataset: RealWorldDataset,
    evidence: EvaluationEvidence,
    thresholds: QualityThresholds | None = None,
) -> dict[str, Any]:
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
    for case in dataset.eligible_cases():
        split_counts[case.split] = split_counts.get(case.split, 0) + 1
        origin_counts[case.origin] = origin_counts.get(case.origin, 0) + 1
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "versions": asdict(evidence.versions),
        "dataset": {
            "schema_version": dataset.schema_version,
            "dataset_version": dataset.dataset_version,
            "case_count": len(dataset.cases),
            "eligible_case_count": len(dataset.eligible_cases()),
            "eligible_case_ids": sorted(
                case.id for case in dataset.eligible_cases()
            ),
            "split_counts": split_counts,
            "origin_counts": origin_counts,
            "ineligible_cases": dataset.ineligible_reasons,
        },
        "metrics": quality_report.metrics,
        "gates": [asdict(item) for item in gate_result.items],
        "gate_passed": gate_result.passed,
    }


def _report_comparison_identity(
    report: dict[str, Any],
    *,
    label: str,
) -> tuple[str, tuple[str, ...]]:
    if report.get("schema_version") != "1.0":
        raise EvaluationInputError(f"{label}报告 schema_version 不受支持")
    versions = report.get("versions")
    dataset = report.get("dataset")
    if not isinstance(versions, dict) or not isinstance(dataset, dict):
        raise EvaluationInputError(f"{label}报告缺少 versions 或 dataset")
    data_version = versions.get("data")
    case_ids = dataset.get("eligible_case_ids")
    if not isinstance(data_version, str) or not data_version.strip():
        raise EvaluationInputError(f"{label}报告缺少数据版本")
    if not isinstance(case_ids, list) or any(
        not isinstance(case_id, str) or not case_id.strip()
        for case_id in case_ids
    ):
        raise EvaluationInputError(f"{label}报告缺少可比较的案例集合")
    normalized_ids = tuple(sorted(case_id.strip() for case_id in case_ids))
    if len(set(normalized_ids)) != len(normalized_ids):
        raise EvaluationInputError(f"{label}报告的案例集合包含重复 ID")
    return data_version.strip(), normalized_ids


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
    candidate_data, candidate_cases = _report_comparison_identity(
        candidate,
        label="候选",
    )
    baseline_data, baseline_cases = _report_comparison_identity(
        baseline,
        label="基线",
    )
    if candidate_data != baseline_data:
        raise EvaluationInputError(
            f"基线与候选数据版本不一致：{baseline_data} != {candidate_data}"
        )
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
        "eligible_case_ids": list(candidate_cases),
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
    if dataset["ineligible_cases"]:
        lines.extend(["", "## 未进入评测的案例", ""])
        for case_id, reasons in dataset["ineligible_cases"].items():
            lines.append(f"- `{case_id}`: {', '.join(reasons)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行真实案例离线质量门禁")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        dataset = load_case_manifest(args.manifest, asset_root=args.asset_root)
        evidence = load_case_results(args.results, dataset=dataset)
        report = build_evaluation_report(dataset=dataset, evidence=evidence)
        comparison = None
        if args.baseline_report is not None:
            baseline_report = _read_json(args.baseline_report.resolve())
            comparison = compare_evaluation_reports(report, baseline_report)
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
