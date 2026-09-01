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
            "split_counts": split_counts,
            "origin_counts": origin_counts,
            "ineligible_cases": dataset.ineligible_reasons,
        },
        "metrics": quality_report.metrics,
        "gates": [asdict(item) for item in gate_result.items],
        "gate_passed": gate_result.passed,
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
        f"| 整体门禁 | {'PASS' if report['gate_passed'] else 'FAIL'} |",
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
    if dataset["ineligible_cases"]:
        lines.extend(["", "## 未进入评测的案例", ""])
        for case_id, reasons in dataset["ineligible_cases"].items():
            lines.append(f"- `{case_id}`: {', '.join(reasons)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行真实案例离线质量门禁")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        dataset = load_case_manifest(args.manifest, asset_root=args.asset_root)
        evidence = load_case_results(args.results, dataset=dataset)
        report = build_evaluation_report(dataset=dataset, evidence=evidence)
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
    status = "PASS" if report["gate_passed"] else "FAIL"
    print(f"REAL_WORLD_EVAL={status}")
    print(f"REPORT_JSON={json_path.resolve()}")
    print(f"REPORT_MARKDOWN={markdown_path.resolve()}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
