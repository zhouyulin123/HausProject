"""需求级指标评测：需求提取准确率 / 约束遵守率 / 预算偏差率。

需求提取准确率与预算偏差率为确定性计算；约束遵守率需 LLM judge（默认开启，
可用 --skip-llm 跳过）。本脚本为可选评测，不纳入 CI 回归。

用法：
    cd backend
    python -m evals.run_requirement_eval            # 全量（含 LLM judge）
    python -m evals.run_requirement_eval --skip-llm # 只跑确定性指标
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.cases.requirement_cases import (  # noqa: E402
    BUDGET_CASES,
    CONSTRAINT_CASES,
    REQUIREMENT_CASES,
)

FIELD_NAMES = (
    "space_type",
    "style",
    "area",
    "budget_max",
    "constraints",
    "custom_projects",
)


# ---------------------------------------------------------------- 确定性指标

def _normalize(parsed: dict[str, Any]) -> dict[str, Any]:
    budget = parsed.get("budget") or {}
    return {
        "space_type": parsed.get("space_type"),
        "style": parsed.get("style"),
        "area": parsed.get("area"),
        "budget_max": budget.get("max_budget"),
        "constraints": parsed.get("constraints") or [],
        "custom_projects": parsed.get("custom_projects") or [],
    }


def _num_match(expected: Any, actual: Any) -> bool:
    if expected is None and actual in (None, "未指定", ""):
        return True
    if expected is None or actual is None or actual == "未指定":
        return False
    try:
        exp = float(expected)
        act = float(actual)
    except (TypeError, ValueError):
        return False
    return abs(exp - act) <= max(1.0, exp * 0.1)


def _text_match(expected: Any, actual: Any) -> bool:
    if not expected and not actual:
        return True
    if not expected or not actual:
        return False
    return expected in str(actual) or str(actual) in expected


def _field_match(name: str, expected: Any, actual: Any) -> bool:
    if name in ("constraints", "custom_projects"):
        return set(expected or []) <= set(actual or [])
    if name in ("area", "budget_max"):
        return _num_match(expected, actual)
    return _text_match(expected, actual)


def field_accuracy(expected: dict[str, Any], parsed: dict[str, Any]) -> float:
    """单条需求提取的字段命中率（0~1）。"""
    actual = _normalize(parsed)
    matched = sum(
        1 for name in FIELD_NAMES if _field_match(name, expected.get(name), actual.get(name))
    )
    return matched / len(FIELD_NAMES)


def budget_deviation(budget_min: int, budget_max: int, plan_budget: int) -> float:
    """方案报价相对预算范围的偏差率（在范围内为 0）。"""
    if budget_min <= plan_budget <= budget_max:
        return 0.0
    span = budget_max - budget_min
    if span <= 0:
        return 0.0
    nearest = budget_min if plan_budget < budget_min else budget_max
    return abs(plan_budget - nearest) / span


def evaluate_extraction(
    cases: list[Any],
    parse_fn: Callable[[str], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        parsed = parse_fn(case.input)
        rows.append(
            {
                "id": case.id,
                "name": case.name,
                "accuracy": field_accuracy(case.expected, parsed),
            }
        )
    return rows


def evaluate_budget(cases: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        rows.append(
            {
                "id": case.id,
                "name": case.name,
                "deviation": budget_deviation(
                    case.budget_min, case.budget_max, case.plan_budget
                ),
            }
        )
    return rows


def evaluate_constraints(
    cases: list[Any],
    judge_fn: Callable[[dict[str, Any], str], tuple[bool, str]],
) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        compliant, reason = judge_fn(case.requirement, case.plan_text)
        rows.append(
            {
                "id": case.id,
                "name": case.name,
                "compliant": compliant,
                "expected": case.expected_compliant,
                "judge_correct": compliant == case.expected_compliant,
                "reason": reason,
            }
        )
    return rows


# ---------------------------------------------------------------- 报告

def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(
    extraction_rows: list[dict[str, Any]],
    budget_rows: list[dict[str, Any]],
    constraint_rows: list[dict[str, Any]] | None,
) -> str:
    lines = [
        "需求级指标评测报告",
        "=" * 48,
        "",
        "一、需求提取准确率（字段级，0~1）",
        f"  平均准确率 {_avg([r['accuracy'] for r in extraction_rows]) * 100:.1f}%",
    ]
    for row in extraction_rows:
        lines.append(f"  {row['id']} {row['accuracy'] * 100:>5.1f}% {row['name']}")

    lines += ["", "二、预算偏差率（0 = 在预算内）",
              f"  平均偏差率 {_avg([r['deviation'] for r in budget_rows]) * 100:.1f}%"]
    for row in budget_rows:
        lines.append(f"  {row['id']} {row['deviation'] * 100:>5.1f}% {row['name']}")

    if constraint_rows is None:
        lines += ["", "三、约束遵守率：跳过（--skip-llm）"]
    else:
        compliant_count = sum(1 for r in constraint_rows if r["compliant"])
        judge_correct = sum(1 for r in constraint_rows if r["judge_correct"])
        lines += [
            "",
            "三、约束遵守率（LLM judge）",
            f"  判定为遵守 {compliant_count}/{len(constraint_rows)}，"
            f"judge 与人工标注一致 {judge_correct}/{len(constraint_rows)}",
        ]
        for row in constraint_rows:
            mark = "✓" if row["judge_correct"] else "✗"
            lines.append(
                f"  {row['id']} {mark} 遵守={row['compliant']} "
                f"(标注={row['expected']}) {row['name']} —— {row['reason']}"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-llm", action="store_true", help="跳过约束遵守率（LLM judge）")
    args = parser.parse_args()

    from app.services import llm_service, task_service
    from app.services.llm_service import LLMUnavailable

    def parse_fn(text: str) -> dict[str, Any]:
        try:
            return llm_service.parse_requirement(text)
        except LLMUnavailable:
            return task_service.parse_requirement(text)

    extraction_rows = evaluate_extraction(REQUIREMENT_CASES, parse_fn)
    budget_rows = evaluate_budget(BUDGET_CASES)

    constraint_rows = None
    if not args.skip_llm:
        try:
            constraint_rows = evaluate_constraints(
                CONSTRAINT_CASES, llm_service.judge_plan_compliance
            )
        except LLMUnavailable as exc:
            print(f"[warn] LLM judge 不可用，跳过约束遵守率：{exc}")

    report = summarize(extraction_rows, budget_rows, constraint_rows)
    print(report)

    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "requirement_eval.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n报告已保存到 {report_path}")


if __name__ == "__main__":
    main()
