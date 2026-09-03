from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Event, Thread

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import (
    DesignAgentEvent,
    DesignAgentTurn,
    DesignTask,
    GenerationRun,
    Product,
)
from app.schemas.design_agent import AgentTurnRequest
from app.services import design_agent_service


@pytest.fixture
def concurrent_agent_context(tmp_path):
    database_path = tmp_path / "design-agent-concurrency.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_concurrency(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(
            status="waiting_input",
            raw_user_input="帮我设计客厅",
            confirmed_requirement_json={"space_type": "客厅"},
            space_type="客厅",
        )
        db.add(task)
        db.add(
            Product(
                sku="SOFA-CONCURRENCY-001",
                name="并发测试沙发",
                category="沙发",
                room="客厅",
                style="现代简约",
                price=5000,
                data_origin="merchant",
                verification_status="verified",
                availability_status="in_stock",
                stock_quantity=5,
                region_codes=["CN-SH"],
                price_valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                price_valid_to=datetime(2027, 1, 1, tzinfo=timezone.utc),
                verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                verified_by="test:fixture",
                model_width_mm=2200,
                model_height_mm=800,
                model_depth_mm=950,
                is_active=True,
            )
        )
        db.commit()
        task_id = task.id

    try:
        yield factory, task_id
    finally:
        engine.dispose()


def _payload(client_turn_id: str, message: str = "开始设计") -> AgentTurnRequest:
    return AgentTurnRequest.model_validate(
        {
            "client_turn_id": client_turn_id,
            "message": message,
            "active_mode": "catalog_design",
            "answers": {
                "budget_max": 20000,
                "room_width_m": 4,
                "room_depth_m": 5,
                "delivery_region": "CN-SH",
            },
        }
    )


@pytest.mark.integration
def test_overlapping_different_turns_are_serialized_per_task(
    concurrent_agent_context,
    monkeypatch,
):
    factory, task_id = concurrent_agent_context
    first_entered = Event()
    release_first = Event()
    original_facts_for_turn = design_agent_service._facts_for_turn

    def block_first_turn(db, task, payload, *, turn_id):
        result = original_facts_for_turn(
            db,
            task,
            payload,
            turn_id=turn_id,
        )
        if payload.client_turn_id == "overlap-first-001":
            first_entered.set()
            assert release_first.wait(timeout=5)
        return result

    monkeypatch.setattr(
        design_agent_service,
        "_facts_for_turn",
        block_first_turn,
    )
    outcomes: dict[str, object] = {}

    def execute_first():
        with factory() as db:
            task = db.get(DesignTask, task_id)
            try:
                outcomes["first"] = design_agent_service.run_turn(
                    db,
                    task=task,
                    payload=_payload("overlap-first-001"),
                )
            except Exception as exc:  # pragma: no cover - asserted by caller
                outcomes["first"] = exc

    first_thread = Thread(target=execute_first)
    first_thread.start()
    assert first_entered.wait(timeout=5)

    try:
        with factory() as db:
            task = db.get(DesignTask, task_id)
            with pytest.raises(
                design_agent_service.AgentTurnInProgress,
                match="任务.*处理中",
            ):
                design_agent_service.run_turn(
                    db,
                    task=task,
                    payload=_payload("overlap-second-002", "换一套设计"),
                )
    finally:
        release_first.set()
        first_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert isinstance(outcomes["first"], dict)
    with factory() as db:
        task = db.get(DesignTask, task_id)
        turns = db.scalars(
            select(DesignAgentTurn).where(DesignAgentTurn.task_id == task_id)
        ).all()
        runs = db.scalars(
            select(GenerationRun).where(GenerationRun.task_id == task_id)
        ).all()
        assert len(turns) == 1
        assert len(runs) == 1
        assert task.agent_state_version == 1
        assert task.agent_state_json["run_id"] == runs[0].id


