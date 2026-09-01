"""统一设计智能体：条件路由、有限重试与明确退出原因。"""

from __future__ import annotations

import operator
from copy import deepcopy
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph


AgentTool = Callable[[dict[str, Any]], dict[str, Any]]


class DesignAgentToolRegistry:
    """固定名称的最小权限工具注册表。"""

    _ALLOWED = {"catalog_search", "design_generation", "scene_edit"}

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, name: str, callback: AgentTool) -> None:
        if name not in self._ALLOWED:
            raise ValueError(f"未批准的 Agent 工具：{name}")
        self._tools[name] = callback

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise RuntimeError(f"Agent 工具未注册：{name}") from exc


class AgentToolRejected(ValueError):
    """受控工具拒绝执行，允许编排器在预算内重试或转人工。"""

    def __init__(self, message: str, *, codes: list[str]) -> None:
        super().__init__(message)
        self.codes = codes


class DesignAgentState(TypedDict, total=False):
    task_id: int
    turn_id: int
    active_mode: str
    intent: str
    message: str
    facts: dict[str, Any]
    scene_context: dict[str, Any]
    status: str
    current_node: str
    pending_questions: list[dict[str, str]]
    tool_events: Annotated[list[dict[str, Any]], operator.add]
    result: dict[str, Any] | None
    hard_errors: list[str]
    quality_outcome: str
    rejection_message: str
    step_count: int
    retry_count: int
    max_steps: int
    max_retries: int
    exit_reason: str


_QUESTIONS = {
    "space_type": {
        "field": "space_type",
        "prompt": "需要设计哪个空间？",
        "reason": "空间类型决定商品范围和布局规则",
    },
    "budget_max": {
        "field": "budget_max",
        "prompt": "这次设计的最高预算是多少？",
        "reason": "预算是商品筛选和报价门禁的硬约束",
    },
    "room_dimensions": {
        "field": "room_dimensions",
        "prompt": "请提供房间的宽度和深度，或先完成户型尺寸校准。",
        "reason": "真实尺寸是摆放与碰撞校验的基础",
    },
    "scene_context": {
        "field": "scene_context",
        "prompt": "请先打开需要修改的 3D 场景。",
        "reason": "场景修改必须绑定场景及其当前版本",
    },
}


def _next_step(state: DesignAgentState, node: str) -> dict[str, Any]:
    step_count = state.get("step_count", 0) + 1
    if step_count > state.get("max_steps", 12):
        return {
            "step_count": step_count,
            "current_node": node,
            "status": "needs_human",
            "exit_reason": "retry_exhausted",
            "quality_outcome": "escalate",
            "hard_errors": ["step_limit_exceeded"],
        }
    return {"step_count": step_count, "current_node": node}


