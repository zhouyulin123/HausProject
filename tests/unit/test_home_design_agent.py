"""受控整屋建议只修改白名单目标，不产生未校验的完整替换。"""

from copy import deepcopy

import pytest

from app.schemas.home_design_agent import HomeDesignAgentPlan, HomeDesignAgentRequest
from app.schemas.home_design import HomeDesignDocument
from app.schemas.home_design_asset import AssetResponse
from app.services.home_design_agent_service import apply_plan
from tests.unit.test_home_design import document


def plan(operations):
    return HomeDesignAgentPlan.model_validate(
        {"outcome": "proposal", "message": "建议调整", "operations": operations}
    )


def frozen_asset(asset_id=7):
    return AssetResponse.model_validate(
        {
            "id": asset_id,
            "task_id": 1,
            "kind": "product",
            "source_id": 12,
            "source_version": 3,
            "name": "冻结单椅",
            "size": {"width": 0.6, "height": 0.8, "depth": 0.7},
            "material": {"name": "羊毛", "color": "#eeeeee"},
            "model_spec": {"不应进入模型上下文": True},
            "content_digest": "a" * 64,
            "source_summary": {"verification_status": "verified"},
        }
    )


def test_patch_keeps_unmodified_fields_and_stable_ids():
    original = document()
    result = apply_plan(
        HomeDesignDocument.model_validate(original),
        plan(
            [
                {
                    "type": "patch_object",
                    "id": "o1",
                    "changes": {"position": {"x": 2.5, "y": 0, "z": 1.5}},
                }
            ]
        ),
    )
    expected = deepcopy(original)
    expected["objects"][0]["position"]["x"] = 2.5
    assert result.model_dump() == expected


def test_rejects_unknown_target_or_repeated_mutation():
    for actions in [
        [{"type": "remove_object", "id": "missing"}],
        [{"type": "remove_object", "id": "o1"}] * 2,
    ]:
        with pytest.raises(ValueError):
            apply_plan(HomeDesignDocument.model_validate(document()), plan(actions))


@pytest.mark.parametrize(
    "changes", [{"price": 2}, {"space_version": 2}, {"id": "renamed"}, {}]
)
def test_patch_cannot_modify_identity_space_or_invent_price(changes):
    with pytest.raises(ValueError):
        plan([{"type": "patch_object", "id": "o1", "changes": changes}])


def test_clarify_cannot_smuggle_operations():
    with pytest.raises(ValueError):
        HomeDesignAgentPlan.model_validate(
            {
                "outcome": "clarify",
                "message": "什么颜色？",
                "operations": [{"type": "remove_object", "id": "o1"}],
            }
        )


def test_planner_uses_single_strict_json_call(monkeypatch):
    from app.services import llm_service

    calls = []

    def chat(system, user, **kwargs):
        calls.append((system, user, kwargs))
        return {"outcome": "clarify", "message": "请选择房间", "operations": []}

    monkeypatch.setattr(llm_service, "_chat_json", chat)
    result = llm_service.plan_home_design(
        instruction="调一下", context={"document": document()}
    )
    assert result.outcome == "clarify"
    assert len(calls) == 1
    assert "responseJsonSchema" in calls[0][1]
    assert "不得承诺" in calls[0][0]


def test_surface_patch_and_object_add_remove_keep_other_targets():
    original = document()
    original["surfaces"] = [
        {
            "id": "floor",
            "room_id": "r1",
            "kind": "floor",
            "material": {"name": "灰", "color": "#aaaaaa"},
        }
    ]
    new_item = deepcopy(original["objects"][0])
    new_item["id"] = "o2"
    result = apply_plan(
        HomeDesignDocument.model_validate(original),
        plan(
            [
                {
                    "type": "patch_surface",
                    "id": "floor",
                    "material": {"name": "白", "color": "#ffffff"},
                },
                {"type": "add_object", "object": new_item},
                {"type": "remove_object", "id": "o1"},
            ]
        ),
    )
    assert result.objects[0].id == "o2"
    assert result.surfaces[0].id == "floor"
    assert result.surfaces[0].material.color == "#ffffff"
    assert result.space_version == 1