@pytest.mark.integration
def test_expired_running_turn_is_recovered_once_and_never_stays_409(
    concurrent_agent_context,
):
    factory, task_id = concurrent_agent_context
    payload = _payload("expired-running-001").model_copy(
        update={"active_mode": "custom_furniture"}
    )
    with factory() as db:
        db.add(
            DesignAgentTurn(
                task_id=task_id,
                client_turn_id=payload.client_turn_id,
                active_mode=payload.active_mode,
                intent="custom_furniture",
                status="running",
                request_json=payload.model_dump(mode="json"),
                created_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        db.commit()

    with factory() as db:
        first = design_agent_service.run_turn(
            db,
            task=db.get(DesignTask, task_id),
            payload=payload,
        )
    with factory() as db:
        second = design_agent_service.run_turn(
            db,
            task=db.get(DesignTask, task_id),
            payload=payload,
        )

    assert first == second
    assert first["status"] == "needs_human"
    assert first["exit_reason"] == "turn_lease_expired"
    assert first["active_mode"] == "custom_furniture"
    assert first["state"]["active_mode"] == "custom_furniture"
    assert first["state"]["intent"] == "custom_furniture"
    assert first["state"]["hard_errors"] == ["turn_lease_expired"]
    with factory() as db:
        turn = db.scalar(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task_id,
                DesignAgentTurn.client_turn_id == payload.client_turn_id,
            )
        )
        assert turn.status == "needs_human"
        assert turn.completed_at is not None
        assert len(
            db.scalars(
                select(DesignAgentEvent).where(DesignAgentEvent.turn_id == turn.id)
            ).all()
        ) == 1
        assert db.scalar(
            select(GenerationRun).where(GenerationRun.task_id == task_id)
        ) is None


@pytest.mark.integration
def test_completed_business_running_turn_does_not_hold_execution_lease(
    concurrent_agent_context,
):
    factory, task_id = concurrent_agent_context
    previous_payload = _payload("queued-response-001")
    with factory() as db:
        db.add(
            DesignAgentTurn(
                task_id=task_id,
                client_turn_id=previous_payload.client_turn_id,
                active_mode=previous_payload.active_mode,
                intent="design",
                status="running",
                request_json=previous_payload.model_dump(mode="json"),
                response_json={"exit_reason": "generation_queued"},
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    with factory() as db:
        response = design_agent_service.run_turn(
            db,
            task=db.get(DesignTask, task_id),
            payload=_payload("after-queued-response-002"),
        )

    assert response["turn_id"] > 0
    with factory() as db:
        turns = db.scalars(
            select(DesignAgentTurn).where(DesignAgentTurn.task_id == task_id)
        ).all()
        assert len(turns) == 2


@pytest.mark.integration
@pytest.mark.parametrize("crash_position", ["before", "after"])
def test_expired_turn_resumes_from_persisted_graph_checkpoint_without_duplicate_run(
    concurrent_agent_context,
    monkeypatch,
    crash_position,
):
    factory, task_id = concurrent_agent_context
    payload = _payload(f"checkpoint-crash-{crash_position}-001")
    original_create_run = design_agent_service.generation_run_service.create_run
    attempts = 0

    def crash_once(db, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1 and crash_position == "before":
            raise SystemExit("crash-before-generation-run")
        run = original_create_run(db, *args, **kwargs)
        if attempts == 1 and crash_position == "after":
            # 模拟外部副作用已提交、但节点结果尚未写入 pending writes。
            db.commit()
            raise SystemExit("crash-after-generation-run")
        return run

    monkeypatch.setattr(
        design_agent_service.generation_run_service,
        "create_run",
        crash_once,
    )

    with factory() as db:
        with pytest.raises(SystemExit, match=f"crash-{crash_position}"):
            design_agent_service.run_turn(
                db,
                task=db.get(DesignTask, task_id),
                payload=payload,
            )

    with factory() as db:
        turn = db.scalar(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task_id,
                DesignAgentTurn.client_turn_id == payload.client_turn_id,
            )
        )
        turn.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()

    with factory() as db:
        response = design_agent_service.run_turn(
            db,
            task=db.get(DesignTask, task_id),
            payload=payload,
        )

    assert response["exit_reason"] == "generation_queued"
    assert attempts == 2
    with factory() as db:
        assert db.scalar(
            select(func.count())
            .select_from(GenerationRun)
            .where(GenerationRun.task_id == task_id)
        ) == 1
        turn = db.scalar(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task_id,
                DesignAgentTurn.client_turn_id == payload.client_turn_id,
            )
        )
        assert turn.response_json["run_id"] == response["run_id"]


@pytest.mark.integration
def test_recovered_lease_prevents_late_executor_from_committing(
    concurrent_agent_context,
    monkeypatch,
):
    factory, task_id = concurrent_agent_context
    payload = _payload("late-executor-001")
    first_entered = Event()
    release_first = Event()
    original_facts_for_turn = design_agent_service._facts_for_turn
    outcomes: dict[str, object] = {}

    def block_old_executor(db, task, current_payload, *, turn_id):
        result = original_facts_for_turn(
            db,
            task,
            current_payload,
            turn_id=turn_id,
        )
        first_entered.set()
        assert release_first.wait(timeout=5)
        return result

    monkeypatch.setattr(
        design_agent_service,
        "_facts_for_turn",
        block_old_executor,
    )

    def execute_old_owner():
        with factory() as db:
            try:
                outcomes["old"] = design_agent_service.run_turn(
                    db,
                    task=db.get(DesignTask, task_id),
                    payload=payload,
                )
            except Exception as exc:  # pragma: no cover - asserted by caller
                outcomes["old"] = exc

    old_thread = Thread(target=execute_old_owner)
    old_thread.start()
    assert first_entered.wait(timeout=5)

    with factory() as db:
        turn = db.scalar(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task_id,
                DesignAgentTurn.client_turn_id == payload.client_turn_id,
            )
        )
        turn.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()
    with factory() as db:
        recovered = design_agent_service.run_turn(
            db,
            task=db.get(DesignTask, task_id),
            payload=payload,
        )

    release_first.set()
    old_thread.join(timeout=5)

    assert not old_thread.is_alive()
    assert outcomes["old"] == recovered
    assert recovered["exit_reason"] == "turn_lease_expired"
    with factory() as db:
        task = db.get(DesignTask, task_id)
        turn = db.scalar(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task_id,
                DesignAgentTurn.client_turn_id == payload.client_turn_id,
            )
        )
        assert task.agent_state_version == 1
        assert task.agent_state_json["exit_reason"] == "turn_lease_expired"
        assert turn.status == "needs_human"
        assert db.scalar(
            select(GenerationRun).where(GenerationRun.task_id == task_id)
        ) is None