class DesignAgentWorkflow:
    """单编排器调用已批准工具，不允许节点自由发现或执行代码。"""

    def __init__(
        self,
        *,
        retrieve_catalog: AgentTool,
        execute_design: AgentTool,
        execute_scene: AgentTool,
        max_steps: int = 12,
        max_retries: int = 2,
    ) -> None:
        self._retrieve_catalog = retrieve_catalog
        self._execute_design = execute_design
        self._execute_scene = execute_scene
        self._max_steps = max_steps
        self._max_retries = max_retries
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(DesignAgentState)
        graph.add_node("validate_facts", self._validate_facts)
        graph.add_node("request_clarification", self._request_clarification)
        graph.add_node("retrieve_catalog", self._retrieve)
        graph.add_node("execute_tool", self._execute)
        graph.add_node("verify_result", self._verify)
        graph.add_node("replan", self._replan)
        graph.add_node("finalize", self._finalize)
        graph.add_node("escalate", self._escalate)
        graph.add_edge(START, "validate_facts")
        graph.add_conditional_edges(
            "validate_facts",
            self._route_after_fact_check,
            {
                "clarify": "request_clarification",
                "catalog": "retrieve_catalog",
                "execute": "execute_tool",
                "escalate": "escalate",
            },
        )
        graph.add_conditional_edges(
            "retrieve_catalog",
            lambda state: (
                "finalize"
                if state["intent"] == "catalog_search"
                else "execute_tool"
            ),
            {"finalize": "finalize", "execute_tool": "execute_tool"},
        )
        graph.add_edge("execute_tool", "verify_result")
        graph.add_conditional_edges(
            "verify_result",
            self._route_after_verify,
            {
                "finalize": "finalize",
                "replan": "replan",
                "escalate": "escalate",
            },
        )
        graph.add_edge("replan", "execute_tool")
        graph.add_edge("request_clarification", END)
        graph.add_edge("finalize", END)
        graph.add_edge("escalate", END)
        return graph.compile()

    def _validate_facts(self, state: DesignAgentState) -> dict[str, Any]:
        update = _next_step(state, "validate_facts")
        if update.get("exit_reason"):
            return update

        missing: list[str] = []
        facts = state.get("facts", {})
        if state["intent"] == "design":
            if not facts.get("space_type"):
                missing.append("space_type")
            if not facts.get("budget_max"):
                missing.append("budget_max")
            if not (facts.get("room_width_m") and facts.get("room_depth_m")):
                missing.append("room_dimensions")
        elif state["intent"] == "scene_edit" and not state.get(
            "scene_context"
        ):
            missing.append("scene_context")
        update["pending_questions"] = [deepcopy(_QUESTIONS[key]) for key in missing]
        return update

    @staticmethod
    def _route_after_fact_check(state: DesignAgentState) -> str:
        if state.get("exit_reason") == "retry_exhausted":
            return "escalate"
        if state.get("pending_questions"):
            return "clarify"
        if state["intent"] in {"design", "catalog_search"}:
            return "catalog"
        return "execute"

    def _request_clarification(self, state: DesignAgentState) -> dict[str, Any]:
        return {
            **_next_step(state, "request_clarification"),
                "status": "waiting_user",
                "exit_reason": "missing_facts",
        }

    def _retrieve(self, state: DesignAgentState) -> dict[str, Any]:
        update = _next_step(state, "retrieve_catalog")
        if update.get("exit_reason"):
            return update
        result = self._retrieve_catalog(state)
        return {
            **update,
            "result": result,
            "tool_events": [
                {
                    "tool": "catalog_search",
                    "status": "completed",
                    "payload": {
                        key: result[key]
                        for key in (
                            "candidate_count",
                            "data_status_counts",
                            "contains_unverified_drafts",
                        )
                        if key in result
                    },
                }
            ],
        }

    def _execute(self, state: DesignAgentState) -> dict[str, Any]:
        update = _next_step(state, "execute_tool")
        if update.get("exit_reason"):
            return update
        tool_name = (
            "scene_edit" if state["intent"] == "scene_edit" else "design_generation"
        )
        callback = (
            self._execute_scene
            if state["intent"] == "scene_edit"
            else self._execute_design
        )
        try:
            result = callback(state)
            return {
                **update,
                "result": result,
                "hard_errors": [],
                "rejection_message": "",
                "tool_events": [
                    {
                        "tool": tool_name,
                        "status": "completed",
                        "payload": {
                            key: value
                            for key, value in result.items()
                            if not key.startswith("_")
                        },
                    }
                ],
            }
        except AgentToolRejected as exc:
            return {
                **update,
                "result": None,
                "hard_errors": list(dict.fromkeys(exc.codes)),
                "rejection_message": str(exc),
                "tool_events": [
                    {
                        "tool": tool_name,
                        "status": "rejected",
                        "payload": {"message": str(exc), "codes": exc.codes},
                    }
                ],
            }

    def _verify(self, state: DesignAgentState) -> dict[str, Any]:
        update = _next_step(state, "verify_result")
        if update.get("exit_reason"):
            return update
        errors = list(state.get("hard_errors", []))
        result = state.get("result")
        if result is None:
            errors = errors or ["tool_failed"]
        elif state["intent"] == "design":
            if not isinstance(result.get("plan_count"), int) or result["plan_count"] < 1:
                errors.append("empty_plan")
            quotes = result.get("quotes")
            if (
                not isinstance(quotes, list)
                or not quotes
                or any(not isinstance(value, int) or value < 0 for value in quotes)
            ):
                errors.append("invalid_quote")
            if result.get("invalid_skus"):
                errors.append("invalid_sku")
            if result.get("quote_consistent") is False:
                errors.append("quote_mismatch")
            budget_max = state.get("facts", {}).get("budget_max")
            if (
                isinstance(quotes, list)
                and quotes
                and isinstance(budget_max, int)
                and min(quotes) > budget_max
            ):
                errors.append("budget_exceeded")

        errors = list(dict.fromkeys(errors))
        if not errors:
            outcome = "passed"
        elif state.get("retry_count", 0) < state.get("max_retries", 2):
            outcome = "retry"
        else:
            outcome = "escalate"
        return {**update, "hard_errors": errors, "quality_outcome": outcome}

    @staticmethod
    def _route_after_verify(state: DesignAgentState) -> str:
        return {
            "passed": "finalize",
            "retry": "replan",
        }.get(state.get("quality_outcome", "escalate"), "escalate")

    def _replan(self, state: DesignAgentState) -> dict[str, Any]:
        update = _next_step(state, "replan")
        if update.get("exit_reason"):
            return update
        return {
            **update,
            "retry_count": state.get("retry_count", 0) + 1,
            "message": (
                f"{state['message']}\n上一次执行未通过质量门禁："
                f"{', '.join(state.get('hard_errors', []))}。"
                "请在不突破已确认约束的前提下重新规划。"
            ),
        }

    def _finalize(self, state: DesignAgentState) -> dict[str, Any]:
        return {
            **_next_step(state, "finalize"),
            "status": "completed",
            "exit_reason": "goal_completed",
            "pending_questions": [],
        }

    def _escalate(self, state: DesignAgentState) -> dict[str, Any]:
        exit_reason = state.get("exit_reason")
        if not exit_reason:
            scene_safety_codes = {
                "item_collision",
                "item_outside_room",
                "item_exceeds_room",
                "door_clearance_blocked",
                "unknown_sku",
            }
            if scene_safety_codes & set(state.get("hard_errors", [])):
                exit_reason = "safety_blocked"
            elif state.get("retry_count", 0) > 0:
                exit_reason = "retry_exhausted"
            else:
                exit_reason = "tool_failed"
        return {
            **_next_step(state, "escalate"),
            "status": "needs_human",
            "exit_reason": exit_reason,
        }

    def run(
        self,
        *,
        task_id: int,
        turn_id: int,
        active_mode: str,
        intent: str,
        message: str,
        facts: dict[str, Any],
        scene_context: dict[str, Any] | None = None,
    ) -> DesignAgentState:
        effective_intent = (
            "scene_edit" if intent == "auto" and scene_context else intent
        )
        if effective_intent == "auto":
            effective_intent = "design"
        return self._graph.invoke(
            {
                "task_id": task_id,
                "turn_id": turn_id,
                "active_mode": active_mode,
                "intent": effective_intent,
                "message": message,
                "facts": deepcopy(facts),
                "scene_context": deepcopy(scene_context or {}),
                "status": "running",
                "current_node": "start",
                "pending_questions": [],
                "tool_events": [],
                "result": None,
                "hard_errors": [],
                "quality_outcome": "",
                "rejection_message": "",
                "step_count": 0,
                "retry_count": 0,
                "max_steps": self._max_steps,
                "max_retries": self._max_retries,
                "exit_reason": "",
            },
            config={"recursion_limit": self._max_steps + 8},
        )
