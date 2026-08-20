import pytest

from evals.run_requirement_eval import (
    budget_deviation,
    field_accuracy,
    _field_match,
    _num_match,
    _text_match,
)


def test_budget_deviation_within_range_is_zero():
    assert budget_deviation(120000, 150000, 138000) == 0.0
    assert budget_deviation(120000, 150000, 150000) == 0.0
    assert budget_deviation(120000, 150000, 120000) == 0.0


def test_budget_deviation_over_and_under():
    # 超预算 3 万 / 范围 3 万 = 100%
    assert budget_deviation(120000, 150000, 180000) == pytest.approx(1.0)
    # 低于预算 2 万 / 范围 3 万
    assert budget_deviation(120000, 150000, 100000) == pytest.approx(20000 / 30000)


def test_budget_deviation_zero_span():
    assert budget_deviation(100000, 100000, 150000) == 0.0


def test_field_accuracy_all_match():
    expected = {
        "space_type": "客厅",
        "style": "奶油风",
        "area": 25,
        "budget_max": 30000,
        "constraints": ["不改水电"],
        "custom_projects": [],
    }
    parsed = {
        "space_type": "客厅",
        "style": "奶油风",
        "area": 25,
        "budget": {"max_budget": 30000},
        "constraints": ["不改水电"],
        "custom_projects": [],
    }
    assert field_accuracy(expected, parsed) == 1.0


def test_field_accuracy_partial_match():
    expected = {
        "space_type": "卧室",
        "style": "现代简约",
        "area": 10,
        "budget_max": 20000,
        "constraints": [],
        "custom_projects": ["衣柜"],
    }
    parsed = {
        "space_type": "客厅",
        "style": "现代简约",
        "area": 10,
        "budget": {"max_budget": 20000},
        "constraints": [],
        "custom_projects": ["衣柜", "储物柜"],
    }
    # space_type 错（1/6 扣分），其余对
    assert field_accuracy(expected, parsed) == pytest.approx(5 / 6)


def test_num_match_handles_unspecified_and_tolerance():
    assert _num_match(150000, 150000) is True
    assert _num_match(150000, 151000) is True  # 1% 容差内
    assert _num_match(150000, 200000) is False
    assert _num_match(None, "未指定") is True
    assert _num_match(150000, "未指定") is False
    assert _num_match(None, None) is True


def test_text_match_contains():
    assert _text_match("原木风", "奶油原木风") is True
    assert _text_match("原木风", "奶油风") is False
    assert _text_match(None, None) is True
    assert _text_match("客厅", None) is False


def test_list_field_requires_expected_subset():
    assert _field_match("constraints", ["不拆墙"], ["不拆墙", "不改水电"]) is True
    assert _field_match("constraints", ["不拆墙"], []) is False
    assert _field_match("custom_projects", [], ["衣柜"]) is True
