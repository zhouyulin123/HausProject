"""统一设计智能体：条件路由、有限重试与明确退出原因。"""

from __future__ import annotations

import operator
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated, Any, Callable, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from pydantic import TypeAdapter, ValidationError

from app.schemas.custom_furniture import CustomFurnitureSpec


AgentTool = Callable[[dict[str, Any]], dict[str, Any]]


class DesignAgentToolRegistry:
    """固定名称的最小权限工具注册表。"""

    _ALLOWED = {
        "catalog_search",
        "design_generation",
        "scene_edit",
        "custom_furniture_preview",
    }

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
    fact_evidence: dict[str, dict[str, Any]]
    scene_context: dict[str, Any]
    custom_furniture_spec: dict[str, Any]
    custom_spec_invalid: bool
    status: str
    current_node: str
    pending_questions: list[dict[str, str]]
    tool_events: Annotated[list[dict[str, Any]], operator.add]
    result: dict[str, Any] | None
    hard_errors: list[str]
    quality_outcome: str
    approval_required: bool
    rejection_message: str
    step_count: int
    retry_count: int
    max_steps: int
    max_retries: int
    budget_exhausted: bool
    turn_execution_deadline_at: str | None
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
    "delivery_region": {
        "field": "delivery_region",
        "prompt": "商品需要配送到哪个地区？请提供城市或地区编码。",
        "reason": "配送地区是库存、价格和可售范围的硬约束",
    },
    "scene_context": {
        "field": "scene_context",
        "prompt": "请先打开需要修改的 3D 场景。",
        "reason": "场景修改必须绑定场景及其当前版本",
    },
    "custom_furniture_spec.family": {
        "field": "custom_furniture_spec.family",
        "prompt": "需要定制柜体还是桌类家具？",
        "reason": "家具族决定尺寸、材料和结构参数契约",
    },
    "custom_furniture_spec.name": {
        "field": "custom_furniture_spec.name",
        "prompt": "请给这件定制家具一个名称。",
        "reason": "名称用于区分本任务中的定制草案",
    },
    "custom_furniture_spec.purpose": {
        "field": "custom_furniture_spec.purpose",
        "prompt": "请确认家具的具体用途。",
        "reason": "用途决定适用的结构约束和报价项目",
    },
    "custom_furniture_spec.material": {
        "field": "custom_furniture_spec.material",
        "prompt": "请从当前支持的材料档位中选择一种。",
        "reason": "材料必须匹配参数化外观与报价规则",
    },
    "custom_furniture_spec.dimensions": {
        "field": "custom_furniture_spec.dimensions",
        "prompt": "请提供宽、高、深三个毫米尺寸。",
        "reason": "完整毫米尺寸是几何生成和报价复算的必要输入",
    },
    "custom_furniture_spec.structure": {
        "field": "custom_furniture_spec.structure",
        "prompt": "请补充或修正该家具族要求的结构参数。",
        "reason": "结构参数必须通过对应家具族的确定性制造约束",
    },
}


_CUSTOM_SPEC_ADAPTER = TypeAdapter(CustomFurnitureSpec)
_CUSTOM_FIELD_ORDER = (
    "family",
    "name",
    "purpose",
    "material",
    "dimensions",
    "structure",
)


