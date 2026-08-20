"""跨空间布局评测 runner：客厅 + 卧室 + 餐厅 + 书房全量评测。

对全部案例跑完整的确定性布局生成（候选生成 → 评估 → 修复），
按空间分组统计通过率 / 平均分 / 失败原因分布。

用法：
    cd backend
    python -m evals.run_layout_eval
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.cases import bedroom, dining_room, living_room, study
from evals.cases.base import RoomCase
from evals.run_living_room_eval import run_case


def all_cases() -> list[RoomCase]:
    return [
        *living_room.CASES,
        *bedroom.CASES,
        *dining_room.CASES,
        *study.CASES,
    ]


def run_all(cases: list[RoomCase] | None = None) -> list[dict[str, Any]]:
    rows = []
    for case in cases or all_cases():
        row = run_case(case)
        if row is not None:
            row["group"] = case.group
            rows.append(row)
    return rows


def _group_stats(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["group"], []).append(row)
    for group, group_rows in groups.items():
        passed = sum(1 for row in group_rows if row["valid"])
        stats[group] = {
            "count": len(group_rows),
            "passed": passed,
            "pass_rate": passed / len(group_rows),
            "average": sum(row["total"] for row in group_rows) / len(group_rows),
        }
    return stats


def summarize(rows: list[dict[str, Any]]) -> str:
    total = len(rows)
    passed = sum(1 for row in rows if row["valid"])
    avg = sum(row["total"] for row in rows) / total if total else 0
    stats = _group_stats(rows)
    failed = [row for row in rows if not row["valid"]]
    issue_counter: Counter[str] = Counter()
    for row in rows:
        issue_counter.update(row["issue_codes"])

    lines = [
        "跨空间布局评测报告",
        "=" * 48,
        f"共 {total} 例，通过 {passed} 例（{passed / total * 100:.1f}%），"
        f"平均分 {avg:.1f}",
        "",
        "分空间统计：",
        f"  {'空间':<8} {'案例':>4} {'通过':>4} {'通过率':>8} {'平均分':>8}",
    ]
    for group in ("living", "bedroom", "dining", "study"):
        if group not in stats:
            continue
        stat = stats[group]
        label = {"living": "客厅", "bedroom": "卧室", "dining": "餐厅", "study": "书房"}[group]
        lines.append(
            f"  {label:<8} {stat['count']:>4} {stat['passed']:>4} "
            f"{stat['pass_rate'] * 100:>7.1f}% {stat['average']:>8.1f}"
        )

    if failed:
        lines.append("")
        lines.append("未达标案例：")
        for row in failed:
            codes = "、".join(sorted(set(row["issue_codes"]))) or "（无评分项）"
            lines.append(
                f"  {row['case_id']} {row['name']} {row['total']}分 [{codes}]"
            )
    lines.append("")
    lines.append("失败原因分布（含软问题，按出现次数）：")
    for code, count in issue_counter.most_common():
        lines.append(f"  {code} × {count}")

    lines.append("")
    lines.append("逐例明细：")
    for row in rows:
        mark = "✓" if row["valid"] else "✗"
        lines.append(
            f"  {row['case_id']} {mark} {row['total']:>3}分 "
            f"[{row['group']}] {row['name']}"
        )
    return "\n".join(lines)


def main() -> None:
    rows = run_all()
    report = summarize(rows)
    print(report)

    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "layout_eval.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n报告已保存到 {report_path}")


if __name__ == "__main__":
    main()
