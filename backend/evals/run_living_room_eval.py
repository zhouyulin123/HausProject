"""客厅布局评测 runner。

对 20 例标准客厅跑完整的确定性布局生成（候选生成 → 评估 → 修复），
统计"无需手动救场即可打开渲染"的比例（以最优布局有效作为代理指标），
并输出失败原因分布。

用法：
    cd backend
    python -m evals.run_living_room_eval
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.scenes import Opening, RoomGeometry, Vector2XZ
from app.services.layout_generator import generate_layouts

from evals.cases.living_room import CASES, LivingRoomCase


def build_room(case: LivingRoomCase) -> RoomGeometry:
    half_w = case.room_width_m / 2
    half_d = case.room_depth_m / 2
    return RoomGeometry(
        id=case.id,
        name="客厅",
        floor_polygon=[
            Vector2XZ(x=-half_w, z=-half_d),
            Vector2XZ(x=half_w, z=-half_d),
            Vector2XZ(x=half_w, z=half_d),
            Vector2XZ(x=-half_w, z=half_d),
        ],
        ceiling_height=case.ceiling_height_m,
    )


def build_openings(case: LivingRoomCase) -> list[Opening]:
    return [
        Opening(id=f"{opening.get('type', 'opening')}-{index + 1}", **opening)
        for index, opening in enumerate(case.openings)
    ]


def run_case(case: LivingRoomCase) -> dict[str, Any] | None:
    """跑单个案例，返回最优布局的评测结果。"""
    room = build_room(case)
    openings = build_openings(case)
    results = generate_layouts(room, openings, case.furniture)
    if not results:
        return None
    best, score = results[0]
    return {
        "case_id": case.id,
        "name": case.name,
        "total": score.total,
        "valid": score.valid,
        "issue_codes": [issue.code for issue in score.issues],
    }


def run_all(cases: list[LivingRoomCase] | None = None) -> list[dict[str, Any]]:
    """跑全部案例并返回结果行。"""
    rows = []
    for case in cases or CASES:
        row = run_case(case)
        if row is not None:
            rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]]) -> str:
    """生成评测报告文本。"""
    total = len(rows)
    passed = sum(1 for row in rows if row["valid"])
    avg = sum(row["total"] for row in rows) / total if total else 0
    failed = [row for row in rows if not row["valid"]]
    issue_counter: Counter[str] = Counter()
    for row in rows:
        issue_counter.update(row["issue_codes"])

    lines = [
        "客厅布局评测报告",
        "=" * 40,
        f"共 {total} 例，通过 {passed} 例（{passed / total * 100:.1f}%），"
        f"平均分 {avg:.1f}",
        "",
    ]
    if failed:
        lines.append("未达标案例：")
        for row in failed:
            codes = "、".join(sorted(set(row["issue_codes"]))) or "（无评分项）"
            lines.append(f"  {row['case_id']} {row['name']} {row['total']}分 [{codes}]")
        lines.append("")
    lines.append("失败原因分布（含软问题，按出现次数）：")
    for code, count in issue_counter.most_common():
        lines.append(f"  {code} × {count}")
    lines.append("")
    lines.append("逐例明细：")
    for row in rows:
        mark = "✓" if row["valid"] else "✗"
        lines.append(f"  {row['case_id']} {mark} {row['total']:>3}分 {row['name']}")
    return "\n".join(lines)


def main() -> None:
    rows = run_all()
    report = summarize(rows)
    print(report)

    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "living_room_eval.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n报告已保存到 {report_path}")


if __name__ == "__main__":
    main()
