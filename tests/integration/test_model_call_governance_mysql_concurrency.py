from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from threading import Barrier, Lock
from typing import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import DesignTask, ModelCallCostAccount, ModelCallLedger
from app.services import model_call_governance_service as service


@pytest.fixture(scope="module")
def mysql_engine() -> Iterator[Engine]:
    engine: Engine | None = None
    if make_url(settings.database_url).get_backend_name() != "mysql":
        pytest.skip("真实并发验收只允许 MySQL，不能用 SQLite 代替")
    try:
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=4,
            max_overflow=0,
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            tables = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = DATABASE()"
                    )
                )
            }
        required = {
            "design_tasks",
            "model_call_cost_accounts",
            "model_call_ledgers",
        }
        if not required <= tables:
            pytest.skip("MySQL 未迁移到模型成本账本版本")
        with engine.connect() as connection:
            storage_engines = dict(
                connection.execute(
                    text(
                        "SELECT table_name, engine FROM information_schema.tables "
                        "WHERE table_schema = DATABASE() "
                        "AND table_name IN "
                        "('model_call_cost_accounts', 'model_call_ledgers')"
                    )
                ).all()
            )
        if set(storage_engines.values()) != {"InnoDB"}:
            pytest.fail("模型成本并发门禁要求账户与账本表使用 InnoDB")
    except (ModuleNotFoundError, SQLAlchemyError) as exc:
        if engine is not None:
            engine.dispose()
        pytest.skip(f"当前环境没有可用的 MySQL 集成测试库: {type(exc).__name__}")

    try:
        yield engine
    finally:
        engine.dispose()


@contextmanager
def _clean_task_scope(
    engine: Engine,
) -> Iterator[tuple[sessionmaker, int, str]]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        task = DesignTask(
            status="waiting_confirm",
            progress=40,
            raw_user_input=f"mysql-cost-concurrency:{uuid4().hex}",
        )
        db.add(task)
        db.flush()
        task_id = task.id
    scope_id = str(task_id)
    try:
        yield factory, task_id, scope_id
    finally:
        with factory.begin() as db:
            account_ids = list(
                db.scalars(
                    select(ModelCallCostAccount.id).where(
                        ModelCallCostAccount.scope_kind == "task",
                        ModelCallCostAccount.scope_id == scope_id,
                    )
                )
            )
            if account_ids:
                db.execute(
                    delete(ModelCallLedger).where(
                        ModelCallLedger.account_id.in_(account_ids)
                    )
                )
                db.execute(
                    delete(ModelCallCostAccount).where(
                        ModelCallCostAccount.id.in_(account_ids)
                    )
                )
            db.execute(delete(DesignTask).where(DesignTask.id == task_id))


def _create_account(
    factory: sessionmaker,
    *,
    task_id: int,
    scope_id: str,
    cost_limit_cny: Decimal = Decimal("1.000000"),
) -> None:
    with factory.begin() as db:
        db.add(
            ModelCallCostAccount(
                scope_kind="task",
                scope_id=scope_id,
                task_id=task_id,
                cost_limit_cny=cost_limit_cny,
                allocated_cost_cny=Decimal("0.000000"),
                actual_cost_cny=Decimal("0.000000"),
                unknown_cost_call_count=0,
            )
        )


@pytest.mark.parametrize("existing_account", [False, True])
def test_cost_reservation_does_not_wait_for_own_business_task_lock(
    mysql_engine: Engine, existing_account: bool,
) -> None:
    """真实 MySQL 必须覆盖已有迁移库，ORM 无 FK 不代表实际库无 FK。"""
    with _clean_task_scope(mysql_engine) as (factory, task_id, scope_id):
        if existing_account:
            _create_account(factory, task_id=task_id, scope_id=scope_id)

        @contextmanager
        def short_wait_factory():
            with factory() as db:
                previous_timeout = db.scalar(text("SELECT @@innodb_lock_wait_timeout"))
                db.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))
                try:
                    yield db
                finally:
                    db.rollback()
                    db.execute(text(f"SET SESSION innodb_lock_wait_timeout = {int(previous_timeout)}"))
                    db.commit()

        with factory() as business:
            business.execute(select(DesignTask).where(DesignTask.id == task_id).with_for_update())
            hooks = service.build_model_call_hooks(
                session_factory=short_wait_factory,
                scope_kind="task", scope_id=scope_id, task_id=task_id,
                operation_key="business-lock-regression", cost_limit_cny=1.0,
            )
            permit = hooks.before_call(
                provider_key="local-regression-no-provider-call", model="test-model",
                modality="text", estimated_cost_cny=0.1,
            )
            assert permit.ledger_id > 0
            hooks.record_failure(permit, failure_code="local_test_no_model_call")
            business.rollback()