_CONSTRUCTION_CLAUSE_SPLIT = re.compile(
    r"[，,。；;！？!?\n]+|但是|不过|然而|然后|后再|"
    r"但(?=要|需|想|可以|能|把|将|拆|改|动|移|开|做|换|调整|消防|燃气|水电)|"
    r"同时(?=在|把|将|拆|改|动|移|开|做|换|调整)|"
    r"再(?=把|将|拆|改|动|移|开|做|换|调整)"
)
_NEGATION_AT_CLAUSE_START = re.compile(
    r"^(?:请|务必|一定)?(?:不要|不准|禁止|避免|无需|不用|不需要|不能|不可|别|勿|不)"
)
_NEGATION_BEFORE_ACTION = re.compile(
    r"(?:不要|不准|禁止|避免|无需|不用|不需要|不能|不可|别|勿|不)"
    r"(?:再|去|要)?[^，。；！？,;!?]{0,2}$"
)
_QUESTION_BEFORE_ACTION = re.compile(
    r"(?:能不能|可不可以|要不要|该不该|是否(?:可以|能够|能)?|能否)$"
)
_SAFE_MOVABLE_OBJECT = re.compile(
    r"沙发|家具|桌(?:子)?|椅(?:子)?|床(?:铺)?|柜(?:子|体)?|灯(?:具)?|窗帘|地毯|家电"
)
_SCENE_EDIT_ACTION = re.compile(
    r"移动|挪动|平移|旋转|转向|删除|移除|拿掉|添加|新增|增加|摆放|放到|放在|替换|换成|"
    r"调整(?=[^，。；！？,;!?]{0,10}(?:位置|摆放|方向|角度|布局))"
)
_LOCATION_THEN_SAFE_OBJECT = re.compile(
    rf"(?:旁边|旁|边上|附近|前面|后面|一侧|侧面|边)"
    rf"[^，。；！？,;!?]{{0,4}}(?:{_SAFE_MOVABLE_OBJECT.pattern})"
)
_LOAD_BEARING_OBJECT = re.compile(
    r"承重墙|承重结构|剪力墙|结构柱|承重柱|房梁|梁柱"
)
_GENERAL_MODIFICATION_ACTION = re.compile(
    r"拆除?|砸掉?|敲掉?|改造|改动|改到|改为|改成|调整|移动|移位|迁移|挪动|"
    r"新增|增加|加装|取消|封堵|关闭|切割?|开槽|布线|走线|"
    r"更换|换管|改管|接管|动(?:一?下)?"
)
_CONSTRUCTION_RISK_RULES: tuple[
    tuple[str, re.Pattern[str], re.Pattern[str]], ...
] = (
    (
        "load_bearing_structure_change",
        _LOAD_BEARING_OBJECT,
        re.compile(
            rf"{_GENERAL_MODIFICATION_ACTION.pattern}|"
            r"开(?:一?个|一?处|一道)?(?:门)?洞|开孔|打孔"
        ),
    ),
    (
        "wall_demolition_or_opening",
        re.compile(
            r"非承重墙(?:体)?|普通(?:隔)?墙(?:体)?|轻体墙(?:体)?|隔墙(?:体)?|"
            r"(?<!承重)(?<!剪力)墙(?:体)?"
        ),
        re.compile(
            r"拆除?|砸掉?|敲掉?|移除|切墙|切割|"
            r"开(?:一?个|一?处|一道)?(?:门)?洞|开孔|打孔"
        ),
    ),
    (
        "fire_safety_system_change",
        re.compile(r"消防(?:设施|系统|管线)?|喷淋|烟感|消防栓|防火门|火灾报警器"),
        _GENERAL_MODIFICATION_ACTION,
    ),
    (
        "gas_system_change",
        re.compile(r"燃气(?:管|表|设施|系统)?|煤气(?:管|表)?|天然气(?:管|表)?"),
        _GENERAL_MODIFICATION_ACTION,
    ),
    (
        "electrical_system_change",
        re.compile(
            r"水电|电路|电线|电缆|插座|开关|配电箱|电箱|强电|弱电|电源|电气|电表"
        ),
        _GENERAL_MODIFICATION_ACTION,
    ),
    (
        "plumbing_system_change",
        re.compile(r"水电|给排水|给水|排水|水路|水管|下水|地漏|马桶"),
        _GENERAL_MODIFICATION_ACTION,
    ),
)


def classify_scene_edit_intent(message: str) -> bool:
    """仅以明确的家具动作与可移动对象组合识别场景编辑。"""
    for raw_clause in _CONSTRUCTION_CLAUSE_SPLIT.split(message):
        clause = raw_clause.strip()
        if not clause or not _SAFE_MOVABLE_OBJECT.search(clause):
            continue
        actions = list(_SCENE_EDIT_ACTION.finditer(clause))
        for action in actions:
            prefix = clause[: action.start()]
            if _NEGATION_AT_CLAUSE_START.search(clause):
                continue
            if _NEGATION_BEFORE_ACTION.search(prefix):
                continue
            return True
    return False