def test_ai_cannot_bind_quote_rule_when_adding_surface():
    value = document()
    operation = {
        "type": "add_surface",
        "surface": {
            "id": "floor",
            "room_id": "r1",
            "kind": "floor",
            "material": {"name": "地砖", "color": "#eeeeee"},
            "quote_rule_id": 7,
        },
    }

    with pytest.raises(ValueError, match="计价规则"):
        apply_plan(
            HomeDesignDocument.model_validate(value),
            plan([operation]),
        )


@pytest.mark.parametrize(
    "change", ["no_candidate", "wrong_space", "clarify_candidate", "invalid_validation"]
)
def test_response_contract_cannot_claim_inconsistent_proposal(change):
    from app.schemas.home_design_agent import HomeDesignAgentResponse

    value = {
        "turn_id": 1,
        "outcome": "proposal",
        "message": "候选",
        "base_version": 1,
        "space_version": 1,
        "candidate_document": document(),
        "validation": {"valid": True, "issues": []},
    }
    if change == "no_candidate":
        value["candidate_document"] = None
    if change == "wrong_space":
        value["space_version"] = 2
    if change == "clarify_candidate":
        value["outcome"] = "clarify"
    if change == "invalid_validation":
        value["validation"]["valid"] = False
    with pytest.raises(ValueError):
        HomeDesignAgentResponse.model_validate(value)


@pytest.mark.parametrize(
    "preview",
    [
        {"region": None, "total_price": 100, "known_subtotal": 100},
        {"region": "CN-SH", "pending_count": 1, "total_price": 100},
        {"region": "CN-SH", "known_subtotal": 90, "total_price": 100},
        {
            "region": "CN-SH",
            "known_subtotal": 100,
            "total_price": 100,
            "budget_max": 50,
            "budget_status": "within",
        },
    ],
)
def test_budget_preview_rejects_inconsistent_server_evidence(preview):
    from app.schemas.home_design_agent import HomeAgentBudgetPreview

    with pytest.raises(ValueError):
        HomeAgentBudgetPreview.model_validate(preview)


def test_request_cross_domain_scope_is_strict_and_deduplicated():
    value = {
        "client_turn_id": "cross-domain",
        "base_version": 1,
        "space_version": 1,
        "message": "加一把椅子",
        "region": "CN-SH",
        "budget_max": 5000,
        "allowed_asset_ids": [7, 8],
    }
    assert HomeDesignAgentRequest.model_validate(value).allowed_asset_ids == [7, 8]
    for change in (
        {"region": "cn-sh"},
        {"budget_max": 0},
        {"budget_max": True},
        {"allowed_asset_ids": [7, 7]},
        {"allowed_asset_ids": list(range(1, 22))},
    ):
        with pytest.raises(ValueError):
            HomeDesignAgentRequest.model_validate({**value, **change})


def test_add_asset_object_is_constructed_from_frozen_snapshot():
    asset = frozen_asset()
    result = apply_plan(
        HomeDesignDocument.model_validate(document()),
        plan(
            [
                {
                    "type": "add_asset_object",
                    "id": "chair-2",
                    "asset_id": asset.id,
                    "room_id": "r1",
                    "position": {"x": 0.5, "y": 0, "z": 0.5},
                    "rotation": 30,
                }
            ]
        ),
        allowed_assets={asset.id: asset},
    )
    added = result.objects[-1]
    assert added.asset_id == asset.id
    assert added.name == asset.name
    assert added.size == asset.size and added.material == asset.material
    assert added.installation.kind == "floor"
    assert added.category == "furniture"


def test_add_asset_object_rejects_unallowed_asset():
    asset = frozen_asset()
    operation = {
        "type": "add_asset_object",
        "id": "chair-2",
        "asset_id": asset.id,
        "room_id": "r1",
        "position": {"x": 0.5, "y": 0, "z": 0.5},
        "rotation": 0,
    }
    with pytest.raises(ValueError):
        apply_plan(HomeDesignDocument.model_validate(document()), plan([operation]))
    operation["position"]["y"] = 0.1
    with pytest.raises(ValueError):
        apply_plan(
            HomeDesignDocument.model_validate(document()),
            plan([operation]),
            allowed_assets={asset.id: asset},
        )
