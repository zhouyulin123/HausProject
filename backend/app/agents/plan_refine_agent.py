"""Plan Refine Agent：模型在现有方案上精准修改，确定性层回填商品与报价。

与 Scene Agent 同构的三节点工作流：
    plan（LLM 修改）→ execute（商品/报价确定性回填）→ validate（质量门禁）

模型只做语义层面的修改（换风格/换家具/调配色/调预算），商品 SKU 与价格
永远由 catalog_service 确定性回填，AI 无法编造。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.llm_service import LLMUnavailable

Plan = dict[str, Any]
RefinePlan = Callable[[Plan, str, str], tuple[Plan, str]]
EnrichPlans = Callable[[list[Plan]], None]
ValidatePlan = Callable[[Plan], None]


class PlanRefineQualityError(ValueError):
    """修改后的方案没有通过确定性质量门禁。"""


class PlanRefineState(TypedDict):
    instruction: str
    current_plan: Plan
    catalog_context: str
    refined_plan: Plan | None
    message: str
    node_trace: list[dict[str, Any]]


def _validate_plan_structure(plan: Plan) -> None:
    """确定性质量门禁：商品与报价必须有效。"""
    furniture = plan.get("furnitureSuggestions")
    if not isinstance(furniture, list) or not furniture:
        raise PlanRefineQualityError("修改后的方案缺少有效商品")
    if any(not isinstance(item, dict) or not item.get("id") for item in furniture):
        raise PlanRefineQualityError("修改后的方案包含无效商品 SKU")

    quote = plan.get("shopQuote")
    if not isinstance(quote, dict):
        raise PlanRefineQualityError("修改后的方案缺少确定性报价")
    totals = (
        quote.get("furnitureTotal"),
        quote.get("customTotal"),
        quote.get("total"),
    )
    if any(not isinstance(value, int) or value < 0 for value in totals):
        raise PlanRefineQualityError("修改后的方案报价结构无效")
    if totals[0] + totals[1] != totals[2]:
        raise PlanRefineQualityError("修改后的方案报价合计不一致")


class PlanRefineWorkflow:
    """可注入、可测试的方案精修工作流。"""

    def __init__(
        self,
        *,
        refine_plan: RefinePlan,
        enrich_plans: EnrichPlans,
        validate_plan: ValidatePlan | None = None,
    ) -> None:
        self._refine_plan = refine_plan
        self._enrich_plans = enrich_plans
        self._validate_plan = validate_plan or _validate_plan_structure
        self._graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(PlanRefineState)
        workflow.add_node("plan_refine", self._plan)
        workflow.add_node("execute_enrich", self._execute)
        workflow.add_node("validate_quality", self._validate)
        workflow.add_edge(START, "plan_refine")
        workflow.add_edge("plan_refine", "execute_enrich")
        workflow.add_edge("execute_enrich", "validate_quality")
        workflow.add_edge("validate_quality", END)
        return workflow.compile()

    def _plan(self, state: PlanRefineState) -> dict[str, Any]:
        refined, message = self._refine_plan(
            state["current_plan"],
            state["instruction"],
            state["catalog_context"],
        )
        return {"refined_plan": refined, "message": message}

    def _execute(self, state: PlanRefineState) -> dict[str, Any]:
        refined = state["refined_plan"]
        if refined is None:
            raise RuntimeError("Plan Refine 缺少候选方案")
        plans = [deepcopy(refined)]
        self._enrich_plans(plans)
        return {"refined_plan": plans[0]}

    def _validate(self, state: PlanRefineState) -> dict[str, Any]:
        refined = state["refined_plan"]
        if refined is None:
            raise RuntimeError("Plan Refine 缺少候选方案")
        self._validate_plan(refined)
        return {"node_trace": []}

    def run(
        self,
        *,
        instruction: str,
        current_plan: Plan,
        catalog_context: str,
    ) -> PlanRefineState:
        return self._graph.invoke(
            {
                "instruction": instruction,
                "current_plan": deepcopy(current_plan),
                "catalog_context": catalog_context,
                "refined_plan": None,
                "message": "",
                "node_trace": [],
            }
        )
