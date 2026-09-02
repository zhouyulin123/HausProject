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


@pytest.mark.unit
def test_agent_custom_furniture_waits_for_only_missing_structure():
    calls = []
    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: (_ for _ in ()).throw(
            AssertionError("定制家具不应检索成品商品")
        ),
        execute_design=lambda _: (_ for _ in ()).throw(
            AssertionError("定制家具不应调用方案生成")
        ),
        execute_scene=lambda _: {},
        execute_custom=lambda state: calls.append(state) or {},
    )

    result = workflow.run(
        task_id=1,
        turn_id=5,
        active_mode="custom_furniture",
        intent="custom_furniture",
        message="做一个衣柜",
        facts={},
        custom_furniture_spec={
            "family": "cabinet",
            "name": "主卧衣柜",
            "purpose": "wardrobe",
            "material": "E0 颗粒板",
            "dimensions": {
                "width_mm": 1200,
                "height_mm": 2400,
                "depth_mm": 600,
            },
        },
    )

    assert calls == []
    assert result["status"] == "waiting_user"
    assert result["exit_reason"] == "missing_facts"
    assert [question["field"] for question in result["pending_questions"]] == [
        "custom_furniture_spec.structure"
    ]


@pytest.mark.unit
def test_agent_custom_furniture_quote_handoff_never_retries():
    attempts = []
    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: {},
        execute_design=lambda _: {},
        execute_scene=lambda _: {},
        execute_custom=lambda state: attempts.append(state["retry_count"])
        or {
            "status": "needs_human",
            "spec": state["custom_furniture_spec"],
            "model_spec": {"确定性建模规则": {"规则状态": "ready"}},
            "quote_preview": {
                "status": "needs_human",
                "reason_code": "quote_rule_missing",
            },
            "warnings": [],
        },
    )

    result = workflow.run(
        task_id=1,
        turn_id=6,
        active_mode="custom_furniture",
        intent="custom_furniture",
        message="生成餐桌预览",
        facts={},
        custom_furniture_spec={
            "family": "table",
            "name": "六人位餐桌",
            "purpose": "dining_table",
            "material": "实木（橡木）",
            "dimensions": {
                "width_mm": 1600,
                "height_mm": 750,
                "depth_mm": 800,
            },
            "structure": {
                "top_shape": "rectangle",
                "base_style": "four_leg",
                "support_count": 4,
                "seat_count": 6,
                "top_thickness_mm": 36,
                "edge_radius_mm": 12,
            },
        },
    )

    assert attempts == [0]
    assert result["status"] == "needs_human"
    assert result["approval_required"] is True
    assert result["exit_reason"] == "approval_required"
    assert result["retry_count"] == 0
