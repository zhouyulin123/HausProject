import json

import httpx
import pytest
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


def test_non_availability_provider_error_releases_half_open_permit(monkeypatch):
    request = httpx.Request("POST", "https://provider.example/v1/chat")

    class Completions:
        def create(self, **kwargs):
            raise APIStatusError(
                "invalid",
                response=httpx.Response(400, request=request),
                body=None,
            )

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
        before_call=lambda provider_key: events.append(("before", provider_key))
        or permit,
        record_success=lambda value: events.append(("success", value)),
        record_failure=lambda value, code: events.append(("failure", value, code)),
        release_call=lambda value: events.append(("release", value)),
    )

    with llm_service.provider_call_guard(hooks):
        with pytest.raises(llm_service.LLMUnavailable):
            llm_service._chat_json("system", "user", max_tokens=100)

    assert events == [
        ("before", "primary-llm"),
        ("release", permit),
    ]


def test_generation_meta_separates_static_prompt_version_from_full_dynamic_input(
    monkeypatch,
):
    required_plan = {
        "name": "方案",
        "style": "现代",
        "budget": 10000,
        "furnitureSuggestions": [{"sku": "SKU-1"}],
        "customItems": [],
        "colorPalette": ["白色"],
        "budgetBreakdown": [{"name": "家具", "percent": 100, "amount": 10000}],
    }
    captured: dict[str, str] = {}

    def fake_chat(system, user, **_kwargs):
        captured.update(system=system, user=user)
        return {"plans": [dict(required_plan), dict(required_plan)]}

    monkeypatch.setattr(llm_service, "_chat_json", fake_chat)
    tail_marker = "TAIL-MUST-BE-DIGESTED"
    llm_service.generate_plans(
        {"notes": "x" * 9000 + tail_marker},
        "catalog-versioned-context",
    )

    meta = llm_service.last_generation_meta()
    assert meta is not None
    assert tail_marker not in meta["prompt_snapshot"]
    assert tail_marker in meta["input_snapshot"]["user"]
    assert meta["input_snapshot"]["user"] == captured["user"]
    assert meta["prompt_snapshot"] != (
        captured["system"] + "\n\n" + captured["user"]
    )
    assert meta["provenance_schema_version"] == 4
    prompt_contract = json.loads(meta["prompt_snapshot"])
    assert prompt_contract["request_contract"]["tools"] == []
    assert prompt_contract["output_contract"]["minimum_valid_plans"] == 2
    assert (
        "budgetBreakdown"
        in prompt_contract["output_contract"]["required_plan_keys"]
    )


def test_generated_plans_do_not_publish_model_self_reported_match_scores(monkeypatch):
    required_plan = {
        "name": "方案",
        "style": "现代",
        "score": 99,
        "budget": 10000,
        "furnitureSuggestions": [{"sku": "SKU-1"}],
        "customItems": [],
        "colorPalette": ["白色"],
        "budgetBreakdown": [{"name": "家具", "percent": 100, "amount": 10000}],
    }
    monkeypatch.setattr(
        llm_service,
        "_chat_json",
        lambda *_args, **_kwargs: {
            "plans": [dict(required_plan), dict(required_plan)]
        },
    )

    plans = llm_service.generate_plans({}, "catalog-context")

    assert all("score" not in plan for plan in plans)
    assert '"score"' not in llm_service._PLAN_SYSTEM
