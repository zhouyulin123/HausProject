import pytest

from app.agents.plan_refine_agent import (
    PlanRefineQualityError,
    PlanRefineWorkflow,
)


def _workflow(refine_plan, enrich_plans):
    return PlanRefineWorkflow(
        refine_plan=refine_plan,
        enrich_plans=enrich_plans,
    )


@pytest.mark.unit
def test_refine_workflow_plan_execute_validate():
    def fake_refine(plan, instruction, catalog):
        refined = dict(plan)
        refined["style"] = "暖调"
        return refined, "已调整风格"

    def fake_enrich(plans):
        for p in plans:
            p["furnitureSuggestions"] = [{"id": "SKU-1", "name": "沙发"}]
            p["shopQuote"] = {
                "furnitureTotal": 100,
                "customTotal": 50,
                "total": 150,
            }

    result = _workflow(fake_refine, fake_enrich).run(
        instruction="换个暖色调",
        current_plan={"id": "plan-a", "name": "暖居"},
        catalog_context="",
    )
    assert result["refined_plan"]["style"] == "暖调"
    assert result["refined_plan"]["id"] == "plan-a"
    assert result["refined_plan"]["shopQuote"]["total"] == 150
    assert result["message"] == "已调整风格"


@pytest.mark.unit
def test_refine_workflow_rejects_missing_furniture():
    def fake_refine(plan, instruction, catalog):
        return dict(plan), ""

    def fake_enrich(plans):
        for p in plans:
            p["furnitureSuggestions"] = []
            p["shopQuote"] = {
                "furnitureTotal": 0,
                "customTotal": 0,
                "total": 0,
            }

    with pytest.raises(PlanRefineQualityError):
        _workflow(fake_refine, fake_enrich).run(
            instruction="x",
            current_plan={"id": "plan-a", "name": "n"},
            catalog_context="",
        )


@pytest.mark.unit
def test_refine_workflow_rejects_inconsistent_quote():
    def fake_refine(plan, instruction, catalog):
        return dict(plan), ""

    def fake_enrich(plans):
        for p in plans:
            p["furnitureSuggestions"] = [{"id": "SKU-1"}]
            p["shopQuote"] = {
                "furnitureTotal": 100,
                "customTotal": 50,
                "total": 999,
            }

    with pytest.raises(PlanRefineQualityError):
        _workflow(fake_refine, fake_enrich).run(
            instruction="x",
            current_plan={"id": "plan-a", "name": "n"},
            catalog_context="",
        )