_ALL_CONSTRUCTION_ACTIONS = re.compile(
    "|".join(
        f"(?:{action.pattern})"
        for _, _, action in _CONSTRUCTION_RISK_RULES
    )
)


def _construction_pair_matches(
    clause: str,
    object_pattern: re.Pattern[str],
    action_pattern: re.Pattern[str],
) -> bool:
    object_matches = list(object_pattern.finditer(clause))
    action_matches = list(action_pattern.finditer(clause))
    if not object_matches or not action_matches:
        return False

    first_action = _ALL_CONSTRUCTION_ACTIONS.search(clause)
    for action in action_matches:
        action_prefix = clause[: action.start()]
        asks_about_action = bool(_QUESTION_BEFORE_ACTION.search(action_prefix))
        action_negated = not asks_about_action and (
            bool(_NEGATION_BEFORE_ACTION.search(action_prefix))
            or (
                bool(_NEGATION_AT_CLAUSE_START.match(clause))
                and first_action is not None
                and action.start() == first_action.start()
            )
        )
        if action_negated:
            continue
        for risk_object in object_matches:
            if (
                action.end() <= risk_object.start()
                and _LOCATION_THEN_SAFE_OBJECT.search(clause[risk_object.end() :])
            ):
                continue
            gap_start = min(action.end(), risk_object.end())
            gap_end = max(action.start(), risk_object.start())
            gap = clause[gap_start:gap_end] if gap_end > gap_start else ""
            if len(gap) > 8 or _SAFE_MOVABLE_OBJECT.search(gap):
                continue
            return True
    return False


def classify_high_risk_construction_intent(message: str) -> list[str]:
    """按分句识别高风险施工意图，返回稳定且可审计的原因码。"""
    reason_codes: list[str] = []
    for raw_clause in _CONSTRUCTION_CLAUSE_SPLIT.split(message):
        clause = re.sub(r"\s+", "", raw_clause)
        if not clause:
            continue
        for code, object_pattern, action_pattern in _CONSTRUCTION_RISK_RULES:
            if _construction_pair_matches(clause, object_pattern, action_pattern):
                if code not in reason_codes:
                    reason_codes.append(code)
    return reason_codes


def _custom_spec_check(
    raw_spec: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]], bool]:
    """返回规范化规格、最少必要追问和是否存在已提交字段错误。"""
    if not raw_spec.get("family"):
        key = "custom_furniture_spec.family"
        return raw_spec, [deepcopy(_QUESTIONS[key])], False

    missing = [field for field in _CUSTOM_FIELD_ORDER[1:] if not raw_spec.get(field)]
    if missing:
        questions = [
            deepcopy(_QUESTIONS[f"custom_furniture_spec.{field}"])
            for field in missing
        ]
        return raw_spec, questions, False

    try:
        normalized = _CUSTOM_SPEC_ADAPTER.validate_python(raw_spec)
    except ValidationError as exc:
        invalid_fields: list[str] = []
        for error in exc.errors():
            location = [str(item) for item in error.get("loc", ())]
            field = next(
                (item for item in location if item in _CUSTOM_FIELD_ORDER),
                "structure",
            )
            if field not in invalid_fields:
                invalid_fields.append(field)
        questions = [
            deepcopy(_QUESTIONS[f"custom_furniture_spec.{field}"])
            for field in invalid_fields
        ]
        return raw_spec, questions, True
    return normalized.model_dump(mode="json"), [], False


def _next_step(state: DesignAgentState, node: str) -> dict[str, Any]:
    step_count = state.get("step_count", 0)
    if step_count >= state.get("max_steps", 12):
        return {
            "step_count": step_count,
            "current_node": node,
            "status": "needs_human",
            "exit_reason": "retry_exhausted",
            "quality_outcome": "escalate",
            "hard_errors": ["step_limit_exceeded"],
        }
    return {"step_count": step_count + 1, "current_node": node}