def test_reservation_deadlock_retry_is_bounded_and_keeps_one_call_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hooks = service.build_model_call_hooks(
        session_factory=sessionmaker(),
        scope_kind="task",
        scope_id="bounded-retry",
        task_id=1,
        operation_key="bounded-retry-operation",
        cost_limit_cny=Decimal("1.000000"),
    )
    attempts: list[int] = []

    def always_deadlock(**_kwargs):
        attempts.append(hooks._call_index)
        raise OperationalError(
            "INSERT INTO model_call_cost_accounts ...",
            {},
            RuntimeError(1213, "deadlock"),
        )

    monkeypatch.setattr(hooks, "_reserve_call", always_deadlock)

    with pytest.raises(OperationalError):
        hooks.before_call(
            provider_key="mysql-concurrency-test",
            model="test-model",
            modality="text",
            estimated_cost_cny=Decimal("0.400000"),
        )

    assert attempts == [1, 1, 1]


@pytest.mark.integration
def test_mysql_first_account_reservations_are_serialized_without_leaking_deadlock(
    mysql_engine: Engine,
) -> None:
    first_select_barrier = Barrier(2, timeout=10)
    selection_lock = Lock()
    synchronized_selects = 0

    def synchronize_first_missing_account_select(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal synchronized_selects
        normalized = statement.lower()
        if (
            "from model_call_cost_accounts" not in normalized
            or "for update" not in normalized
        ):
            return
        with selection_lock:
            if synchronized_selects >= 2:
                return
            synchronized_selects += 1
        first_select_barrier.wait()

    event.listen(
        mysql_engine,
        "after_cursor_execute",
        synchronize_first_missing_account_select,
    )
    try:
        with _clean_task_scope(mysql_engine) as (
            factory,
            task_id,
            scope_id,
        ):

            def reserve(operation_key: str):
                hooks = service.build_model_call_hooks(
                    session_factory=factory,
                    scope_kind="task",
                    scope_id=scope_id,
                    task_id=task_id,
                    operation_key=operation_key,
                    cost_limit_cny=Decimal("1.000000"),
                )
                try:
                    return hooks.before_call(
                        provider_key="mysql-concurrency-test",
                        model="test-model",
                        modality="text",
                        estimated_cost_cny=Decimal("0.600000"),
                    )
                except service.ModelCallCostLimitExceeded as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(
                    executor.map(reserve, ("concurrent:first", "concurrent:second"))
                )

            permits = [
                outcome
                for outcome in outcomes
                if isinstance(outcome, service.ModelCallPermit)
            ]
            rejected = [
                outcome
                for outcome in outcomes
                if isinstance(outcome, service.ModelCallCostLimitExceeded)
            ]
            assert len(permits) == 1
            assert len(rejected) == 1
            assert rejected[0].code == "task_model_cost_limit_exceeded"
            assert synchronized_selects == 2

            with factory() as db:
                account = db.scalar(
                    select(ModelCallCostAccount).where(
                        ModelCallCostAccount.scope_kind == "task",
                        ModelCallCostAccount.scope_id == scope_id,
                    )
                )
                rows = list(
                    db.scalars(
                        select(ModelCallLedger)
                        .where(ModelCallLedger.account_id == account.id)
                        .order_by(ModelCallLedger.id)
                    )
                )
                assert account.allocated_cost_cny == Decimal("0.600000")
                assert account.allocated_cost_cny <= account.cost_limit_cny
                assert [row.status for row in rows] == ["reserved", "blocked"]
    finally:
        event.remove(
            mysql_engine,
            "after_cursor_execute",
            synchronize_first_missing_account_select,
        )


@pytest.mark.integration
def test_mysql_concurrent_idempotent_operation_reserves_exactly_once(
    mysql_engine: Engine,
) -> None:
    start_barrier = Barrier(2, timeout=10)
    connection_lock = Lock()
    connection_ids: set[int] = set()

    def capture_account_lock_connection(
        connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = statement.lower()
        if (
            "from model_call_cost_accounts" not in normalized
            or "for update" not in normalized
        ):
            return
        with connection_lock:
            connection_ids.add(id(connection.connection.dbapi_connection))

    event.listen(
        mysql_engine,
        "after_cursor_execute",
        capture_account_lock_connection,
    )
    try:
        with _clean_task_scope(mysql_engine) as (
            factory,
            task_id,
            scope_id,
        ):
            _create_account(factory, task_id=task_id, scope_id=scope_id)

            def reserve():
                hooks = service.build_model_call_hooks(
                    session_factory=factory,
                    scope_kind="task",
                    scope_id=scope_id,
                    task_id=task_id,
                    operation_key="same-user-operation",
                    cost_limit_cny=Decimal("1.000000"),
                )
                start_barrier.wait()
                try:
                    return hooks.before_call(
                        provider_key="mysql-concurrency-test",
                        model="test-model",
                        modality="text",
                        estimated_cost_cny=Decimal("0.400000"),
                    )
                except service.ModelCallIdempotencyConflict as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = [
                    future.result()
                    for future in (executor.submit(reserve), executor.submit(reserve))
                ]

            permits = [
                outcome
                for outcome in outcomes
                if isinstance(outcome, service.ModelCallPermit)
            ]
            conflicts = [
                outcome
                for outcome in outcomes
                if isinstance(outcome, service.ModelCallIdempotencyConflict)
            ]
            assert len(connection_ids) == 2
            assert len(permits) == 1
            assert len(conflicts) == 1
            assert conflicts[0].code == "model_call_already_recorded"

            with factory() as db:
                account = db.scalar(
                    select(ModelCallCostAccount).where(
                        ModelCallCostAccount.scope_kind == "task",
                        ModelCallCostAccount.scope_id == scope_id,
                    )
                )
                rows = list(
                    db.scalars(
                        select(ModelCallLedger).where(
                            ModelCallLedger.account_id == account.id
                        )
                    )
                )
                assert account.allocated_cost_cny == Decimal("0.400000")
                assert len(rows) == 1
                assert rows[0].status == "reserved"
    finally:
        event.remove(
            mysql_engine,
            "after_cursor_execute",
            capture_account_lock_connection,
        )


@pytest.mark.integration
def test_mysql_concurrent_settlement_preserves_reserved_cost_conservation(
    mysql_engine: Engine,
) -> None:
    with _clean_task_scope(mysql_engine) as (
        factory,
        task_id,
        scope_id,
    ):
        _create_account(factory, task_id=task_id, scope_id=scope_id)
        hooks = [
            service.build_model_call_hooks(
                session_factory=factory,
                scope_kind="task",
                scope_id=scope_id,
                task_id=task_id,
                operation_key=operation_key,
                cost_limit_cny=Decimal("1.000000"),
            )
            for operation_key in ("settle:success", "settle:failure", "settle:blocked")
        ]
        permits = [
            hooks[0].before_call(
                provider_key="mysql-concurrency-test",
                model="test-model",
                modality="text",
                estimated_cost_cny=Decimal("0.400000"),
            ),
            hooks[1].before_call(
                provider_key="mysql-concurrency-test",
                model="test-model",
                modality="text",
                estimated_cost_cny=Decimal("0.300000"),
            ),
            hooks[2].before_call(
                provider_key="mysql-concurrency-test",
                model="test-model",
                modality="text",
                estimated_cost_cny=Decimal("0.200000"),
            ),
        ]
        settle_barrier = Barrier(3, timeout=10)
        ledger_lock_barrier = Barrier(3, timeout=10)
        connection_lock = Lock()
        settlement_connection_ids: set[int] = set()

        def synchronize_ledger_locks(
            connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            normalized = statement.lower()
            if (
                "from model_call_ledgers" not in normalized
                or "for update" not in normalized
            ):
                return
            with connection_lock:
                settlement_connection_ids.add(
                    id(connection.connection.dbapi_connection)
                )
            ledger_lock_barrier.wait()

        def settle_success() -> None:
            settle_barrier.wait()
            hooks[0].record_success(
                permits[0],
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 25,
                    "total_tokens": 125,
                },
                actual_cost_cny=Decimal("0.250000"),
            )

        def settle_failure() -> None:
            settle_barrier.wait()
            hooks[1].record_failure(permits[1], failure_code="provider_timeout")

        def settle_blocked() -> None:
            settle_barrier.wait()
            hooks[2].record_blocked(permits[2], failure_code="circuit_open")

        event.listen(mysql_engine, "after_cursor_execute", synchronize_ledger_locks)
        try:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [
                    executor.submit(settle_success),
                    executor.submit(settle_failure),
                    executor.submit(settle_blocked),
                ]
                for future in futures:
                    future.result()
        finally:
            event.remove(mysql_engine, "after_cursor_execute", synchronize_ledger_locks)

        assert len(settlement_connection_ids) == 3

        with factory() as db:
            account = db.scalar(
                select(ModelCallCostAccount).where(
                    ModelCallCostAccount.scope_kind == "task",
                    ModelCallCostAccount.scope_id == scope_id,
                )
            )
            rows = list(
                db.scalars(
                    select(ModelCallLedger)
                    .where(ModelCallLedger.account_id == account.id)
                    .order_by(ModelCallLedger.id)
                )
            )

            conserved_cost = sum(
                (
                    row.actual_cost_cny
                    if row.status == "succeeded" and row.actual_cost_cny is not None
                    else row.estimated_cost_cny
                    if row.status in {"reserved", "failed"}
                    else Decimal("0.000000")
                )
                for row in rows
            )
            assert [row.status for row in rows] == [
                "succeeded",
                "failed",
                "blocked",
            ]
            assert account.actual_cost_cny == Decimal("0.250000")
            assert account.unknown_cost_call_count == 1
            assert account.allocated_cost_cny == Decimal("0.550000")
            assert account.allocated_cost_cny == conserved_cost
            assert account.allocated_cost_cny <= account.cost_limit_cny
