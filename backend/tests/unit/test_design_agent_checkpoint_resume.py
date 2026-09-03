from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.design_agent import DesignAgentWorkflow
from app.db.database import Base
from app.db.models import DesignAgentTurn, DesignTask
from app.services.langgraph_checkpoint_service import SqlAlchemyCheckpointSaver


@pytest.fixture
def resumable_workflow_context():
    artifacts_dir = Path(__file__).resolve().parents[2] / ".test_artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    database_path = artifacts_dir / "design-agent-resume-unit.db"
    database_path.unlink(missing_ok=True)
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="waiting_input", raw_user_input="修改场景")
        db.add(task)
        db.flush()
        turn = DesignAgentTurn(
            task_id=task.id,
            client_turn_id="resume-turn-001",
            active_mode="room_scan_3d",
            intent="scene_edit",
            status="running",
            request_json={"message": "移动沙发"},
        )
        db.add(turn)
        db.commit()
        task_id, turn_id = task.id, turn.id
    try:
        yield factory, task_id, turn_id
    finally:
        engine.dispose()
        database_path.unlink(missing_ok=True)


def _run_scene_workflow(workflow: DesignAgentWorkflow, *, resume: bool = False):
    return workflow.run(
        task_id=1,
        turn_id=1,
        active_mode="room_scan_3d",
        intent="scene_edit",
        message="移动沙发",
        facts={},
        scene_context={"scene_id": 1, "base_version": 1},
        resume=resume,
    )


def test_crash_before_tool_resumes_from_last_superstep(resumable_workflow_context):
    factory, task_id, turn_id = resumable_workflow_context
    saver = SqlAlchemyCheckpointSaver(factory, task_id=task_id, turn_id=turn_id)
    attempts = 0
    fail_first = True

    def scene_tool(_state):
        nonlocal attempts, fail_first
        if fail_first:
            fail_first = False
            raise SystemExit("crash-before-side-effect")
        attempts += 1
        return {"scene_ref": {"scene_id": 1, "version": 2}}

    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: {},
        execute_design=lambda _: {},
        execute_scene=scene_tool,
        checkpointer=saver,
    )
    with pytest.raises(SystemExit, match="crash-before-side-effect"):
        _run_scene_workflow(workflow)

    assert saver.has_checkpoint()
    state = _run_scene_workflow(workflow, resume=True)

    assert state["status"] == "completed"
    assert attempts == 1
    assert state["current_node"] == "finalize"


def test_crash_after_idempotent_tool_does_not_duplicate_effect(
    resumable_workflow_context,
):
    factory, task_id, turn_id = resumable_workflow_context
    saver = SqlAlchemyCheckpointSaver(factory, task_id=task_id, turn_id=turn_id)
    attempts = 0
    effects: dict[str, dict] = {}

    def scene_tool(_state):
        nonlocal attempts
        attempts += 1
        result = effects.setdefault(
            f"agent-turn:{turn_id}",
            {"scene_ref": {"scene_id": 1, "version": 2}},
        )
        if attempts == 1:
            raise SystemExit("crash-after-side-effect")
        return result

    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: {},
        execute_design=lambda _: {},
        execute_scene=scene_tool,
        checkpointer=saver,
    )
    with pytest.raises(SystemExit, match="crash-after-side-effect"):
        _run_scene_workflow(workflow)

    state = _run_scene_workflow(workflow, resume=True)

    assert state["status"] == "completed"
    assert attempts == 2
    assert list(effects) == [f"agent-turn:{turn_id}"]
    assert state["result"] == {"scene_ref": {"scene_id": 1, "version": 2}}
