"""业务写入与图检查点之间的事务隔离回归。"""

import pytest
from sqlalchemy.exc import IntegrityError, SAWarning

from app.db.models import DesignTask
from app.schemas.design_agent import AgentTurnRequest
from app.services import design_agent_service, scene_service
from tests.integration.test_design_agent_api import (
    agent_api_context,  # noqa: F401
    test_action_plan_moves_recent_open_geometry_near_known_window as run_move_case,
)


def test_scene_side_effect_defers_checkpoint_before_first_write(
    agent_api_context, monkeypatch  # noqa: F811
):
    savers = []
    create_saver = design_agent_service._checkpoint_saver
    update_scene = scene_service.update_scene_idempotent

    def capture_saver(*args, **kwargs):
        saver = create_saver(*args, **kwargs)
        savers.append(saver)
        return saver

    def guarded_update(*args, **kwargs):
        assert savers[-1]._defer_persistence, "业务写入前必须停止检查点独立事务"
        return update_scene(*args, **kwargs)

    monkeypatch.setattr(design_agent_service, "_checkpoint_saver", capture_saver)
    monkeypatch.setattr(scene_service, "update_scene_idempotent", guarded_update)
    run_move_case(agent_api_context, monkeypatch)


def test_failed_flush_preserves_original_error_for_failure_persistence(
    agent_api_context, monkeypatch  # noqa: F811
):
    _, factory, _, _, task_id = agent_api_context
    captured = []

    def failing_turn(db, *, task, **kwargs):
        db.add(DesignTask(id=task_id, status="waiting_input"))
        with pytest.warns(SAWarning, match="conflicts with persistent instance"):
            db.flush()

    def persist_failure(db, *, task_id, error, **kwargs):
        captured.append((task_id, error))
        db.rollback()
        return {"status": "failed"}

    monkeypatch.setattr(design_agent_service, "_run_turn", failing_turn)
    monkeypatch.setattr(design_agent_service, "_persist_failed_turn", persist_failure)
    with factory() as db:
        task = db.get(DesignTask, task_id)
        result = design_agent_service.run_turn(
            db,
            task=task,
            payload=AgentTurnRequest(
                client_turn_id="flush-error-regression", message="修改家具"
            ),
        )
    assert result == {"status": "failed"}
    assert captured[0][0] == task_id
    assert isinstance(captured[0][1], IntegrityError)
