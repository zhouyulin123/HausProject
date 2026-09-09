"""M3 评测体系：跨空间（客厅/卧室/餐厅/书房）布局评测验收。

对齐专家 M3 的「建立 AI 评测体系」——先用确定性布局评测集量化当前能力，
后续再扩展需求提取/约束遵守/预算偏差等需要 LLM 的指标。
"""

import pytest

from evals.run_layout_eval import _group_stats, all_cases, run_all

# 验收标准
TOTAL_PASS_RATE_THRESHOLD = 0.9
SPACE_PASS_RATE_THRESHOLD = 0.8
MIN_CASE_COUNT = 30


@pytest.mark.integration
def test_layout_eval_has_30_plus_cases():
    assert len(all_cases()) >= MIN_CASE_COUNT


@pytest.mark.integration
def test_layout_eval_overall_pass_rate():
    rows = run_all()
    assert len(rows) == len(all_cases())

    passed = sum(1 for row in rows if row["valid"])
    pass_rate = passed / len(rows)

    assert pass_rate >= TOTAL_PASS_RATE_THRESHOLD, (
        f"跨空间布局通过率 {pass_rate:.0%} 低于验收线 "
        f"{TOTAL_PASS_RATE_THRESHOLD:.0%}"
    )


@pytest.mark.integration
def test_layout_eval_every_space_meets_minimum_pass_rate():
    rows = run_all()
    stats = _group_stats(rows)

    # 四个空间都应参与评测
    assert set(stats) == {"living", "bedroom", "dining", "study"}

    for group, stat in stats.items():
        assert stat["pass_rate"] >= SPACE_PASS_RATE_THRESHOLD, (
            f"{group} 通过率 {stat['pass_rate']:.0%} 低于验收线 "
            f"{SPACE_PASS_RATE_THRESHOLD:.0%}"
        )


@pytest.mark.integration
def test_layout_eval_average_score_is_reasonable():
    rows = run_all()
    average = sum(row["total"] for row in rows) / len(rows)

    assert average >= 70, f"跨空间布局平均分 {average:.1f} 低于验收线"
