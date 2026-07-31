"""Scene Agent：模型只规划，确定性工具执行并通过空间安全门禁。"""

from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.schemas.scene_agent import SceneOperationBatch
from app.schemas.scenes import SceneDocument, SceneValidationReport


PlanOperations = Callable[..., SceneOperationBatch]
ExecuteOperations = Callable[[SceneDocument, list], SceneDocument]
ValidateScene = Callable[[SceneDocument], SceneValidationReport]

_BLOCKING_WARNING_CODES = {
    "item_outside_room",
    "item_exceeds_room",
    "item_collision",
    "door_clearance_blocked",
}


class SceneAgentSafetyError(ValueError):
    """模型建议会导致不可接受的空间问题，未写入场景。"""

    def __init__(self, report: SceneValidationReport):
        super().__init__("Scene Agent 操作未通过空间安全检查")
        self.report = report


class SceneAgentState(TypedDict):
    instruction: str
    context: dict[str, Any]
    source_scene: SceneDocument
    batch: SceneOperationBatch | None
    proposed_scene: SceneDocument | None
    validation: SceneValidationReport | None


class SceneAgentWorkflow:
    """可注入、可测试的三节点场景工作流。"""

    def __init__(
        self,
        *,
        plan_operations: PlanOperations,
        execute_operations: ExecuteOperations,
        validate_scene: ValidateScene,
    ) -> None:
        self._plan_operations = plan_operations
        self._execute_operations = execute_operations
        self._validate_scene = validate_scene
        self._graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(SceneAgentState)
        workflow.add_node("plan_operations", self._plan)
        workflow.add_node("execute_tools", self._execute)
        workflow.add_node("validate_space", self._validate)
        workflow.add_edge(START, "plan_operations")
        workflow.add_edge("plan_operations", "execute_tools")
        workflow.add_edge("execute_tools", "validate_space")
        workflow.add_edge("validate_space", END)
        return workflow.compile()

    def _plan(self, state: SceneAgentState) -> dict:
        return {
            "batch": self._plan_operations(
                instruction=state["instruction"],
                context=state["context"],
            )
        }

    def _execute(self, state: SceneAgentState) -> dict:
        batch = state["batch"]
        if batch is None:
            raise RuntimeError("Scene Agent 缺少操作计划")
        return {
            "proposed_scene": self._execute_operations(
                state["source_scene"],
                batch.operations,
            )
        }

    def _validate(self, state: SceneAgentState) -> dict:
        proposed = state["proposed_scene"]
        if proposed is None:
            raise RuntimeError("Scene Agent 缺少候选场景")
        report = self._validate_scene(proposed)
        blocking_warnings = {
            issue.code for issue in report.warnings
        } & _BLOCKING_WARNING_CODES
        if not report.valid or blocking_warnings:
            raise SceneAgentSafetyError(report)
        return {"validation": report}

    def run(
        self,
        *,
        instruction: str,
        context: dict[str, Any],
        source_scene: SceneDocument,
    ) -> SceneAgentState:
        return self._graph.invoke(
            {
                "instruction": instruction,
                "context": context,
                "source_scene": source_scene,
                "batch": None,
                "proposed_scene": None,
                "validation": None,
            }
        )
