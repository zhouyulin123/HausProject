from datetime import datetime, timedelta, timezone

import pytest

from app.agents import design_agent as design_agent_module
from app.agents.design_agent import (
    AgentToolRejected,
    DesignAgentWorkflow,
)
from app.schemas.design_agent import AgentTurnRequest
from app.schemas.scene_agent import SceneOperationBatch
from app.services import design_agent_service


def _facts(**overrides):
    values = {
        "space_type": "客厅",
        "budget_max": 20000,
        "room_width_m": 4.2,
        "room_depth_m": 5.1,
        "delivery_region": "CN-SH",
    }
    values.update(overrides)
    return values


@pytest.mark.unit
@pytest.mark.parametrize(
    ("message", "expected_codes"),
    [
        ("请拆除客厅承重墙扩大空间", ["load_bearing_structure_change"]),
        ("承重墙能不能拆？", ["load_bearing_structure_change"]),
        ("普通隔墙可以开一个门洞吗？", ["wall_demolition_or_opening"]),
        (
            "保留承重墙，同时在普通隔墙开洞",
            ["wall_demolition_or_opening"],
        ),
        ("消防喷淋能移位到吊顶边缘吗？", ["fire_safety_system_change"]),
        ("把厨房燃气管改到另一侧", ["gas_system_change"]),
        ("插座和配电箱都要移位", ["electrical_system_change"]),
        ("卫生间给排水管需要改造", ["plumbing_system_change"]),
        (
            "请做全屋水电改造",
            ["electrical_system_change", "plumbing_system_change"],
        ),
    ],
)
def test_high_risk_construction_classifier_returns_stable_reason_codes(
    message,
    expected_codes,
):
    assert (
        design_agent_module.classify_high_risk_construction_intent(message)
        == expected_codes
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "message",
    [
        "不拆墙、不动水电，只换家具",
        "不要移动燃气管，只调整餐桌位置",
        "不改消防设施，帮我选一组沙发",
        "墙面只刷漆，不开洞",
        "把承重墙旁边的沙发移动到窗边",
        "移动承重墙旁边的沙发到窗边",
    ],
)
def test_high_risk_construction_classifier_respects_negation_scope(message):
    assert design_agent_module.classify_high_risk_construction_intent(message) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("把当前场景里的沙发向左移动 30 厘米", True),
        ("删除茶几，增加一把椅子", True),
        ("调整餐桌的摆放位置", True),
        ("不要移动沙发，只换整体设计风格", False),
        ("帮我选一套适合客厅的沙发", False),
        ("调整家具配色", False),
    ],
)
def test_scene_edit_classifier_requires_positive_action_and_movable_object(
    message,
    expected,
):
    assert design_agent_module.classify_scene_edit_intent(message) is expected


@pytest.mark.unit
@pytest.mark.parametrize("conjunction", ["但是", "但"])
def test_high_risk_construction_classifier_only_negates_its_own_clause(conjunction):
    assert design_agent_module.classify_high_risk_construction_intent(
        f"不要拆承重墙，{conjunction}消防喷淋能移位吗？"
    ) == ["fire_safety_system_change"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("intent", "message", "expected_code", "scene_context"),
    [
        ("design", "拆除承重墙后做方案", "load_bearing_structure_change", None),
        ("catalog_search", "燃气管移位后选橱柜", "gas_system_change", None),
        (
            "scene_edit",
            "在隔墙开门洞",
            "wall_demolition_or_opening",
            {"scene_id": 9, "base_version": 1},
        ),
        ("custom_furniture", "先改造水电再做衣柜", "electrical_system_change", None),
    ],
)
def test_agent_blocks_construction_risk_before_any_tool_call(
    intent,
    message,
    expected_code,
    scene_context,
):
    calls = []
    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: calls.append("catalog") or {},
        execute_design=lambda _: calls.append("design") or {},
        execute_scene=lambda _: calls.append("scene") or {},
        execute_custom=lambda _: calls.append("custom") or {},
    )

    result = workflow.run(
        task_id=1,
        turn_id=99,
        active_mode=(
            "custom_furniture" if intent == "custom_furniture" else "catalog_design"
        ),
        intent=intent,
        message=message,
        facts=_facts(),
        scene_context=scene_context,
    )

    assert calls == []
    assert result["status"] == "needs_human"
    assert result["approval_required"] is True
    assert result["exit_reason"] == "safety_blocked"
    assert expected_code in result["hard_errors"]
    assert result["tool_events"] == [
        {
            "tool": "safety_intent_gate",
            "status": "rejected",
            "payload": {"reason_codes": result["hard_errors"]},
        }
    ]