@pytest.mark.integration
def test_checkpoint_compare_and_swap_preserves_newer_state_and_rolls_back_run(
    concurrent_agent_context,
    monkeypatch,
):
    factory, task_id = concurrent_agent_context
    concurrent_checkpoint = {
        "status": "completed",
        "active_mode": "catalog_design",
        "intent": "design",
        "current_node": "generation_completed",
        "facts": {"space_type": "客厅"},
        "fact_evidence": {},
        "pending_questions": [],
        "step_count": 9,
        "retry_count": 1,
        "max_steps": 12,
        "max_retries": 2,
        "hard_errors": [],
        "approval_required": False,
        "exit_reason": "goal_completed",
        "scene_ref": None,
        "run_id": 9876,
        "result": {"source": "concurrent-writer"},
    }
    original_facts_for_turn = design_agent_service._facts_for_turn
    concurrent_write_done = False

    def inject_concurrent_checkpoint(db, task, payload, *, turn_id):
        nonlocal concurrent_write_done
        if not concurrent_write_done:
            with factory() as other_db:
                concurrent_task = other_db.get(DesignTask, task_id)
                concurrent_task.agent_state_version = 7
                concurrent_task.agent_state_json = concurrent_checkpoint
                other_db.commit()
            concurrent_write_done = True
        return original_facts_for_turn(
            db,
            task,
            payload,
            turn_id=turn_id,
        )

    monkeypatch.setattr(
        design_agent_service,
        "_facts_for_turn",
        inject_concurrent_checkpoint,
    )

    with factory() as db:
        with pytest.raises(ValueError, match="状态版本.*冲突"):
            design_agent_service.run_turn(
                db,
                task=db.get(DesignTask, task_id),
                payload=_payload("checkpoint-cas-001"),
            )

    with factory() as db:
        task = db.get(DesignTask, task_id)
        turn = db.scalar(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task_id,
                DesignAgentTurn.client_turn_id == "checkpoint-cas-001",
            )
        )
        assert task.agent_state_version == 7
        assert task.agent_state_json == concurrent_checkpoint
        assert turn.status == "conflict"
        assert turn.response_json["code"] == "agent_state_conflict"
        assert db.scalar(
            select(GenerationRun).where(GenerationRun.task_id == task_id)
        ) is None
