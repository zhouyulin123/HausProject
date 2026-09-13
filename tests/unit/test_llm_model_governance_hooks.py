from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.db.database import Base
from app.db.models import ModelCallCostAccount, ModelCallLedger, ModelProviderCircuit
from app.services import llm_service
from app.services import model_call_governance_service as governance


class _Hooks:
    def __init__(self):
        self.calls = []

    def before_call(self, **kwargs):
        self.calls.append(("before", kwargs))
        return "permit"

    def record_success(self, permit, *, usage, actual_cost_cny):
        self.calls.append(("success", permit, usage, actual_cost_cny))

    def record_failure(self, permit, *, failure_code):
        self.calls.append(("failure", permit, failure_code))


def _response(content: str):
    usage = SimpleNamespace(prompt_tokens=12, completion_tokens=3, total_tokens=15)
    return SimpleNamespace(
        usage=usage,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def test_plain_text_chat_uses_same_governance_hooks(monkeypatch):
    hooks = _Hooks()
    completions = SimpleNamespace(create=lambda **_kwargs: _response("好的"))
    monkeypatch.setattr(
        llm_service,
        "get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 8.0)

    with llm_service.model_call_governance(hooks):
        assert llm_service.chat_reply("请帮我设计") == "好的"

    assert hooks.calls[0][0] == "before"
    assert hooks.calls[0][1]["provider_key"] == llm_service.settings.llm_provider_key
    assert hooks.calls[0][1]["modality"] == "text"
    assert hooks.calls[-1][0] == "success"
    assert hooks.calls[-1][2]["total_tokens"] == 15


def test_vision_call_uses_vision_provider_and_price(monkeypatch):
    hooks = _Hooks()
    payload = (
        '{"imageKind":"other","spaceType":"未知空间","roomCount":"",'
        '"rooms":[],"walls":[],"doors":[],"windows":[],"fixedObstacles":[],'
        '"existingFurniture":[],"scale":{"source":"default",'
        '"referenceWallLength":null,"referenceRoomId":null,'
        '"referenceWallIndex":null,"confidence":0.3},"confidence":0.3,'
        '"requiresConfirmation":[],"analysisNotes":[],"suggestions":[]}'
    )
    completions = SimpleNamespace(create=lambda **_kwargs: _response(payload))
    monkeypatch.setattr(
        llm_service,
        "get_vl_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    monkeypatch.setattr(llm_service.settings, "vl_input_price_per_mtok", 3.0)
    monkeypatch.setattr(llm_service.settings, "vl_output_price_per_mtok", 9.0)

    with llm_service.model_call_governance(hooks):
        llm_service.analyze_room_model(b"image", "room.png")

    before = hooks.calls[0][1]
    assert before["provider_key"] == llm_service.settings.vl_provider_key
    assert before["model"] == llm_service.settings.vl_model
    assert before["modality"] == "vision"
    assert hooks.calls[-1][0] == "success"


def test_availability_failure_is_reported_once_to_governance(monkeypatch):
    hooks = _Hooks()

    def fail(**_kwargs):
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(
        llm_service,
        "get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fail))
        ),
    )
    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 8.0)

    with llm_service.model_call_governance(hooks):
        try:
            llm_service.chat_reply("测试")
        except llm_service.LLMUnavailable:
            pass
        else:
            raise AssertionError("上游超时必须向调用方报告不可用")

    assert [call[0] for call in hooks.calls] == ["before", "failure"]
    assert hooks.calls[-1][2] == "timeout"


def test_persistent_circuit_blocks_next_operation_without_consuming_reservation(
    monkeypatch,
):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def fail(**_kwargs):
        raise TimeoutError("provider timeout")

    monkeypatch.setattr(
        llm_service,
        "get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fail))
        ),
    )
    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 8.0)

    provider_hooks = governance.build_provider_hooks(
        session_factory=factory,
        failure_threshold=1,
        cooldown_seconds=60,
        probe_lease_seconds=10,
    )
    first_cost_hooks = governance.build_model_call_hooks(
        session_factory=factory,
        scope_kind="session",
        scope_id="demo-session",
        task_id=None,
        operation_key="demo:first",
        cost_limit_cny=1.0,
    )
    with (
        llm_service.provider_call_guard(provider_hooks),
        llm_service.model_call_governance(first_cost_hooks),
    ):
        try:
            llm_service._chat_json("system", "first", max_tokens=100)
        except llm_service.LLMUnavailable:
            pass

    second_cost_hooks = governance.build_model_call_hooks(
        session_factory=factory,
        scope_kind="session",
        scope_id="demo-session",
        task_id=None,
        operation_key="demo:second",
        cost_limit_cny=1.0,
    )
    with (
        llm_service.provider_call_guard(provider_hooks),
        llm_service.model_call_governance(second_cost_hooks),
    ):
        try:
            llm_service._chat_json("system", "second", max_tokens=100)
        except governance.ModelProviderUnavailable as exc:
            assert exc.code == "provider_circuit_open"
        else:
            raise AssertionError("熔断开启后下一业务操作必须在供应商调用前拒绝")

    with factory() as db:
        account = db.scalar(select(ModelCallCostAccount))
        ledgers = list(
            db.scalars(select(ModelCallLedger).order_by(ModelCallLedger.id))
        )
        circuit = db.scalar(select(ModelProviderCircuit))
        assert circuit.state == "open"
        assert [row.status for row in ledgers] == ["failed", "blocked"]
        assert ledgers[1].failure_code == "provider_circuit_open"
        assert account.allocated_cost_cny == pytest.approx(
            ledgers[0].estimated_cost_cny
        )


def test_governance_rejection_preserves_stable_exception_code(monkeypatch):
    rejection = governance.ModelCallCostLimitExceeded(
        "cost blocked",
        code="task_model_cost_limit_exceeded",
    )

    class RejectingHooks:
        def before_call(self, **_kwargs):
            raise rejection

    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 8.0)

    with llm_service.model_call_governance(RejectingHooks()):
        with pytest.raises(governance.ModelCallCostLimitExceeded) as captured:
            llm_service._chat_json("system", "user", max_tokens=100)

    assert captured.value is rejection
    assert captured.value.code == "task_model_cost_limit_exceeded"


@pytest.mark.parametrize("provider_failure", [False, True])
def test_provider_permit_is_always_settled_when_ledger_settlement_fails(
    monkeypatch,
    provider_failure,
):
    provider_events = []

    class ProviderHooks:
        def before_call(self, _provider_key):
            provider_events.append("acquired")
            return "provider-permit"

        def record_success(self, _permit):
            provider_events.append("success")

        def record_failure(self, _permit, _failure_code):
            provider_events.append("failure")

        def release_call(self, _permit):
            provider_events.append("released")

    class BrokenLedgerHooks:
        def before_call(self, **_kwargs):
            return "ledger-permit"

        def record_success(self, _permit, **_kwargs):
            raise RuntimeError("ledger settlement failed")

        def record_failure(self, _permit, **_kwargs):
            raise RuntimeError("ledger settlement failed")

    def complete(**_kwargs):
        if provider_failure:
            raise TimeoutError("provider timeout")
        return _response('{"ok":true}')

    monkeypatch.setattr(
        llm_service,
        "get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=complete))
        ),
    )
    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 8.0)

    with (
        llm_service.provider_call_guard(ProviderHooks()),
        llm_service.model_call_governance(BrokenLedgerHooks()),
    ):
        with pytest.raises(RuntimeError, match="ledger settlement failed"):
            llm_service._chat_json("system", "user", max_tokens=100)

    assert provider_events == [
        "acquired",
        "failure" if provider_failure else "success",
    ]
