from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import AgentApproval, DesignAgentTurn, DesignTask, TaskExecutionEvent
from app.services import agent_approval_service


def _task_and_turn(db):
    task = DesignTask(status="needs_human")
    db.add(task)
    db.flush()
    turn = DesignAgentTurn(
        task_id=task.id,
        client_turn_id="approval-turn-001",
        active_mode="catalog_design",
        intent="design",
        status="needs_human",
        request_json={"message": "请审核"},
    )
    db.add(turn)
    db.flush()
    return task, turn


@pytest.mark.parametrize(
    ("state", "approval_type", "reason_code"),
    [
        (
            {
                "status": "needs_human",
                "exit_reason": "approval_required",
                "current_node": "request_approval",
                "hard_errors": [],
                "result": {
                    "quote_preview": {
                        "status": "needs_human",
                        "reason_code": "quote_rule_missing",
                    }
                },
            },
            "quote_review",
            "quote_rule_missing",
        ),
        (
            {
                "status": "needs_human",
                "exit_reason": "safety_blocked",
                "current_node": "escalate",
                "hard_errors": ["load_bearing_structure_change"],
            },
            "construction_risk",
            "load_bearing_structure_change",
        ),
        (
            {
                "status": "needs_human",
                "exit_reason": "retry_exhausted",
                "current_node": "escalate",
                "hard_errors": ["layout_hard_conflict"],
            },
            "quality_gate",
            "layout_hard_conflict",
        ),
    ],
)
def test_needs_human_creates_one_typed_idempotent_approval(
    state,
    approval_type,
    reason_code,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task, turn = _task_and_turn(db)

        first = agent_approval_service.ensure_for_agent_handoff(
            db,
            task=task,
            turn=turn,
            state=state,
        )
        second = agent_approval_service.ensure_for_agent_handoff(
            db,
            task=task,
            turn=turn,
            state=state,
        )

        assert first is not None
        assert second is not None
        assert second.id == first.id
        assert first.approval_type == approval_type
        assert first.reason_code == reason_code
        assert first.status == "pending"
        assert first.requested_at is not None
        assert db.scalar(select(func.count(AgentApproval.id))) == 1


def test_non_handoff_state_does_not_create_approval():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task, turn = _task_and_turn(db)

        approval = agent_approval_service.ensure_for_agent_handoff(
            db,
            task=task,
            turn=turn,
            state={"status": "completed", "exit_reason": "completed"},
        )

        assert approval is None


def test_approval_decision_is_atomic_under_competing_writers(tmp_path):
    database_path = tmp_path / "approval-concurrency.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task, turn = _task_and_turn(db)
        approval = agent_approval_service.ensure_for_agent_handoff(
            db,
            task=task,
            turn=turn,
            state={
                "status": "needs_human",
                "exit_reason": "retry_exhausted",
                "hard_errors": ["layout_hard_conflict"],
            },
        )
        db.commit()
        approval_id = approval.id
        task_id = task.id

    barrier = Barrier(2)

    def decide(decision: str, client_decision_id: str):
        with factory() as db:
            barrier.wait()
            try:
                result = agent_approval_service.decide_approval(
                    db,
                    task_id=task_id,
                    approval_id=approval_id,
                    decision=decision,
                    conclusion=f"并发结论 {decision}",
                    client_decision_id=client_decision_id,
                    decided_by_type="session",
                    decided_by_id=client_decision_id,
                    decided_at=datetime.now(timezone.utc),
                )
                db.commit()
                return result.decision
            except agent_approval_service.ApprovalDecisionConflict:
                db.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda args: decide(*args),
                [("approve", "decision-approve"), ("reject", "decision-reject")],
            )
        )

    assert outcomes.count("conflict") == 1
    assert sorted(outcomes) in (["approve", "conflict"], ["conflict", "reject"])
    with factory() as db:
        persisted = db.get(AgentApproval, approval_id)
        assert persisted.status in {"approved", "rejected"}
        assert persisted.decided_by_type == "session"
        assert persisted.decided_at is not None


