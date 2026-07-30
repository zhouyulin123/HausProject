import pytest

from app.agents.design_workflow import (
    DesignWorkflow,
    WorkflowQualityError,
)
from app.services.llm_service import LLMUnavailable


def test_workflow_runs_real_generation_and_deterministic_quote_nodes():
    received: dict = {}

    def generate(requirement, catalog_context):
        received["requirement"] = requirement
        received["catalog_context"] = catalog_context
        return [
            {
                "id": "plan-a",
                "name": "暖居",
                "style": "原木风",
                "furnitureSuggestions": [{"sku": "SOFA-001"}],
            }
        ]

    def enrich(plans):
        plans[0]["furnitureSuggestions"] = [{"id": "SOFA-001"}]
        plans[0]["shopQuote"] = {
            "furnitureTotal": 5000,
            "customTotal": 3000,
            "total": 8000,
        }

    workflow = DesignWorkflow(
        generate_plans=generate,
        build_template_plans=lambda _: [],
        enrich_plans=enrich,
    )

    result = workflow.run(
        requirement={"area": 90},
        image_context=["客厅采光良好"],
        catalog_context="SOFA-001|原木沙发",
    )

    assert received["requirement"]["image_analysis"] == ["客厅采光良好"]
    assert received["catalog_context"] == "SOFA-001|原木沙发"
    assert result["generator"] == "llm"
    assert result["plans"][0]["shopQuote"]["total"] == 8000
    assert [step["node"] for step in result["node_trace"]] == [
        "prepare_context",
        "generate_plans",
        "calculate_quote",
        "validate_quality",
    ]
    assert all(step["status"] == "completed" for step in result["node_trace"])


def test_workflow_records_template_fallback_without_fake_llm_success():
    def unavailable(*_):
        raise LLMUnavailable("模型暂不可用")

    template_plan = {
        "id": "plan-a",
        "name": "模板方案",
        "style": "现代简约",
        "furnitureSuggestions": [],
    }

    def enrich(plans):
        plans[0]["furnitureSuggestions"] = [{"id": "CHAIR-001"}]
        plans[0]["shopQuote"] = {
            "furnitureTotal": 1000,
            "customTotal": 0,
            "total": 1000,
        }

    workflow = DesignWorkflow(
        generate_plans=unavailable,
        build_template_plans=lambda _: [template_plan],
        enrich_plans=enrich,
    )

    result = workflow.run(
        requirement={"area": 60},
        image_context=[],
        catalog_context="",
    )

    assert result["generator"] == "template"
    generation_step = result["node_trace"][1]
    assert generation_step["source"] == "template"
    assert generation_step["fallback_reason"] == "模型暂不可用"


def test_workflow_rejects_plan_without_server_quote():
    workflow = DesignWorkflow(
        generate_plans=lambda *_: [
            {
                "id": "plan-a",
                "name": "不完整方案",
                "style": "现代简约",
                "furnitureSuggestions": [{"id": "CHAIR-001"}],
            }
        ],
        build_template_plans=lambda _: [],
        enrich_plans=lambda _: None,
    )

    with pytest.raises(WorkflowQualityError, match="缺少确定性报价"):
        workflow.run(
            requirement={"area": 60},
            image_context=[],
            catalog_context="",
        )


def test_workflow_emits_each_completed_node_for_live_progress():
    emitted: list[dict] = []

    def enrich(plans):
        plans[0]["furnitureSuggestions"] = [{"id": "CHAIR-001"}]
        plans[0]["shopQuote"] = {
            "furnitureTotal": 1000,
            "customTotal": 0,
            "total": 1000,
        }

    workflow = DesignWorkflow(
        generate_plans=lambda *_: [
            {
                "id": "plan-a",
                "name": "实时进度方案",
                "style": "现代简约",
                "furnitureSuggestions": [{"sku": "CHAIR-001"}],
            }
        ],
        build_template_plans=lambda _: [],
        enrich_plans=enrich,
        on_step=emitted.append,
    )

    workflow.run(
        requirement={"area": 60},
        image_context=[],
        catalog_context="CHAIR-001|单椅",
    )

    assert [step["node"] for step in emitted] == [
        "prepare_context",
        "generate_plans",
        "calculate_quote",
        "validate_quality",
    ]