@pytest.mark.unit
def test_construction_safety_codes_survive_step_budget_boundary():
    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: {},
        execute_design=lambda _: {},
        execute_scene=lambda _: {},
        max_steps=12,
    )

    result = workflow.run(
        task_id=1,
        turn_id=100,
        active_mode="catalog_design",
        intent="design",
        message="承重墙可以开洞吗？",
        facts=_facts(),
        initial_step_count=11,
    )

    assert result["status"] == "needs_human"
    assert result["exit_reason"] == "safety_blocked"
    assert result["hard_errors"] == ["load_bearing_structure_change"]
    assert result["approval_required"] is True


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
        "delivery_region",
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
def test_catalog_timeout_after_call_never_reports_success_or_retries():
    started_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    readings = iter([started_at, started_at + timedelta(seconds=31)])
    calls = []
    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: calls.append("catalog")
        or {"candidate_count": 1},
        execute_design=lambda _: (_ for _ in ()).throw(
            AssertionError("已超时时不应继续生成")
        ),
        execute_scene=lambda _: {},
        clock=lambda: next(readings),
    )

    result = workflow.run(
        task_id=1,
        turn_id=20,
        active_mode="catalog_design",
        intent="catalog_search",
        message="查找可配送商品",
        facts={"delivery_region": "CN-SH"},
        turn_execution_deadline_at=started_at + timedelta(seconds=30),
    )

    assert calls == ["catalog"]
    assert result["status"] == "needs_human"
    assert result["exit_reason"] == "timeout"
    assert result["retry_count"] == 0
    assert result["hard_errors"] == ["tool_timeout"]
    assert result["result"] is None
    assert result["tool_events"][-1]["status"] == "rejected"


@pytest.mark.unit
def test_scene_timeout_after_planning_never_writes_late_version(monkeypatch):
    started_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    readings = iter([started_at, started_at + timedelta(seconds=31)])
    scene = type("Scene", (), {"id": 9, "current_version": 1})()
    source = {
        "room": {
            "id": "living-room",
            "name": "客厅",
            "floorPolygon": [
                {"x": -2, "z": -2},
                {"x": 2, "z": -2},
                {"x": 2, "z": 2},
                {"x": -2, "z": 2},
            ],
            "ceilingHeight": 2.8,
            "wallThickness": 0.12,
        },
        "openings": [],
        "items": [],
    }
    writes = []
    monkeypatch.setattr(
        design_agent_service,
        "_load_task_scene",
        lambda *_, **__: scene,
    )
    monkeypatch.setattr(
        design_agent_service.scene_service,
        "get_current_version",
        lambda *_: type("Version", (), {"scene_json": source})(),
    )
    monkeypatch.setattr(
        design_agent_service.scene_tools,
        "build_scene_agent_context",
        lambda *_: {},
    )
    batch = SceneOperationBatch.model_validate(
        {
            "message": "已移动沙发",
            "operations": [
                {
                    "type": "move",
                    "instanceId": "sofa-main",
                    "position": {"x": -0.3, "z": 0},
                }
            ],
        }
    )
    monkeypatch.setattr(
        design_agent_service.llm_service,
        "plan_scene_operations",
        lambda **_: batch,
    )

    class FakeSceneWorkflow:
        def __init__(self, **_):
            pass

        def run(self, **kwargs):
            return {"proposed_scene": kwargs["source_scene"]}

    monkeypatch.setattr(design_agent_service, "SceneAgentWorkflow", FakeSceneWorkflow)
    monkeypatch.setattr(
        design_agent_service.scene_service,
        "update_scene_idempotent",
        lambda *_, **__: writes.append("write"),
    )
    db = type("Db", (), {"scalar": lambda *_: None})()
    tool = design_agent_service._scene_tool(
        db,
        type("Task", (), {"id": 1})(),
        AgentTurnRequest(
            client_turn_id="scene-timeout-001",
            message="移动沙发",
            scene_id=9,
            base_scene_version=1,
        ),
        2,
        turn_execution_deadline_at=started_at + timedelta(seconds=30),
        clock=lambda: next(readings),
    )

    with pytest.raises(AgentToolRejected) as caught:
        tool({"message": "移动沙发"})

    assert caught.value.codes == ["tool_timeout"]
    assert writes == []


@pytest.mark.unit
def test_custom_tool_timeout_discards_late_result_without_retry():
    started_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    readings = iter([started_at, started_at + timedelta(seconds=31)])
    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda _: {},
        execute_design=lambda _: {},
        execute_scene=lambda _: {},
        execute_custom=lambda _: {"status": "preview_ready"},
        clock=lambda: next(readings),
    )

    executed = workflow._execute(
        {
            "intent": "custom_furniture",
            "step_count": 1,
            "max_steps": 12,
            "turn_execution_deadline_at": "2026-09-04T08:00:30Z",
        }
    )
    verified = workflow._verify(
        {
            **executed,
            "intent": "custom_furniture",
            "step_count": executed["step_count"],
            "max_steps": 12,
            "max_retries": 2,
            "retry_count": 0,
        }
    )

    assert executed["result"] is None
    assert executed["hard_errors"] == ["tool_timeout"]
    assert verified["quality_outcome"] == "escalate"


@pytest.mark.unit
def test_catalog_search_waits_for_delivery_region_before_calling_catalog():
    calls = []
    workflow = DesignAgentWorkflow(
        retrieve_catalog=lambda state: calls.append(state) or {"candidate_count": 1},
        execute_design=lambda _: {},
        execute_scene=lambda _: {},
    )

    result = workflow.run(
        task_id=1,
        turn_id=5,
        active_mode="catalog_design",
        intent="catalog_search",
        message="先找可配送的沙发",
        facts={"space_type": "客厅"},
    )

    assert calls == []
    assert result["status"] == "waiting_user"
    assert [item["field"] for item in result["pending_questions"]] == [
        "delivery_region"
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