def test_decision_id_cannot_be_reused_for_another_approval_in_same_task():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task, first_turn = _task_and_turn(db)
        second_turn = DesignAgentTurn(
            task_id=task.id,
            client_turn_id="approval-turn-002",
            active_mode="catalog_design",
            intent="design",
            status="needs_human",
            request_json={"message": "再次审核"},
        )
        db.add(second_turn)
        db.flush()
        state = {
            "status": "needs_human",
            "exit_reason": "retry_exhausted",
            "hard_errors": ["layout_hard_conflict"],
        }
        first = agent_approval_service.ensure_for_agent_handoff(
            db,
            task=task,
            turn=first_turn,
            state=state,
        )
        second = agent_approval_service.ensure_for_agent_handoff(
            db,
            task=task,
            turn=second_turn,
            state=state,
        )
        agent_approval_service.decide_approval(
            db,
            task_id=task.id,
            approval_id=first.id,
            decision="approve",
            conclusion="第一项通过",
            client_decision_id="shared-decision-id",
            decided_by_type="session",
            decided_by_id="owner",
        )

        with pytest.raises(
            agent_approval_service.ApprovalDecisionConflict,
            match="幂等键",
        ):
            agent_approval_service.decide_approval(
                db,
                task_id=task.id,
                approval_id=second.id,
                decision="reject",
                conclusion="第二项拒绝",
                client_decision_id="shared-decision-id",
                decided_by_type="session",
                decided_by_id="owner",
            )


@pytest.mark.parametrize(
    (
        "approval_type",
        "decision",
        "expected_status",
        "expected_task_status",
        "expected_exit",
    ),
    [
        (
            "quote_review",
            "approve",
            "waiting_user",
            "waiting_input",
            "approval_recorded",
        ),
        (
            "quality_gate",
            "reject",
            "waiting_user",
            "waiting_input",
            "quality_revision_required",
        ),
        (
            "construction_risk",
            "approve",
            "waiting_user",
            "waiting_input",
            "safety_user_revision_required",
        ),
    ],
)
def test_decision_converges_agent_checkpoint_without_bypassing_hard_gates(
    approval_type,
    decision,
    expected_status,
    expected_task_status,
    expected_exit,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task, turn = _task_and_turn(db)
        state_by_type = {
            "quote_review": {
                "exit_reason": "approval_required",
                "hard_errors": ["quote_rule_missing"],
            },
            "quality_gate": {
                "exit_reason": "retry_exhausted",
                "hard_errors": ["layout_hard_conflict"],
            },
            "construction_risk": {
                "exit_reason": "safety_blocked",
                "hard_errors": ["load_bearing_structure_change"],
            },
        }
        task.agent_state_json = {
            "status": "needs_human",
            "current_node": "request_approval",
            "approval_required": True,
            **state_by_type[approval_type],
            "step_count": 4,
            "retry_count": 1,
        }
        original_turn_status = turn.status
        turn.response_json = {
            "task_id": task.id,
            "turn_id": turn.id,
            "state_version": 0,
            "status": "needs_human",
            "approval_required": True,
            "exit_reason": "approval_required",
            "state": task.agent_state_json,
            "pending_questions": [],
        }
        original_turn_response = turn.response_json.copy()
        approval = agent_approval_service.ensure_for_agent_handoff(
            db,
            task=task,
            turn=turn,
            state=task.agent_state_json,
        )
        db.commit()

        decided = agent_approval_service.decide_approval(
            db,
            task_id=task.id,
            approval_id=approval.id,
            decision=decision,
            conclusion="人工复核结论",
            client_decision_id=f"resolution-{approval_type}-001",
            decided_by_type="session",
            decided_by_id="owner",
        )
        db.commit()
        db.refresh(task)
        db.refresh(turn)
        decided_state_version = task.agent_state_version

        replayed = agent_approval_service.decide_approval(
            db,
            task_id=task.id,
            approval_id=approval.id,
            decision=decision,
            conclusion="人工复核结论",
            client_decision_id=f"resolution-{approval_type}-001",
            decided_by_type="session",
            decided_by_id="owner",
        )
        db.commit()
        db.refresh(task)

        assert decided.status == (
            "approved" if decision == "approve" else "rejected"
        )
        assert replayed.id == decided.id
        assert task.agent_state_version == decided_state_version
        assert task.status == expected_task_status
        assert task.agent_state_json["status"] == expected_status
        assert task.agent_state_json["exit_reason"] == expected_exit
        assert task.agent_state_json["approval_required"] is False
        assert task.agent_state_json["current_node"] == "approval_decision"
        assert task.agent_state_json["step_count"] == 0
        assert task.agent_state_json["retry_count"] == 0
        assert task.agent_state_json["hard_errors"] == []
        assert turn.status == original_turn_status
        assert turn.response_json == original_turn_response
        assert db.scalar(select(func.count()).select_from(TaskExecutionEvent)) == 1
        timeline_event = db.scalar(select(TaskExecutionEvent))
        assert timeline_event.event_code == "agent.approval.decided"
        assert task.agent_state_json["approval_resolution"]["decision"] == decision
        assert task.agent_state_json["approval_resolution"]["next_action"] in {
            "new_agent_turn",
            "revise_user_request",
        }
