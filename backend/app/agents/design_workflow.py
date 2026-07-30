"""AI 家装方案生成的 LangGraph 编排层。

工作流只负责状态流转、降级和质量门禁；商品查询、模型调用与报价计算仍由
现有 service 提供，并通过依赖注入保持节点可测试。
"""

from __future__ import annotations

import operator
from copy import deepcopy
from time import perf_counter
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.llm_service import LLMUnavailable

Plan = dict[str, Any]
GeneratePlans = Callable[[dict[str, Any], str], list[Plan]]
BuildTemplatePlans = Callable[[dict[str, Any]], list[Plan]]
EnrichPlans = Callable[[list[Plan]], None]
OnStep = Callable[["WorkflowStep"], None]


class WorkflowQualityError(ValueError):
    """工作流产物没有通过确定性质量门禁。"""


class WorkflowStep(TypedDict, total=False):
    node: str
    status: str
    duration_ms: int
    source: str
    fallback_reason: str


class DesignAgentState(TypedDict):
    requirement: dict[str, Any]
    image_context: list[str]
    catalog_context: str
    requirement_for_llm: dict[str, Any]
    plans: list[Plan]
    generator: str
    node_trace: Annotated[list[WorkflowStep], operator.add]


def _completed_step(
    node: str,
    started_at: float,
    **details: str,
) -> WorkflowStep:
    return {
        "node": node,
        "status": "completed",
        "duration_ms": max(0, round((perf_counter() - started_at) * 1000)),
        **details,
    }


class DesignWorkflow:
    """可注入、可观察的方案生成工作流。"""

    def __init__(
        self,
        *,
        generate_plans: GeneratePlans,
        build_template_plans: BuildTemplatePlans,
        enrich_plans: EnrichPlans,
        on_step: OnStep | None = None,
    ) -> None:
        self._generate_plans = generate_plans
        self._build_template_plans = build_template_plans
        self._enrich_plans = enrich_plans
        self._on_step = on_step
        self._graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(DesignAgentState)
        workflow.add_node("prepare_context", self._prepare_context)
        workflow.add_node("generate_plans", self._generate)
        workflow.add_node("calculate_quote", self._calculate_quote)
        workflow.add_node("validate_quality", self._validate_quality)
        workflow.add_edge(START, "prepare_context")
        workflow.add_edge("prepare_context", "generate_plans")
        workflow.add_edge("generate_plans", "calculate_quote")
        workflow.add_edge("calculate_quote", "validate_quality")
        workflow.add_edge("validate_quality", END)
        return workflow.compile()

    def _publish(self, step: WorkflowStep) -> WorkflowStep:
        if self._on_step is not None:
            self._on_step(deepcopy(step))
        return step

    def _prepare_context(self, state: DesignAgentState) -> dict[str, Any]:
        started_at = perf_counter()
        requirement_for_llm = deepcopy(state["requirement"])
        if state["image_context"]:
            requirement_for_llm["image_analysis"] = deepcopy(
                state["image_context"]
            )
        return {
            "requirement_for_llm": requirement_for_llm,
            "node_trace": [
                self._publish(
                    _completed_step("prepare_context", started_at)
                )
            ],
        }

    def _generate(self, state: DesignAgentState) -> dict[str, Any]:
        started_at = perf_counter()
        try:
            plans = self._generate_plans(
                state["requirement_for_llm"],
                state["catalog_context"],
            )
            generator = "llm"
            step = self._publish(
                _completed_step(
                    "generate_plans",
                    started_at,
                    source=generator,
                )
            )
        except LLMUnavailable as exc:
            plans = self._build_template_plans(state["requirement"])
            generator = "template"
            step = self._publish(
                _completed_step(
                    "generate_plans",
                    started_at,
                    source=generator,
                    fallback_reason=str(exc),
                )
            )
        return {
            "plans": deepcopy(plans),
            "generator": generator,
            "node_trace": [step],
        }

    def _calculate_quote(self, state: DesignAgentState) -> dict[str, Any]:
        started_at = perf_counter()
        plans = deepcopy(state["plans"])
        self._enrich_plans(plans)
        return {
            "plans": plans,
            "node_trace": [
                self._publish(
                    _completed_step(
                        "calculate_quote",
                        started_at,
                        source="deterministic",
                    )
                )
            ],
        }

    def _validate_quality(self, state: DesignAgentState) -> dict[str, Any]:
        started_at = perf_counter()
        plans = state["plans"]
        if not plans:
            raise WorkflowQualityError("没有生成可用方案")

        for plan in plans:
            plan_name = str(plan.get("name") or plan.get("id") or "未知方案")
            furniture = plan.get("furnitureSuggestions")
            if not isinstance(furniture, list) or not furniture:
                raise WorkflowQualityError(f"{plan_name} 缺少有效商品")
            if any(not isinstance(item, dict) or not item.get("id") for item in furniture):
                raise WorkflowQualityError(f"{plan_name} 包含无效商品 SKU")

            quote = plan.get("shopQuote")
            if not isinstance(quote, dict):
                raise WorkflowQualityError(f"{plan_name} 缺少确定性报价")
            totals = (
                quote.get("furnitureTotal"),
                quote.get("customTotal"),
                quote.get("total"),
            )
            if any(not isinstance(value, int) or value < 0 for value in totals):
                raise WorkflowQualityError(f"{plan_name} 报价结构无效")
            if totals[0] + totals[1] != totals[2]:
                raise WorkflowQualityError(f"{plan_name} 报价合计不一致")

        return {
            "node_trace": [
                self._publish(
                    _completed_step(
                        "validate_quality",
                        started_at,
                        source="deterministic",
                    )
                )
            ]
        }

    def run(
        self,
        *,
        requirement: dict[str, Any],
        image_context: list[str],
        catalog_context: str,
    ) -> DesignAgentState:
        return self._graph.invoke(
            {
                "requirement": deepcopy(requirement),
                "image_context": deepcopy(image_context),
                "catalog_context": catalog_context,
                "requirement_for_llm": {},
                "plans": [],
                "generator": "",
                "node_trace": [],
            }
        )
