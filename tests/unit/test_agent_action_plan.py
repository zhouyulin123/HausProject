import pytest
from pydantic import ValidationError

from app.schemas.agent_action_plan import AgentActionPlan
from app.schemas.design_agent import AgentTurnRequest
from app.services import llm_service
from app.services.design_agent_service import _intent_for


pytestmark = pytest.mark.unit


def test_scene_context_does_not_steal_custom_furniture_or_catalog_turns():
    custom_edit = AgentTurnRequest(
        client_turn_id="action-route-custom-001",
        message="靠背再包裹一些",
        active_mode="custom_furniture",
        scene_id=9,
        base_scene_version=3,
    )
    compound = custom_edit.model_copy(
        update={
            "client_turn_id": "action-route-compound-001",
            "message": "做一把包裹感椅子并放到客厅中间",
        }
    )
    catalog = custom_edit.model_copy(
        update={
            "client_turn_id": "action-route-catalog-001",
            "message": "帮我选一套适合客厅的沙发",
            "active_mode": "catalog_design",
        }
    )
    catalog_compound = custom_edit.model_copy(
        update={
            "client_turn_id": "action-route-catalog-compound-001",
            "message": "做一把包裹感椅子并放到客厅中间",
            "active_mode": "catalog_design",
        }
    )
    structured_custom = AgentTurnRequest.model_validate(
        {
            **custom_edit.model_dump(mode="json"),
            "client_turn_id": "action-route-structured-custom-001",
            "message": "生成后放进房间",
            "custom_furniture_spec": {"family": "table"},
        }
    )

    assert _intent_for(custom_edit) == "action_plan"
    assert _intent_for(compound) == "action_plan"
    assert _intent_for(catalog) == "design"
    assert _intent_for(catalog_compound) == "scene_edit"
    assert _intent_for(structured_custom) == "custom_furniture"


def test_action_plan_accepts_only_ordered_whitelisted_steps():
    plan = AgentActionPlan.model_validate(
        {
            "schemaVersion": "agent-action-plan/1.0",
            "outcome": "execute",
            "summary": "创建并放到房间中心",
            "steps": [
                {
                    "id": "shape",
                    "tool": "open_geometry.edit",
                    "instruction": "做一把包裹感椅子",
                },
                {
                    "id": "place",
                    "tool": "scene.place_open_geometry",
                    "dependsOn": ["shape"],
                    "placement": {"kind": "room_center"},
                },
            ],
        }
    )

    assert [step.tool for step in plan.steps] == [
        "open_geometry.edit",
        "scene.place_open_geometry",
    ]

    with pytest.raises(ValidationError):
        AgentActionPlan.model_validate(
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "越权调用",
                "steps": [{"id": "x", "tool": "shell.exec", "command": "rm"}],
            }
        )

    with pytest.raises(ValidationError):
        AgentActionPlan.model_validate(
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "逆向依赖",
                "steps": [
                    {
                        "id": "place",
                        "tool": "scene.place_open_geometry",
                        "dependsOn": ["shape"],
                        "placement": {"kind": "room_center"},
                    },
                    {
                        "id": "shape",
                        "tool": "open_geometry.edit",
                        "instruction": "创建椅子",
                    },
                ],
            }
        )


def test_clarification_and_unsupported_plans_cannot_smuggle_actions():
    clarification = AgentActionPlan.model_validate(
        {
            "schemaVersion": "agent-action-plan/1.0",
            "outcome": "clarify",
            "summary": "无法唯一确定目标",
            "steps": [],
            "question": {
                "field": "target_instance",
                "prompt": "要移动哪一把椅子？",
                "candidateIds": ["chair-a", "chair-b"],
            },
        }
    )
    assert clarification.question is not None

    with pytest.raises(ValidationError):
        AgentActionPlan.model_validate(
            {
                **clarification.model_dump(by_alias=True, mode="json"),
                "steps": [
                    {
                        "id": "move",
                        "tool": "scene.move_item",
                        "instanceId": "chair-a",
                        "placement": {"kind": "room_center"},
                    }
                ],
            }
        )


def test_action_planner_has_one_bounded_model_call_and_strict_output(monkeypatch):
    calls = []

    def chat(system, user, *, max_tokens, temperature):
        calls.append(
            {
                "system": system,
                "user": user,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        return {
            "schemaVersion": "agent-action-plan/1.0",
            "outcome": "execute",
            "summary": "移动刚创建的椅子",
            "steps": [
                {
                    "id": "move",
                    "tool": "scene.move_item",
                    "instanceId": "chair-a",
                    "placement": {
                        "kind": "near_opening",
                        "openingId": "window-east",
                    },
                }
            ],
        }

    monkeypatch.setattr(llm_service, "_chat_json", chat)
    plan = llm_service.plan_agent_actions(
        instruction="把刚做的椅子靠窗移动",
        context={"scene": {"id": 9, "version": 3}},
    )

    assert plan.steps[0].tool == "scene.move_item"
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 1200

    monkeypatch.setattr(
        llm_service,
        "_chat_json",
        lambda *_args, **_kwargs: {
            "schemaVersion": "agent-action-plan/1.0",
            "outcome": "execute",
            "summary": "越权",
            "steps": [{"id": "x", "tool": "shell.exec"}],
        },
    )
    with pytest.raises(llm_service.LLMUnavailable):
        llm_service.plan_agent_actions(
            instruction="执行脚本",
            context={"scene": {"id": 9, "version": 3}},
        )
