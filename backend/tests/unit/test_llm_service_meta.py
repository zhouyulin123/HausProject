import pytest

from app.services import llm_service
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


def test_model_call_cost_ceiling_uses_prompt_bytes_and_output_limit():
    cost = llm_service.estimate_model_call_cost_ceiling_cny(
        system="a",
        user="中",
        max_tokens=100,
        input_price_per_mtok=2.0,
        output_price_per_mtok=8.0,
    )

    # 1 + 3 个 UTF-8 字节，加 256 个消息格式 token 上界。
    assert cost == pytest.approx(((260 * 2.0) + (100 * 8.0)) / 1_000_000)


def test_model_cost_guard_runs_before_provider_and_is_not_converted(monkeypatch):
    provider_called = False

    class Completions:
        def create(self, **kwargs):
            nonlocal provider_called
            provider_called = True
            raise AssertionError("预算拒绝后不能调用供应商")

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    monkeypatch.setattr(llm_service, "get_client", lambda: client)

    class BudgetRejected(RuntimeError):
        pass

    def reject(_estimated_cost):
        raise BudgetRejected("超出任务成本上限")

    with llm_service.model_cost_guard(reject):
        with pytest.raises(BudgetRejected, match="成本上限"):
            llm_service._chat_json("system", "user", max_tokens=100)

    assert provider_called is False