class DesignAgentWorkflow:
    """单编排器调用已批准工具，不允许节点自由发现或执行代码。"""

    def __init__(
        self,
        *,
        retrieve_catalog: AgentTool,
        execute_design: AgentTool,
        execute_scene: AgentTool,
        execute_custom: AgentTool | None = None,
        max_steps: int = 12,
        max_retries: int = 2,
        checkpointer: BaseCheckpointSaver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._retrieve_catalog = retrieve_catalog
        self._execute_design = execute_design
        self._execute_scene = execute_scene
        self._execute_custom = execute_custom
        self._max_steps = max_steps
        self._max_retries = max_retries
        self._checkpointer = checkpointer
        self._clock = clock or (lambda: datetime.now(timezone.utc))
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
        graph.add_node("request_approval", self._request_approval)
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
            self._route_after_retrieve,
            {
                "finalize": "finalize",
                "execute_tool": "execute_tool",
                "escalate": "escalate",
            },
        )
        graph.add_edge("execute_tool", "verify_result")
        graph.add_conditional_edges(
            "verify_result",
            self._route_after_verify,
            {
                "finalize": "finalize",
                "replan": "replan",
                "approval": "request_approval",
                "escalate": "escalate",
            },
        )
        graph.add_edge("replan", "execute_tool")
        graph.add_edge("request_clarification", END)
        graph.add_edge("finalize", END)
        graph.add_edge("request_approval", END)
        graph.add_edge("escalate", END)
        return graph.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _turn_timed_out(self, state: DesignAgentState) -> bool:
        raw_deadline = state.get("turn_execution_deadline_at")
        if not raw_deadline:
            return False
        deadline = datetime.fromisoformat(raw_deadline.replace("Z", "+00:00"))
        return self._as_utc(self._clock()) >= self._as_utc(deadline)

    @staticmethod
    def _timeout_result(
        update: dict[str, Any],
        *,
        tool_name: str,
    ) -> dict[str, Any]:
        message = "同步工具执行超过本轮截止时间"
        return {
            **update,
            "result": None,
            "hard_errors": ["tool_timeout"],
            "rejection_message": message,
            "tool_events": [
                {
                    "tool": tool_name,
                    "status": "rejected",
                    "payload": {"message": message, "codes": ["tool_timeout"]},
                }
            ],
        }

    def _validate_facts(self, state: DesignAgentState) -> dict[str, Any]:
        construction_risks = classify_high_risk_construction_intent(
            state.get("message", "")
        )
        if construction_risks:
            return {
                **_next_step(state, "safety_intent_gate"),
                "current_node": "safety_intent_gate",
                "status": "needs_human",
                "exit_reason": "safety_blocked",
                "quality_outcome": "escalate",
                "approval_required": True,
                "hard_errors": construction_risks,
                "pending_questions": [],
                "result": None,
                "tool_events": [
                    {
                        "tool": "safety_intent_gate",
                        "status": "rejected",
                        "payload": {"reason_codes": construction_risks},
                    }
                ],
            }
        if state.get("budget_exhausted"):
            return {
                "current_node": "validate_facts",
                "status": "needs_human",
                "exit_reason": state.get("exit_reason") or "retry_exhausted",
                "quality_outcome": "escalate",
            }
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
            if not facts.get("delivery_region"):
                missing.append("delivery_region")
        elif state["intent"] == "catalog_search":
            if not facts.get("delivery_region"):
                missing.append("delivery_region")
        elif state["intent"] == "scene_edit" and not state.get(
            "scene_context"
        ):
            missing.append("scene_context")
        elif state["intent"] == "custom_furniture":
            normalized, questions, invalid = _custom_spec_check(
                state.get("custom_furniture_spec", {})
            )
            update["custom_furniture_spec"] = normalized
            update["pending_questions"] = questions
            update["custom_spec_invalid"] = invalid
            return update
        update["pending_questions"] = [deepcopy(_QUESTIONS[key]) for key in missing]
        return update

    @staticmethod
    def _route_after_fact_check(state: DesignAgentState) -> str:
        if state.get("exit_reason") == "safety_blocked":
            return "escalate"
        if (
            state.get("budget_exhausted")
            or state.get("exit_reason") == "retry_exhausted"
        ):
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
            "exit_reason": (
                "invalid_facts"
                if state.get("custom_spec_invalid")
                else "missing_facts"
            ),
        }

    def _retrieve(self, state: DesignAgentState) -> dict[str, Any]:
        update = _next_step(state, "retrieve_catalog")
        if update.get("exit_reason"):
            return update
        if self._turn_timed_out(state):
            return self._timeout_result(update, tool_name="catalog_search")
        result = self._retrieve_catalog(state)
        if self._turn_timed_out(state):
            return self._timeout_result(update, tool_name="catalog_search")
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

    @staticmethod
    def _route_after_retrieve(state: DesignAgentState) -> str:
        if "tool_timeout" in state.get("hard_errors", []):
            return "escalate"
        return (
            "finalize"
            if state["intent"] == "catalog_search"
            else "execute_tool"
        )

    def _execute(self, state: DesignAgentState) -> dict[str, Any]:
        update = _next_step(state, "execute_tool")
        if update.get("exit_reason"):
            return update
        if state["intent"] == "scene_edit":
            tool_name = "scene_edit"
            callback = self._execute_scene
        elif state["intent"] == "custom_furniture":
            tool_name = "custom_furniture_preview"
            callback = self._execute_custom
        else:
            tool_name = "design_generation"
            callback = self._execute_design
        try:
            if callback is None:
                raise AgentToolRejected(
                    "定制家具预览工具尚未注册",
                    codes=["tool_not_available"],
                )
            if tool_name != "design_generation" and self._turn_timed_out(state):
                return self._timeout_result(update, tool_name=tool_name)
            result = callback(state)
            if tool_name != "design_generation" and self._turn_timed_out(state):
                return self._timeout_result(update, tool_name=tool_name)
            tool_status = (
                "queued"
                if tool_name == "design_generation"
                and result.get("generation_status") in {"queued", "running"}
                else "completed"
            )
            return {
                **update,
                "result": result,
                "hard_errors": [],
                "rejection_message": "",
                "tool_events": [
                    {
                        "tool": tool_name,
                        "status": tool_status,
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
            if result.get("generation_status") in {"queued", "running"}:
                return {
                    **update,
                    "hard_errors": [],
                    "quality_outcome": "queued",
                }
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
        elif state["intent"] == "custom_furniture":
            quote = result.get("quote_preview") if isinstance(result, dict) else None
            if result and result.get("status") == "needs_human":
                return {
                    **update,
                    "hard_errors": [],
                    "quality_outcome": "approval",
                    "approval_required": True,
                }
            if (
                not isinstance(result, dict)
                or result.get("status") != "preview_ready"
                or not isinstance(quote, dict)
                or quote.get("status") != "estimated"
            ):
                errors.append("invalid_custom_furniture_preview")

        errors = list(dict.fromkeys(errors))
        if not errors:
            outcome = "passed"
        elif "tool_timeout" in errors:
            outcome = "escalate"
        elif state["intent"] == "custom_furniture":
            outcome = "escalate"
        elif state.get("retry_count", 0) < state.get("max_retries", 2):
            outcome = "retry"
        else:
            outcome = "escalate"
        return {**update, "hard_errors": errors, "quality_outcome": outcome}

    @staticmethod
    def _route_after_verify(state: DesignAgentState) -> str:
        return {
            "passed": "finalize",
            "queued": "finalize",
            "retry": "replan",
            "approval": "approval",
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
        update = _next_step(state, "finalize")
        if update.get("exit_reason"):
            return update
        return {
            **update,
            "status": (
                "running"
                if state["intent"] == "design"
                and (state.get("result") or {}).get("generation_status")
                in {"queued", "running"}
                else "completed"
            ),
            "exit_reason": (
                "generation_queued"
                if state["intent"] == "design"
                and (state.get("result") or {}).get("generation_status")
                in {"queued", "running"}
                else "goal_completed"
            ),
            "pending_questions": [],
            "approval_required": False,
        }

    def _request_approval(self, state: DesignAgentState) -> dict[str, Any]:
        return {
            **_next_step(state, "request_approval"),
            "status": "needs_human",
            "exit_reason": "approval_required",
            "pending_questions": [],
            "approval_required": True,
        }

    def _escalate(self, state: DesignAgentState) -> dict[str, Any]:
        if state.get("exit_reason") == "safety_blocked":
            return {
                **_next_step(state, "escalate"),
                "status": "needs_human",
                "exit_reason": "safety_blocked",
                "approval_required": True,
                "hard_errors": list(state.get("hard_errors", [])),
            }
        if state.get("budget_exhausted"):
            return {
                "current_node": "escalate",
                "status": "needs_human",
                "exit_reason": state.get("exit_reason") or "retry_exhausted",
            }
        exit_reason = state.get("exit_reason")
        if not exit_reason:
            scene_safety_codes = {
                "item_collision",
                "item_outside_room",
                "item_exceeds_room",
                "door_clearance_blocked",
                "unknown_sku",
            }
            if "tool_timeout" in state.get("hard_errors", []):
                exit_reason = "timeout"
            elif scene_safety_codes & set(state.get("hard_errors", [])):
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
        fact_evidence: dict[str, dict[str, Any]] | None = None,
        scene_context: dict[str, Any] | None = None,
        custom_furniture_spec: dict[str, Any] | None = None,
        initial_step_count: int = 0,
        initial_retry_count: int = 0,
        initial_hard_errors: list[str] | None = None,
        budget_exhausted: bool = False,
        initial_exit_reason: str = "",
        turn_execution_deadline_at: datetime | None = None,
        resume: bool = False,
    ) -> DesignAgentState:
        config = {
            "recursion_limit": self._max_steps + 8,
            "configurable": {
                "thread_id": f"design-task:{task_id}",
                # 顶层 namespace 由绑定 turn 的持久化 saver 映射。
                "checkpoint_ns": "",
            },
        }
        if resume:
            if self._checkpointer is None:
                raise RuntimeError("恢复 LangGraph 执行必须配置持久化 checkpointer")
            state = self._graph.invoke(None, config=config, durability="sync")
            if state is None:
                raise RuntimeError("没有可恢复的 LangGraph checkpoint")
            return state
        effective_intent = (
            "scene_edit" if intent == "auto" and scene_context else intent
        )
        if effective_intent == "auto":
            effective_intent = "design"
        initial_state = {
            "task_id": task_id,
            "turn_id": turn_id,
            "active_mode": active_mode,
            "intent": effective_intent,
            "message": message,
            "facts": deepcopy(facts),
            "fact_evidence": deepcopy(fact_evidence or {}),
            "scene_context": deepcopy(scene_context or {}),
            "custom_furniture_spec": deepcopy(custom_furniture_spec or {}),
            "custom_spec_invalid": False,
            "status": "running",
            "current_node": "start",
            "pending_questions": [],
            "tool_events": [],
            "result": None,
            "hard_errors": list(initial_hard_errors or []),
            "quality_outcome": "",
            "approval_required": False,
            "rejection_message": "",
            "step_count": initial_step_count,
            "retry_count": initial_retry_count,
            "max_steps": self._max_steps,
            "max_retries": self._max_retries,
            "budget_exhausted": budget_exhausted,
            "turn_execution_deadline_at": (
                self._as_utc(turn_execution_deadline_at)
                .isoformat()
                .replace("+00:00", "Z")
                if turn_execution_deadline_at is not None
                else None
            ),
            "exit_reason": initial_exit_reason if budget_exhausted else "",
        }
        if self._checkpointer is None:
            return self._graph.invoke(initial_state, config=config)
        return self._graph.invoke(initial_state, config=config, durability="sync")
