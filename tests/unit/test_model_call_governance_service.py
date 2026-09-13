from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import (
    DesignTask,
    ModelCallCostAccount,
    ModelCallLedger,
    TaskExecutionEvent,
)
from app.services import model_call_governance_service as service


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_cost_account_enforces_cumulative_limit_and_persists_call_ledger():
    factory = _session_factory()
    hooks = service.build_model_call_hooks(
        session_factory=factory,
        scope_kind="task",
        scope_id="41",
        task_id=41,
        operation_key="agent-turn:turn-1",
        cost_limit_cny=1.0,
    )

    first = hooks.before_call(
        provider_key="text-primary",
        model="model-v1",
        modality="text",
        estimated_cost_cny=0.6,
    )
    hooks.record_success(
        first,
        usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        actual_cost_cny=0.4,
    )

    second = hooks.before_call(
        provider_key="text-primary",
        model="model-v1",
        modality="text",
        estimated_cost_cny=0.6,
    )
    hooks.record_failure(second, failure_code="timeout")

    try:
        hooks.before_call(
            provider_key="text-primary",
            model="model-v1",
            modality="text",
            estimated_cost_cny=0.01,
        )
    except service.ModelCallCostLimitExceeded as exc:
        assert exc.code == "task_model_cost_limit_exceeded"
    else:
        raise AssertionError("累计成本达到上限后必须在供应商调用前失败关闭")

    with factory() as db:
        account = db.scalar(select(ModelCallCostAccount))
        rows = list(db.scalars(select(ModelCallLedger).order_by(ModelCallLedger.call_index)))
        assert account.scope_kind == "task"
        assert account.scope_id == "41"
        assert account.cost_limit_cny == Decimal("1.000000")
        assert account.allocated_cost_cny == Decimal("1.000000")
        assert account.actual_cost_cny == Decimal("0.400000")
        assert account.unknown_cost_call_count == 1
        assert [row.status for row in rows] == ["succeeded", "failed", "blocked"]
        assert rows[0].usage_json["total_tokens"] == 120
        assert rows[0].actual_cost_cny == Decimal("0.400000")
        assert rows[0].operation_key.startswith("sha256:")
        assert rows[0].operation_key != "agent-turn:turn-1"
        assert rows[1].failure_code == "timeout"
        assert rows[2].failure_code == "task_model_cost_limit_exceeded"


def test_missing_price_configuration_blocks_before_provider_call():
    factory = _session_factory()
    hooks = service.build_model_call_hooks(
        session_factory=factory,
        scope_kind="task",
        scope_id="7",
        task_id=7,
        operation_key="requirement:7:v1",
        cost_limit_cny=1.0,
    )

    try:
        hooks.before_call(
            provider_key="text-primary",
            model="model-v1",
            modality="text",
            estimated_cost_cny=None,
        )
    except service.ModelCallCostConfigurationError as exc:
        assert exc.code == "model_price_not_configured"
    else:
        raise AssertionError("未配置模型单价时不能绕过成本硬门禁")

    with factory() as db:
        row = db.scalar(select(ModelCallLedger))
        assert row.status == "blocked"
        assert row.failure_code == "model_price_not_configured"


def test_operation_key_reuse_cannot_duplicate_a_provider_call():
    factory = _session_factory()
    kwargs = dict(
        session_factory=factory,
        scope_kind="task",
        scope_id="9",
        task_id=9,
        operation_key="open-geometry:stable-key",
        cost_limit_cny=1.0,
    )
    first_hooks = service.build_model_call_hooks(**kwargs)
    permit = first_hooks.before_call(
        provider_key="text-primary",
        model="model-v1",
        modality="text",
        estimated_cost_cny=0.2,
    )
    first_hooks.record_success(
        permit,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        actual_cost_cny=0.1,
    )

    replay_hooks = service.build_model_call_hooks(**kwargs)
    try:
        replay_hooks.before_call(
            provider_key="text-primary",
            model="model-v1",
            modality="text",
            estimated_cost_cny=0.2,
        )
    except service.ModelCallIdempotencyConflict as exc:
        assert exc.code == "model_call_already_recorded"
    else:
        raise AssertionError("同一操作的同序号调用不能再次请求供应商")


def test_new_account_inherits_legacy_task_cost_before_reserving():
    factory = _session_factory()
    with factory() as db:
        task = DesignTask(status="waiting_confirm", progress=40)
        db.add(task)
        db.flush()
        db.add(
            TaskExecutionEvent(
                task_id=task.id,
                source_type="requirement",
                source_id=1,
                attempt=1,
                event_code="requirement.completed",
                billing_status="metered",
                cost_cny=0.8,
                event_key="requirement:legacy:completed",
            )
        )
        db.commit()
        task_id = task.id

    hooks = service.build_model_call_hooks(
        session_factory=factory,
        scope_kind="task",
        scope_id=str(task_id),
        task_id=task_id,
        operation_key="agent:new-turn",
        cost_limit_cny=1.0,
    )
    try:
        hooks.before_call(
            provider_key="text-primary",
            model="model-v1",
            modality="text",
            estimated_cost_cny=0.3,
        )
    except service.ModelCallCostLimitExceeded:
        pass
    else:
        raise AssertionError("升级前已产生的任务成本必须计入统一冻结上限")

    with factory() as db:
        account = db.scalar(select(ModelCallCostAccount))
        assert account.actual_cost_cny == Decimal("0.800000")
        assert account.allocated_cost_cny == Decimal("0.800000")


def test_budget_reservations_use_account_row_lock_and_shared_frozen_limit():
    statement = service._cost_account_lock_statement(
        scope_kind="task",
        scope_id="91",
    )
    compiled = str(statement.compile(dialect=mysql.dialect())).upper()
    assert "FOR UPDATE" in compiled

    factory = _session_factory()
    first_hooks = service.build_model_call_hooks(
        session_factory=factory,
        scope_kind="task",
        scope_id="91",
        task_id=91,
        operation_key="agent:first",
        cost_limit_cny=1.0,
    )
    second_hooks = service.build_model_call_hooks(
        session_factory=factory,
        scope_kind="task",
        scope_id="91",
        task_id=91,
        operation_key="agent:second",
        cost_limit_cny=1.0,
    )

    first_hooks.before_call(
        provider_key="text-primary",
        model="model-v1",
        modality="text",
        estimated_cost_cny=0.6,
    )
    try:
        second_hooks.before_call(
            provider_key="text-primary",
            model="model-v1",
            modality="text",
            estimated_cost_cny=0.6,
        )
    except service.ModelCallCostLimitExceeded:
        pass
    else:
        raise AssertionError("并行操作必须在同一账户行锁内串行化预算预留")

    with factory() as db:
        account = db.scalar(select(ModelCallCostAccount))
        assert account.allocated_cost_cny == Decimal("0.600000")
