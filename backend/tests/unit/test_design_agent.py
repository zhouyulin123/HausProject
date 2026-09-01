import pytest

from app.agents.design_agent import (
    AgentToolRejected,
    DesignAgentWorkflow,
)


def _facts(**overrides):
    values = {
        "space_type": "客厅",
        "budget_max": 20000,
        "room_width_m": 4.2,
        "room_depth_m": 5.1,
    }
    values.update(overrides)
    return values


@pytest.mark.unit
def test_agent_pauses_and_returns_minimal_missing_fact_questions():
    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: {"candidate_count": 0},
        execute_design=lambda _: (_ for _ in ()).throw(
            AssertionError("事实不完整时不应执行方案工具")
        ),
        execute_scene=lambda _: (_ for _ in ()).throw(
            AssertionError("事实不完整时不应执行场景工具")
        ),
    )

    result = workflow.run(
        task_id=1,
        turn_id=1,
        active_mode="catalog_design",
        intent="design",
        message="帮我设计客厅",
        facts={"space_type": "客厅"},
    )

    assert result["exit_reason"] == "missing_facts"
    assert result["status"] == "waiting_user"
    assert [item["field"] for item in result["pending_questions"]] == [
        "budget_max",
        "room_dimensions",
    ]
    assert result["step_count"] <= result["max_steps"]


@pytest.mark.unit
def test_agent_completes_design_through_registered_tools():
    calls = []

    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda state: calls.append("catalog")
        or {"candidate_count": 8},
        execute_design=lambda state: calls.append("design")
        or {
            "plan_count": 3,
            "revision_version": 2,
            "generator": "llm",
            "quotes": [18000, 19500, 19900],
        },
        execute_scene=lambda _: {},
    )

    result = workflow.run(
        task_id=1,
        turn_id=2,
        active_mode="catalog_design",
        intent="design",
        message="开始设计",
        facts=_facts(),
    )

    assert calls == ["catalog", "design"]
    assert result["status"] == "completed"
    assert result["exit_reason"] == "goal_completed"
    assert result["result"]["revision_version"] == 2
    assert [event["tool"] for event in result["tool_events"]] == [
        "catalog_search",
        "design_generation",
    ]


@pytest.mark.unit
def test_agent_retries_bounded_tool_rejection_then_escalates():
    attempts = []

    def reject_scene(state):
        attempts.append(state["retry_count"])
        raise AgentToolRejected(
            "场景存在硬冲突",
            codes=["item_collision"],
        )

    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: {},
        execute_design=lambda _: {},
        execute_scene=reject_scene,
        max_retries=2,
    )

    result = workflow.run(
        task_id=1,
        turn_id=3,
        active_mode="catalog_design",
        intent="scene_edit",
        message="把沙发放到门口",
        facts=_facts(),
        scene_context={"scene_id": 9, "base_version": 1},
    )

    assert len(attempts) == 3
    assert result["retry_count"] == 2
    assert result["status"] == "needs_human"
    assert result["exit_reason"] == "safety_blocked"
    assert result["hard_errors"] == ["item_collision"]
    assert result["step_count"] <= result["max_steps"]


@pytest.mark.unit
def test_agent_never_completes_invalid_quote_result():
    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: {"candidate_count": 2},
        execute_design=lambda _: {
            "plan_count": 1,
            "generator": "llm",
            "quotes": [-1],
        },
        execute_scene=lambda _: {},
        max_retries=0,
    )

    result = workflow.run(
        task_id=1,
        turn_id=4,
        active_mode="catalog_design",
        intent="design",
        message="开始设计",
        facts=_facts(),
    )

    assert result["status"] == "needs_human"
    assert result["exit_reason"] == "tool_failed"
    assert "invalid_quote" in result["hard_errors"]
