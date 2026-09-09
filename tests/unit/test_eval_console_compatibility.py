from evals.run_layout_eval import summarize as summarize_layout
from evals.run_living_room_eval import summarize as summarize_living_room
from evals.run_requirement_eval import summarize as summarize_requirement


def test_layout_reports_are_printable_on_default_windows_gbk_console():
    living_rows = [
        {
            "case_id": "living-1",
            "name": "客厅案例",
            "total": 95,
            "valid": True,
            "issue_codes": [],
        }
    ]
    layout_rows = [{**living_rows[0], "group": "living"}]

    summarize_living_room(living_rows).encode("gbk")
    summarize_layout(layout_rows).encode("gbk")


def test_requirement_report_is_printable_on_default_windows_gbk_console():
    report = summarize_requirement(
        [{"id": "req-1", "name": "需求案例", "accuracy": 1.0}],
        [{"id": "budget-1", "name": "预算案例", "deviation": 0.0}],
        [
            {
                "id": "constraint-1",
                "name": "约束案例",
                "compliant": True,
                "expected": True,
                "judge_correct": True,
                "reason": "满足人工标注",
            }
        ],
    )

    report.encode("gbk")
