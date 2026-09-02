import pytest
import httpx
from openai import APIStatusError, APITimeoutError

from app.core.request_context import bind_request_id
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


def test_provider_request_uses_bound_client_request_id():
    with bind_request_id("generation-request-001"):
        kwargs = llm_service._provider_request_kwargs()

    assert kwargs == {
        "extra_headers": {"X-Client-Request-Id": "generation-request-001"}
    }
    assert llm_service._provider_request_kwargs() == {}


def test_only_provider_availability_errors_are_classified_for_circuit():
    request = httpx.Request("POST", "https://provider.example/v1/chat")
    timeout = APITimeoutError(request=request)
    rate_limit = APIStatusError(
        "limited",
        response=httpx.Response(429, request=request),
        body=None,
    )
    server_error = APIStatusError(
        "unavailable",
        response=httpx.Response(503, request=request),
        body=None,
    )
    bad_request = APIStatusError(
        "invalid",
        response=httpx.Response(400, request=request),
        body=None,
    )

    assert llm_service.provider_failure_code(timeout) == "timeout"
    assert llm_service.provider_failure_code(rate_limit) == "rate_limited"
    assert llm_service.provider_failure_code(server_error) == "server_error"
    assert llm_service.provider_failure_code(bad_request) is None
    assert llm_service.provider_failure_code(ValueError("code bug")) is None


def test_invalid_provider_payload_does_not_record_availability_failure(
    monkeypatch,
):
    class Completions:
        def create(self, **kwargs):
            message = type("Message", (), {"content": "not-json"})()
            choice = type("Choice", (), {"message": message})()
            return type(
                "Response",
                (),
                {"choices": [choice], "usage": None},
            )()

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    monkeypatch.setattr(llm_service, "get_client", lambda: client)
    monkeypatch.setattr(llm_service.settings, "llm_provider_key", "primary-llm")
    events = []
    permit = object()
    hooks = llm_service.ProviderCallHooks(
        before_call=lambda provider_key: events.append(
            ("before", provider_key)
        )
        or permit,
        record_success=lambda value: events.append(("success", value)),
        record_failure=lambda value, code: events.append(
            ("failure", value, code)
        ),
        release_call=lambda value: events.append(("release", value)),
    )

    with llm_service.provider_call_guard(hooks):
        with pytest.raises(llm_service.LLMUnavailable):
            llm_service._chat_json("system", "user", max_tokens=100)

    assert events == [
        ("before", "primary-llm"),
        ("success", permit),
    ]
