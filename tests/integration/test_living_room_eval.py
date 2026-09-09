"""M2 验收评测：20 例标准客厅，布局引擎自动产出无需手动救场的场景。"""

import pytest

from evals.cases.living_room import CASES
from evals.run_living_room_eval import run_all

# 验收标准（对齐专家 M2）：20 例标准客厅中大部分方案无需手动救场
PASS_RATE_THRESHOLD = 0.9
AVERAGE_SCORE_THRESHOLD = 70


@pytest.mark.integration
def test_living_room_eval_has_20_cases():
    assert len(CASES) == 20


@pytest.mark.integration
def test_living_room_eval_pass_rate_meets_acceptance():
    rows = run_all()
    assert len(rows) == len(CASES)

    passed = sum(1 for row in rows if row["valid"])
    pass_rate = passed / len(rows)

    assert pass_rate >= PASS_RATE_THRESHOLD, (
        f"客厅布局通过率 {pass_rate:.0%} 低于验收线 "
        f"{PASS_RATE_THRESHOLD:.0%}"
    )


@pytest.mark.integration
def test_living_room_eval_average_score_is_reasonable():
    rows = run_all()
    average = sum(row["total"] for row in rows) / len(rows)

    assert average >= AVERAGE_SCORE_THRESHOLD, (
        f"客厅布局平均分 {average:.1f} 低于验收线 "
        f"{AVERAGE_SCORE_THRESHOLD}"
    )


@pytest.mark.integration
def test_living_room_eval_every_case_has_a_best_layout():
    rows = run_all()
    # 每个案例都应生成至少一组候选布局（不会返回空）
    assert len(rows) == len(CASES)
    for row in rows:
        assert row["total"] >= 0
        assert isinstance(row["issue_codes"], list)
