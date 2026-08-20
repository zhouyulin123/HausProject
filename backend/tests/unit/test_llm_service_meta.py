from app.services.llm_service import estimate_cost_cny


def test_estimate_cost_returns_none_without_prices():
    usage = {"prompt_tokens": 1200, "completion_tokens": 800, "total_tokens": 2000}
    assert estimate_cost_cny(usage, None, None) is None
    assert estimate_cost_cny(usage, 1.0, None) is None
    assert estimate_cost_cny(None, 1.0, 1.0) is None


def test_estimate_cost_computes_cny():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 500_000, "total_tokens": 1_500_000}
    cost = estimate_cost_cny(usage, 2.0, 8.0)
    # 1M * 2 + 0.5M * 8 = 2 + 4 = 6 元
    assert cost == 6.0


def test_estimate_cost_ignores_non_int_tokens():
    usage = {"prompt_tokens": "not-a-number", "completion_tokens": 100}
    assert estimate_cost_cny(usage, 2.0, 8.0) is None
    # 缺失字段按 0 计，不报错
    assert estimate_cost_cny({"completion_tokens": 100}, 2.0, 8.0) == 0.0008
