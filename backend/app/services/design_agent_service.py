"""DesignTask 聚合根上的统一 Agent turn 服务。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
from math import hypot, isclose
from typing import Any, Callable

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.agents.design_agent import (
    AgentToolRejected,
    classify_scene_edit_intent,
    DesignAgentToolRegistry,
    DesignAgentWorkflow,
)
from app.agents.scene_agent import SceneAgentSafetyError, SceneAgentWorkflow
from app.core.config import settings
from app.core.request_context import current_request_id
from app.db.models import (
    CustomFurnitureDraftMutation,
    DesignAgentEvent,
    DesignAgentTurn,
    ChatLog,
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    DesignTask,
    GenerationRun,
    RoomFactConfirmation,
    UploadedImage,
)
from app.schemas.design_agent import AgentTurnRequest, CustomFurnitureDraftRequest
from app.schemas.design_agent import AgentFactsPatch
from app.schemas.agent_action_plan import (
    AgentActionPlan,
    ExplicitPlacement,
    MoveSceneItemAction,
    NearOpeningPlacement,
    OpenGeometryEditAction,
    PlaceOpenGeometryAction,
    RoomCenterPlacement,
)
from app.schemas.custom_furniture import CustomFurniturePreviewRequest
from app.schemas.room_model import RoomModel
from app.schemas.scene_agent import MoveSceneItem, SceneOperationBatch
from app.schemas.scenes import (
    OpenGeometrySceneItemRequest,
    PositiveVector3,
    SceneDocument,
    Vector2XZ,
)
from app.services import (
    agent_approval_service,
    agent_fact_extraction_service,
    aggregate_lock_service,
    catalog_service,
    custom_furniture_service,
    generation_constraints_service,
    generation_request_service,
    generation_run_service,
    llm_service,
    model_call_governance_service,
    open_geometry_service,
    plan_refine_service,
    scene_service,
    scene_tools,
    task_timeline_service,
)
from app.services.llm_service import LLMUnavailable
from app.services.langgraph_checkpoint_service import SqlAlchemyCheckpointSaver
from app.services.scene_geometry import point_in_polygon

logger = logging.getLogger(__name__)
ROOM_FACT_CONFIDENCE_THRESHOLD = 0.8
_AGENT_STATE_EXTENSION_KEYS = frozenset({"open_geometry_furniture"})


class AgentSceneNotFound(ValueError):
    """场景不存在或不属于当前 DesignTask。"""


class AgentSceneVersionConflict(ValueError):
    """场景基线版本已过期，禁止静默覆盖。"""


class AgentTurnInProgress(ValueError):
    """相同幂等键已由另一请求占用且尚未产生最终响应。"""


class AgentIdempotencyConflict(ValueError):
    """相同 client_turn_id 被用于语义不同的请求。"""


class AgentStateVersionConflict(ValueError):
    """执行期间任务 checkpoint 已被其他持久化流程推进。"""

    def __init__(
        self,
        message: str,
        *,
        state_version: int,
        custom_furniture_draft: dict[str, Any] | None = None,
        scene_ref: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.state_version = state_version
        self.custom_furniture_draft = deepcopy(custom_furniture_draft)
        self.scene_ref = deepcopy(scene_ref)


class AgentActionPlanFailed(ValueError):
    """统一动作计划失败；携带可公开的稳定门禁原因码。"""

    def __init__(self, codes: list[str]) -> None:
        self.codes = list(dict.fromkeys(codes)) or ["action_plan_failed"]
        super().__init__("统一动作计划未通过确定性门禁")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _intent_for(payload: AgentTurnRequest) -> str:
    if payload.plan_id is not None:
        return "plan_refine"
    if payload.active_mode == "custom_furniture":
        supplied_spec = (
            payload.custom_furniture_spec.model_dump(
                mode="json", exclude_none=True
            )
            if payload.custom_furniture_spec is not None
            else {}
        )
        if supplied_spec:
            return "custom_furniture"
        if payload.scene_id is not None and payload.base_scene_version is not None:
            return "action_plan"
        return "open_geometry"
    if (
        payload.active_mode in {"catalog_design", "room_reconstruction"}
        and classify_scene_edit_intent(payload.message)
    ):
        return "scene_edit"
    if payload.active_mode != "catalog_design":
        return payload.active_mode
    return "design"


def is_open_geometry_turn(payload: AgentTurnRequest) -> bool:
    """供 HTTP 前置治理复用与编排完全一致的意图判定。"""
    return _intent_for(payload) in {"open_geometry", "action_plan"}


def _normalize_requirement_facts(requirement: dict[str, Any]) -> dict[str, Any]:
    return generation_constraints_service.normalize_requirement_facts(requirement)


def confirmed_generation_facts(task: DesignTask) -> dict[str, Any]:
    """返回生成链可使用的已确认事实，不从未确认输入推断硬约束。"""
    facts = _normalize_requirement_facts(task.confirmed_requirement_json or {})
    if task.budget_max is not None:
        facts["budget_max"] = task.budget_max
    return facts


def missing_confirmed_generation_facts(task: DesignTask) -> list[str]:
    """返回旧生成入口缺失的已确认硬事实，语义与 Agent 事实门禁一致。"""
    constraints = generation_constraints_service.constraints_for_task(task)

    missing: list[str] = []
    if constraints.budget_max is None:
        missing.append("budget_max")
    if constraints.max_dimensions_mm() is None:
        missing.append("room_dimensions")
    return missing


def _parse_budget_range(value: Any) -> tuple[int | None, int | None]:
    return generation_constraints_service.parse_budget_range(value)


def _room_facts(
    db: Session,
    task_id: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    images = db.scalars(
        select(UploadedImage)
        .where(UploadedImage.task_id == task_id)
        .order_by(UploadedImage.id.desc())
    ).all()
    for image in images:
        raw = (image.analysis_json or {}).get("room_model")
        if not isinstance(raw, dict):
            continue
        try:
            model = RoomModel.model_validate(raw)
        except (ValueError, TypeError):
            continue
        room = model.rooms[0]
        facts: dict[str, Any] = {}
        evidence: dict[str, dict[str, Any]] = {}
        if model.space_type:
            needs_confirmation = (
                model.confidence < ROOM_FACT_CONFIDENCE_THRESHOLD
                or "spaceType" in model.requires_confirmation
            )
            evidence["space_type"] = {
                "source": "room_model",
                "confidence": model.confidence,
                "image_id": image.id,
                "accepted": not needs_confirmation,
                "confirmation_required": needs_confirmation,
            }
            if not needs_confirmation:
                facts["space_type"] = model.space_type

        confirmations = db.scalars(
            select(RoomFactConfirmation)
            .where(RoomFactConfirmation.image_id == image.id)
            .order_by(RoomFactConfirmation.id.desc())
        ).all()
        latest_by_path: dict[str, RoomFactConfirmation] = {}
        for item in confirmations:
            latest_by_path.setdefault(item.fact_path, item)

        def confirmed_dimension(field: str, value: float | None):
            path = f"rooms.{room.id}.{field}"
            confirmation = latest_by_path.get(path)
            if confirmation is None or value is None:
                return None
            confirmed = confirmation.confirmed_value_json
            if (
                isinstance(confirmed, (int, float))
                and not isinstance(confirmed, bool)
                and isclose(float(confirmed), float(value), rel_tol=0, abs_tol=1e-9)
            ):
                return confirmation
            return None

        width_confirmation = confirmed_dimension("width_m", room.width_m)
        depth_confirmation = confirmed_dimension("depth_m", room.depth_m)
        dimensions_confirmed = (
            model.scale.source == "user"
            and width_confirmation is not None
            and depth_confirmation is not None
        )
        for fact_name, value, confirmation in (
            ("room_width_m", room.width_m, width_confirmation),
            ("room_depth_m", room.depth_m, depth_confirmation),
        ):
            evidence[fact_name] = {
                "source": (
                    "user_confirmation" if dimensions_confirmed else "room_model"
                ),
                "confidence": 1.0 if dimensions_confirmed else model.scale.confidence,
                "image_id": image.id,
                "accepted": dimensions_confirmed,
                "confirmation_required": not dimensions_confirmed,
            }
            if dimensions_confirmed and confirmation is not None:
                evidence[fact_name]["confirmation_id"] = confirmation.id
                facts[fact_name] = value
        if dimensions_confirmed:
            height_confirmation = confirmed_dimension(
                "ceiling_height",
                room.ceiling_height,
            )
            if room.ceiling_height and height_confirmation is not None:
                facts["ceiling_height_m"] = room.ceiling_height
                evidence["ceiling_height_m"] = {
                    "source": "user_confirmation",
                    "confidence": 1.0,
                    "image_id": image.id,
                    "confirmation_id": height_confirmation.id,
                    "accepted": True,
                    "confirmation_required": False,
                }
        return facts, evidence
    return {}, {}


def _facts_for_turn(
    db: Session,
    task: DesignTask,
    payload: AgentTurnRequest,
    *,
    turn_id: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    checkpoint = task.agent_state_json or {}
    prior_facts = checkpoint.get("facts") or {}
    prior_evidence = checkpoint.get("fact_evidence") or {}
    facts, evidence = _room_facts(db, task.id)

    def apply_confirmed(values: dict[str, Any], source: str) -> None:
        for field_name, value in values.items():
            facts[field_name] = value
            preserved = prior_evidence.get(field_name)
            if (
                prior_facts.get(field_name) == value
                and isinstance(preserved, dict)
                and preserved.get("accepted") is True
            ):
                evidence[field_name] = deepcopy(preserved)
            else:
                evidence[field_name] = {
                    "source": source,
                    "confidence": 1.0,
                    "accepted": True,
                    "confirmation_required": False,
                }

    apply_confirmed(
        _normalize_requirement_facts(task.confirmed_requirement_json or {}),
        "confirmed_requirement",
    )
    task_values: dict[str, Any] = {}
    if task.space_type:
        task_values["space_type"] = task.space_type
    if task.style:
        task_values["style"] = task.style
    if task.budget_min:
        task_values["budget_min"] = task.budget_min
    if task.budget_max:
        task_values["budget_max"] = task.budget_max
    apply_confirmed(task_values, "task_confirmation")
    # 保留明确撤回的 tombstone，防止图像事实或旧字段别名恢复已否定值。
    for field_name, value in prior_facts.items():
        if field_name in AgentFactsPatch.model_fields and value is None:
            facts[field_name] = None
            evidence[field_name] = deepcopy(prior_evidence.get(field_name) or {})
    if payload.answers is not None:
        for field_name, value in payload.answers.model_dump(
            exclude_none=True
        ).items():
            facts[field_name] = value
            evidence[field_name] = {
                "source": "user_turn",
                "confidence": 1.0,
                "turn_id": turn_id,
                "accepted": True,
                "confirmation_required": False,
            }
    return facts, evidence


def _merge_nested_dict(
    base: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested_dict(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _preserve_agent_state_extensions(
    prior: dict[str, Any],
    checkpoint: dict[str, Any],
    *,
    extension: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """在重建核心 checkpoint 时保留已登记的扩展状态命名空间。"""
    preserved = deepcopy(checkpoint)
    for key in _AGENT_STATE_EXTENSION_KEYS:
        if extension is not None and key in extension:
            preserved[key] = deepcopy(extension[key])
        elif key in prior:
            preserved[key] = deepcopy(prior[key])
    return preserved


def _open_geometry_tool():
    def execute(state: dict[str, Any]) -> dict[str, Any]:
        extension = state.get("open_geometry_extension")
        if not isinstance(extension, dict):
            extension = {"current_version": 0, "current": None, "history": []}
        try:
            prepared = open_geometry_service.prepare_command(
                instruction=state.get("message", ""),
                current_state=extension,
            )
        except open_geometry_service.OpenGeometryError as exc:
            raise AgentToolRejected(str(exc), codes=[exc.code]) from exc
        return {
            **prepared.result,
            "_open_geometry_extension": prepared.extension,
        }

    return execute


def _scene_document_for_action(
    db: Session,
    *,
    task_id: int,
    scene_id: int,
) -> tuple[DesignScene, SceneDocument]:
    scene = _load_task_scene(db, task_id=task_id, scene_id=scene_id)
    if scene is None:
        raise AgentSceneNotFound("场景不存在或不属于当前任务")
    current = scene_service.get_current_version(db, scene)
    return scene, SceneDocument.model_validate(current.scene_json)


def _action_planner_context(
    *,
    task_id: int,
    scene: DesignScene,
    document: SceneDocument,
    selected_instance_id: str | None,
    open_geometry_state: dict[str, Any],
    active_mode: str,
) -> dict[str, Any]:
    open_response = open_geometry_service.state_response(task_id, open_geometry_state)
    current = open_response.current if open_response is not None else None
    points = document.room.floor_polygon
    center = {
        "x": sum(point.x for point in points) / len(points),
        "z": sum(point.z for point in points) / len(points),
    }
    open_items = [
        {
            "instanceId": item.instance_id,
            "name": item.category,
            "openGeometryVersion": (
                item.open_geometry_ref.open_geometry_version
                if item.open_geometry_ref is not None
                else None
            ),
            "position": {
                "x": item.transform.position.x,
                "z": item.transform.position.z,
            },
        }
        for item in document.items
        if item.source_type == "open_geometry_draft"
    ]
    return {
        "activeMode": active_mode,
        "scene": {
            "id": scene.id,
            "version": scene.current_version,
            "roomId": document.room.id,
            "roomName": document.room.name,
            "roomCenter": center,
            "openings": [
                {"id": opening.id, "type": opening.type}
                for opening in document.openings[:20]
            ],
        },
        "selectedInstanceId": selected_instance_id,
        "currentOpenGeometry": (
            {
                "version": current.version,
                "name": current.design.name,
                "modelId": (
                    current.model_spec.get("确定性建模规则", {}).get("模型ID")
                ),
                "partIds": [part.id for part in current.design.parts[:40]],
            }
            if current is not None
            else None
        ),
        "openGeometryItems": open_items[:20],
        "openGeometryItemsTruncated": len(open_items) > 20,
    }


def _placement_point(
    document: SceneDocument,
    placement: RoomCenterPlacement | NearOpeningPlacement | ExplicitPlacement,
    *,
    dimensions: Any = None,
) -> Vector2XZ:
    if isinstance(placement, ExplicitPlacement):
        return placement.position
    points = document.room.floor_polygon
    if isinstance(placement, RoomCenterPlacement):
        return Vector2XZ(
            x=sum(point.x for point in points) / len(points),
            z=sum(point.z for point in points) / len(points),
        )
    opening = next(
        (item for item in document.openings if item.id == placement.opening_id),
        None,
    )
    if opening is None:
        raise AgentToolRejected(
            "动作计划引用了不存在的门窗洞口",
            codes=["opening_not_found"],
        )
    start = points[opening.wall_index]
    end = points[(opening.wall_index + 1) % len(points)]
    wall_length = hypot(end.x - start.x, end.z - start.z)
    if wall_length <= 1e-9:
        raise AgentToolRejected(
            "目标门窗所在墙段无效",
            codes=["opening_wall_invalid"],
        )
    tangent_x = (end.x - start.x) / wall_length
    tangent_z = (end.z - start.z) / wall_length
    center_x = start.x + tangent_x * (opening.offset + opening.width / 2)
    center_z = start.z + tangent_z * (opening.offset + opening.width / 2)
    left_normal = (-tangent_z, tangent_x)
    polygon = [(point.x, point.z) for point in points]
    left_probe = (
        center_x + left_normal[0] * 1e-4,
        center_z + left_normal[1] * 1e-4,
    )
    inward = (
        left_normal
        if point_in_polygon(left_probe, polygon)
        else (-left_normal[0], -left_normal[1])
    )
    clearance = 0.35
    if dimensions is not None:
        clearance = max(float(dimensions.x), float(dimensions.z)) / 2 + 0.15
    return Vector2XZ(
        x=center_x + inward[0] * clearance,
        z=center_z + inward[1] * clearance,
    )


def _action_plan_tool(
    db: Session,
    task: DesignTask,
    payload: AgentTurnRequest,
    turn_id: int,
    *,
    turn_execution_deadline_at: datetime,
    clock: Callable[[], datetime] | None = None,
    on_model_attempt: Callable[[], None] | None = None,
):
    current_time = clock or _utc_now

    def ensure_active() -> None:
        if _as_utc(current_time()) >= _as_utc(turn_execution_deadline_at):
            raise AgentToolRejected(
                "统一动作规划超过本轮截止时间",
                codes=["tool_timeout"],
            )

    def execute(state: dict[str, Any]) -> dict[str, Any]:
        if payload.scene_id is None or payload.base_scene_version is None:
            raise AgentToolRejected(
                "统一动作规划缺少场景版本",
                codes=["scene_context_missing"],
            )
        ensure_active()
        scene, document = _scene_document_for_action(
            db,
            task_id=task.id,
            scene_id=payload.scene_id,
        )
        if scene.current_version != payload.base_scene_version:
            raise AgentSceneVersionConflict(
                f"场景已经更新到版本 {scene.current_version}"
            )
        extension = state.get("open_geometry_extension")
        if not isinstance(extension, dict):
            extension = {"current_version": 0, "current": None, "history": []}
        context = _action_planner_context(
            task_id=task.id,
            scene=scene,
            document=document,
            selected_instance_id=payload.selected_instance_id,
            open_geometry_state=extension,
            active_mode=payload.active_mode,
        )
        try:
            if on_model_attempt is not None:
                on_model_attempt()
            plan: AgentActionPlan = llm_service.plan_agent_actions(
                instruction=state["message"],
                context=context,
            )
        except LLMUnavailable as exc:
            raise AgentToolRejected(str(exc), codes=["model_unavailable"]) from exc

        if plan.outcome == "clarify":
            question = plan.question
            return {
                "status": "waiting_user",
                "code": "clarification_required",
                "message": question.prompt,
                "partialCompletion": False,
                "actions": [],
                "_pending_questions": [
                    {
                        "field": question.field,
                        "prompt": question.prompt,
                        "reason": "需要先唯一确定受控动作目标",
                    }
                ],
                "_open_geometry_extension": extension,
            }
        if plan.outcome == "unsupported":
            return {
                "status": "completed",
                "code": "unsupported_action",
                "message": plan.summary,
                "reasonCode": plan.reason_code,
                "partialCompletion": False,
                "actions": [],
                "_open_geometry_extension": extension,
            }

        staged_extension = deepcopy(extension)
        action_results: list[dict[str, Any]] = []
        scene_ref: dict[str, int] | None = None
        for step in plan.steps:
            ensure_active()
            if isinstance(step, OpenGeometryEditAction):
                try:
                    if on_model_attempt is not None:
                        on_model_attempt()
                    prepared = open_geometry_service.prepare_command(
                        instruction=step.instruction,
                        current_state=staged_extension,
                        max_attempts=1,
                    )
                except open_geometry_service.OpenGeometryError as exc:
                    raise AgentToolRejected(str(exc), codes=[exc.code]) from exc
                if prepared.result.get("code") == "unsupported_geometry":
                    return {
                        "status": "completed",
                        "code": "unsupported_action",
                        "message": prepared.result.get("message") or plan.summary,
                        "reasonCode": "unsupported_geometry",
                        "partialCompletion": False,
                        "actions": [
                            {
                                "id": step.id,
                                "tool": step.tool,
                                "status": "unsupported",
                            }
                        ],
                        "_open_geometry_extension": extension,
                    }
                staged_extension = prepared.extension
                action_results.append(
                    {
                        "id": step.id,
                        "tool": step.tool,
                        "status": "completed",
                        "result": prepared.result,
                    }
                )
                continue

            if isinstance(step, PlaceOpenGeometryAction):
                staged_state = open_geometry_service.state_response(
                    task.id,
                    staged_extension,
                )
                current = staged_state.current if staged_state is not None else None
                if current is None:
                    raise AgentToolRejected(
                        "当前没有可放入房间的开放几何版本",
                        codes=["open_geometry_missing"],
                    )
                rule = current.model_spec.get("确定性建模规则", {})
                raw_dimensions = rule.get("包围尺寸_mm", {})
                try:
                    dimensions = PositiveVector3(
                        x=float(raw_dimensions["宽"]) / 1000,
                        y=float(raw_dimensions["高"]) / 1000,
                        z=float(raw_dimensions["深"]) / 1000,
                    )
                except (KeyError, TypeError, ValueError, ValidationError) as exc:
                    raise AgentToolRejected(
                        "开放几何版本缺少有效包围尺寸",
                        codes=["open_geometry_dimensions_invalid"],
                    ) from exc
                position = _placement_point(
                    document,
                    step.placement,
                    dimensions=dimensions,
                )
                try:
                    version, _ = scene_service.add_staged_open_geometry_to_scene(
                        db,
                        task=task,
                        scene=scene,
                        payload=OpenGeometrySceneItemRequest(
                            base_version=scene.current_version,
                            client_mutation_id=f"agent-turn:{turn_id}:{step.id}",
                            open_geometry_version=current.version,
                            position=position,
                            rotation_y=0,
                        ),
                        current=current,
                    )
                except scene_service.SceneConflictError as exc:
                    raise AgentSceneVersionConflict(str(exc)) from exc
                except (
                    scene_service.OpenGeometrySceneBindingError,
                    scene_service.ScenePlacementError,
                    scene_service.SceneValidationError,
                ) as exc:
                    codes = [getattr(exc, "code", "scene_validation_failed")]
                    if isinstance(exc, scene_service.ScenePlacementError):
                        codes = [issue.code for issue in exc.issues]
                    raise AgentToolRejected(str(exc), codes=codes) from exc
                scene_ref = {"scene_id": scene.id, "version": version.version}
                action_results.append(
                    {
                        "id": step.id,
                        "tool": step.tool,
                        "status": "completed",
                        "sceneRef": scene_ref,
                    }
                )
                continue

            if isinstance(step, MoveSceneItemAction):
                target = next(
                    (
                        item
                        for item in document.items
                        if item.instance_id == step.instance_id
                    ),
                    None,
                )
                if target is None:
                    raise AgentToolRejected(
                        "动作计划引用了不存在的场景物件",
                        codes=["target_instance_not_found"],
                    )
                position = _placement_point(
                    document,
                    step.placement,
                    dimensions=target.dimensions,
                )
                try:
                    proposed = scene_tools.apply_scene_operations(
                        db,
                        document,
                        [
                            MoveSceneItem(
                                type="move",
                                instance_id=step.instance_id,
                                position=position,
                            )
                        ],
                    )
                    placement_issues = scene_service.validate_item_placement(
                        proposed,
                        step.instance_id,
                    )
                    if placement_issues:
                        raise scene_service.ScenePlacementError(placement_issues)
                    version, _ = scene_service.update_scene_idempotent(
                        db,
                        scene=scene,
                        base_version=scene.current_version,
                        document=proposed,
                        source="scene_agent",
                        client_mutation_id=f"agent-turn:{turn_id}:{step.id}",
                        mutation_metadata={
                            "task_id": task.id,
                            "turn_id": turn_id,
                            "action_plan_schema": plan.schema_version,
                        },
                    )
                except scene_service.SceneConflictError as exc:
                    raise AgentSceneVersionConflict(str(exc)) from exc
                except scene_service.ScenePlacementError as exc:
                    raise AgentToolRejected(
                        str(exc),
                        codes=[issue.code for issue in exc.issues],
                    ) from exc
                except (scene_tools.SceneToolError, scene_service.SceneValidationError) as exc:
                    raise AgentToolRejected(
                        str(exc),
                        codes=["scene_validation_failed"],
                    ) from exc
                scene_ref = {"scene_id": scene.id, "version": version.version}
                action_results.append(
                    {
                        "id": step.id,
                        "tool": step.tool,
                        "status": "completed",
                        "sceneRef": scene_ref,
                    }
                )

        ensure_active()
        return {
            "status": "completed",
            "code": "action_plan_completed",
            "message": plan.summary,
            "partialCompletion": False,
            "actions": action_results,
            "scene_ref": scene_ref,
            "_open_geometry_extension": staged_extension,
        }

    return execute


def _normalized_model_call_capture(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"attempt_count": 0, "usage": {}}
    attempt_count = value.get("attempt_count", 0)
    if (
        not isinstance(attempt_count, int)
        or isinstance(attempt_count, bool)
        or attempt_count < 0
    ):
        attempt_count = 0
    raw_usage = value.get("usage")
    usage: dict[str, int] = {}
    if isinstance(raw_usage, dict):
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            token_count = raw_usage.get(key)
            if (
                isinstance(token_count, int)
                and not isinstance(token_count, bool)
                and token_count >= 0
            ):
                usage[key] = token_count
    return {"attempt_count": attempt_count, "usage": usage}


def _runtime_model_call_capture(value: Any) -> dict[str, Any]:
    return _normalized_model_call_capture(
        {
            "attempt_count": getattr(value, "attempt_count", 0),
            "usage": deepcopy(getattr(value, "usage", {}) or {}),
        }
    )


def _merge_model_call_capture(
    persisted: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    left = _normalized_model_call_capture(persisted)
    right = _normalized_model_call_capture(runtime)
    usage = {
        key: left["usage"].get(key, 0) + right["usage"].get(key, 0)
        for key in {**left["usage"], **right["usage"]}
    }
    return {
        "attempt_count": left["attempt_count"] + right["attempt_count"],
        "usage": usage,
    }


def _effective_model_call_capture(
    state: dict[str, Any],
    runtime: Any,
) -> llm_service.ModelCallCapture:
    checkpointed = _normalized_model_call_capture(
        state.get("model_call_capture")
    )
    live = _runtime_model_call_capture(runtime)
    selected = (
        checkpointed
        if checkpointed["attempt_count"] >= live["attempt_count"]
        else live
    )
    return llm_service.ModelCallCapture(
        attempt_count=selected["attempt_count"],
        usage=deepcopy(selected["usage"]),
    )


def _open_geometry_payload(task_id: int, state: Any) -> dict[str, Any] | None:
    try:
        response = open_geometry_service.state_response(task_id, state)
    except (
        TypeError,
        ValueError,
        ValidationError,
        open_geometry_service.OpenGeometryError,
    ):
        return None
    return response.model_dump(mode="json") if response is not None else None


def _validated_open_geometry_extension(
    task_id: int,
    state: Any,
    *,
    result: dict[str, Any] | None,
    prior_state: Any,
) -> dict[str, Any]:
    response = open_geometry_service.state_response(task_id, state)
    if response is None:
        raise open_geometry_service.OpenGeometryError(
            "invalid_state",
            "开放几何工具没有返回可提交的状态",
        )
    prior_response = open_geometry_service.state_response(
        task_id,
        prior_state
        if isinstance(prior_state, dict)
        else {"current_version": 0, "current": None, "history": []},
    )
    if prior_response is None:
        raise open_geometry_service.OpenGeometryError(
            "invalid_state",
            "开放几何旧状态无效",
        )
    normalized = response.model_dump(mode="json", exclude={"task_id"})
    prior = prior_response.model_dump(mode="json", exclude={"task_id"})
    if not isinstance(result, dict):
        if normalized != prior:
            raise open_geometry_service.OpenGeometryError(
                "invalid_state",
                "开放几何失败结果不得修改设计状态",
            )
        return normalized

    code = result.get("code")
    if result.get("current_version") != response.current_version:
        raise open_geometry_service.OpenGeometryError(
            "invalid_state",
            "开放几何结果版本与设计状态不一致",
        )
    if code == "unsupported_geometry":
        if normalized != prior:
            raise open_geometry_service.OpenGeometryError(
                "invalid_state",
                "不支持的开放几何请求不得覆盖旧版本",
            )
    elif code == "completed":
        if (
            response.current_version != prior_response.current_version + 1
            or response.current is None
        ):
            raise open_geometry_service.OpenGeometryError(
                "invalid_state",
                "开放几何成功结果必须在旧状态上连续推进一版",
            )
    else:
        raise open_geometry_service.OpenGeometryError(
            "invalid_state",
            "开放几何工具返回了未知结果状态",
        )

    expected_part_count = (
        len(response.current.design.parts) if response.current is not None else 0
    )
    expected_model_id = None
    if response.current is not None:
        expected_model_id = (
            response.current.model_spec.get("确定性建模规则", {}).get("模型ID")
        )
    if result.get("part_count") != expected_part_count:
        raise open_geometry_service.OpenGeometryError(
            "invalid_state",
            "开放几何结果部件数与设计状态不一致",
        )
    if result.get("model_id") != expected_model_id:
        raise open_geometry_service.OpenGeometryError(
            "invalid_state",
            "开放几何结果模型 ID 与设计状态不一致",
        )
    return normalized


def _custom_spec_for_turn(
    task: DesignTask,
    payload: AgentTurnRequest,
) -> dict[str, Any]:
    checkpoint = task.agent_state_json or {}
    prior = checkpoint.get("custom_furniture_spec")
    current = deepcopy(prior) if isinstance(prior, dict) else {}
    if payload.custom_furniture_spec is None:
        return current
    patch = payload.custom_furniture_spec.model_dump(
        mode="json",
        exclude_none=True,
    )
    incoming_family = patch.get("family")
    if incoming_family and current.get("family") not in (None, incoming_family):
        current = {}
    return _merge_nested_dict(current, patch)


def _max_dimensions_from_facts(
    facts: dict[str, Any],
) -> dict[str, int] | None:
    return generation_constraints_service.constraints_from_facts(
        facts
    ).max_dimensions_mm()


def _catalog_tool(db: Session):
    def execute(state: dict[str, Any]) -> dict[str, Any]:
        facts = state.get("facts", {})
        region = facts.get("delivery_region")
        if not region:
            raise AgentToolRejected(
                "缺少配送地区，禁止检索商用商品",
                codes=["delivery_region_required"],
            )
        budget = facts.get("budget_max")
        max_unit_price = budget if isinstance(budget, int) and budget > 0 else None
        products = catalog_service.eligible_products(
            db,
            region=region,
            max_unit_price=max_unit_price,
            max_dimensions_mm=_max_dimensions_from_facts(facts),
        )
        space_type = facts.get("space_type")
        if space_type:
            products = [product for product in products if product.room == space_type]
        ranked_products = catalog_service.rank_products_by_preferences(
            products,
            preferred_styles=facts.get("preferred_styles") or facts.get("style"),
            preferred_materials=(
                facts.get("preferred_materials") or facts.get("material")
            ),
        )
        status_counts: dict[str, int] = {}
        for product in products:
            status = product.data_origin or "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "candidate_count": len(products),
            "data_status_counts": status_counts,
            "contains_unverified_drafts": bool(
                {"merchant_draft", "unknown"} & set(status_counts)
            ),
            "products": [
                {
                    "sku": product.sku,
                    "name": product.name,
                    "category": product.category,
                    "price": product.price,
                    "data_origin": product.data_origin,
                    "ranking_reasons": ranking_reasons,
                }
                for product, ranking_reasons in ranked_products[:20]
                if product.sku
            ],
        }

    return execute


def _design_tool(
    db: Session,
    task: DesignTask,
    *,
    next_state_version: int,
):
    def execute(state: dict[str, Any]) -> dict[str, Any]:
        if state["intent"] != "design":
            raise AgentToolRejected(
                "该工作模式的受控工具尚未接入",
                codes=["tool_not_available"],
            )
        requirement = deepcopy(task.confirmed_requirement_json or {})
        requirement.update(state.get("facts", {}))
        requirement["agent_instruction"] = state["message"]
        facts = state.get("facts", {})
        region = facts.get("delivery_region")
        if not region:
            raise AgentToolRejected(
                "缺少配送地区，禁止生成商用方案",
                codes=["delivery_region_required"],
            )
        catalog_result = state.get("result") or {}
        if not catalog_result.get("candidate_count"):
            raise AgentToolRejected(
                "当前约束下没有可用于生成方案的已验证商品",
                codes=["catalog_empty"],
            )
        request_digest = generation_request_service.build_request_digest(
            db,
            task,
            requirement=requirement,
            agent_state_version=next_state_version,
            active_mode=state["active_mode"],
        )
        operation_key = generation_request_service.build_agent_operation_key(
            task_id=task.id,
            request_digest=request_digest,
        )
        try:
            run = generation_run_service.create_run(
                db,
                task=task,
                idempotency_key=operation_key,
                max_attempts=settings.generation_worker_max_attempts,
                request_id=current_request_id(),
                request_digest=request_digest,
                commit=False,
            )
        except generation_run_service.GenerationIdempotencyConflict as exc:
            raise AgentToolRejected(
                "生成操作幂等输入发生冲突，已停止自动执行",
                codes=["generation_idempotency_conflict"],
            ) from exc
        return {
            "run_id": run.id,
            "generation_status": run.status,
        }

    return execute


def _custom_furniture_tool(db: Session):
    def execute(state: dict[str, Any]) -> dict[str, Any]:
        try:
            request = CustomFurniturePreviewRequest.model_validate(
                {"spec": state.get("custom_furniture_spec")}
            )
        except ValueError as exc:
            raise AgentToolRejected(
                "定制家具规格未通过领域校验",
                codes=["invalid_custom_furniture_spec"],
            ) from exc
        region = (state.get("facts") or {}).get("delivery_region")
        preview = (
            custom_furniture_service.build_preview(db, request.spec, region=region)
            if region
            else custom_furniture_service.build_preview(db, request.spec)
        )
        return preview.model_dump(mode="json")

    return execute


def _plan_refine_tool(
    db: Session,
    task: DesignTask,
    payload: AgentTurnRequest,
    *,
    on_model_attempt: Callable[[], None],
):
    def execute(_state: dict[str, Any]) -> dict[str, Any]:
        if payload.plan_id is None:
            raise AgentToolRejected(
                "方案精修缺少方案标识",
                codes=["plan_context_missing"],
            )
        on_model_attempt()
        try:
            return plan_refine_service.refine_plan_version(
                db,
                task=task,
                plan_id=payload.plan_id,
                instruction=payload.message,
                commit=False,
            )
        except plan_refine_service.PlanRefineError as exc:
            raise AgentToolRejected(
                str(exc),
                codes=["plan_refine_failed"],
            ) from exc

    return execute


def _load_task_scene(
    db: Session,
    *,
    task_id: int,
    scene_id: int,
) -> DesignScene | None:
    return db.scalars(
        select(DesignScene)
        .join(
            DesignPlanVersion,
            DesignPlanVersion.id == DesignScene.plan_version_id,
        )
        .join(DesignRevision, DesignRevision.id == DesignPlanVersion.revision_id)
        .where(DesignScene.id == scene_id, DesignRevision.task_id == task_id)
    ).first()


def _scene_tool(
    db: Session,
    task: DesignTask,
    payload: AgentTurnRequest,
    turn_id: int,
    *,
    turn_execution_deadline_at: datetime,
    clock: Callable[[], datetime] | None = None,
    on_model_attempt: Callable[[], None] | None = None,
):
    current_time = clock or _utc_now

    def ensure_active() -> None:
        if _as_utc(current_time()) >= _as_utc(turn_execution_deadline_at):
            raise AgentToolRejected(
                "同步工具执行超过本轮截止时间",
                codes=["tool_timeout"],
            )

    def execute(state: dict[str, Any]) -> dict[str, Any]:
        ensure_active()
        if payload.scene_id is None or payload.base_scene_version is None:
            raise AgentToolRejected(
                "场景修改缺少场景版本",
                codes=["scene_context_missing"],
            )
        scene = _load_task_scene(db, task_id=task.id, scene_id=payload.scene_id)
        if scene is None:
            raise AgentSceneNotFound("场景不存在或不属于当前任务")
        mutation_id = f"agent-turn:{turn_id}"
        replayed = db.scalar(
            select(DesignSceneVersion).where(
                DesignSceneVersion.scene_id == scene.id,
                DesignSceneVersion.client_mutation_id == mutation_id,
            )
        )
        if replayed is not None:
            return {
                "operation_count": 0,
                "message": "已从幂等记录恢复场景修改。",
                "scene_ref": {"scene_id": scene.id, "version": replayed.version},
            }
        if scene.current_version != payload.base_scene_version:
            raise AgentSceneVersionConflict(
                f"场景已经更新到版本 {scene.current_version}"
            )
        current = scene_service.get_current_version(db, scene)
        document = SceneDocument.model_validate(current.scene_json)
        requirement = getattr(task, "confirmed_requirement_json", None)
        region_value = (
            requirement.get("delivery_region")
            if isinstance(requirement, dict)
            else None
        )
        delivery_region = (
            region_value.strip()
            if isinstance(region_value, str) and region_value.strip()
            else None
        )
        catalog_scope = (
            {"region": delivery_region} if delivery_region is not None else {}
        )
        context = scene_tools.build_scene_agent_context(
            db,
            document,
            **catalog_scope,
        )
        try:
            if on_model_attempt is not None:
                on_model_attempt()
            batch: SceneOperationBatch = llm_service.plan_scene_operations(
                instruction=state["message"],
                context=context,
            )
            workflow = SceneAgentWorkflow(
                plan_operations=lambda **_: batch,
                execute_operations=lambda source, operations: (
                    scene_tools.apply_scene_operations(
                        db,
                        source,
                        operations,
                        **catalog_scope,
                    )
                ),
                validate_scene=lambda candidate: scene_service.validate_scene(
                    db, candidate
                ),
            )
            workflow_result = workflow.run_planned(
                batch=batch,
                source_scene=document,
            )
        except LLMUnavailable as exc:
            raise AgentToolRejected(str(exc), codes=["model_unavailable"]) from exc
        except scene_tools.SceneCatalogEligibilityError as exc:
            raise AgentToolRejected(
                str(exc),
                codes=list(exc.reason_codes) or [exc.code],
            ) from exc
        except scene_tools.SceneToolError as exc:
            code = "invalid_sku" if "SKU" in str(exc) else "scene_tool_error"
            raise AgentToolRejected(str(exc), codes=[code]) from exc
        except SceneAgentSafetyError as exc:
            codes = [
                issue.code
                for issue in [*exc.report.errors, *exc.report.warnings]
            ]
            raise AgentToolRejected(str(exc), codes=codes) from exc

        refreshed = _load_task_scene(db, task_id=task.id, scene_id=scene.id)
        if refreshed is None:
            raise AgentSceneNotFound("场景不存在或不属于当前任务")
        if refreshed.current_version != payload.base_scene_version:
            raise AgentSceneVersionConflict("场景版本已变化，本轮建议未写入")
        proposed = workflow_result.get("proposed_scene")
        if proposed is None:
            raise AgentToolRejected("未生成候选场景", codes=["empty_scene"])
        ensure_active()
        try:
            version, _ = scene_service.update_scene_idempotent(
                db,
                scene=refreshed,
                base_version=payload.base_scene_version,
                document=proposed,
                source="scene_agent",
                client_mutation_id=mutation_id,
                mutation_metadata={
                    "task_id": task.id,
                    "turn_id": turn_id,
                    "instruction": state["message"],
                },
            )
        except scene_service.SceneConflictError as exc:
            raise AgentSceneVersionConflict(str(exc)) from exc
        except scene_service.SceneValidationError as exc:
            codes = [issue.code for issue in exc.report.errors]
            raise AgentToolRejected(str(exc), codes=codes) from exc
        return {
            "operation_count": len(batch.operations),
            "operations": [
                operation.model_dump(mode="json")
                for operation in batch.operations
            ],
            "message": batch.message,
            "scene_ref": {"scene_id": refreshed.id, "version": version.version},
        }

    return execute


def _public_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {key: value for key, value in result.items() if not key.startswith("_")}


def _reply(state: dict[str, Any]) -> str:
    if state["status"] == "waiting_user":
        return "为了继续设计，我还需要确认：" + "；".join(
            item["prompt"] for item in state["pending_questions"]
        )
    if state["status"] == "needs_human":
        if state.get("exit_reason") == "safety_blocked":
            return "该请求涉及高风险施工事项，已停止自动执行，需要由具备资质的专业人员审核。"
        if state.get("approval_required"):
            return "参数化预览已生成，但当前没有唯一可复算报价，需要人工确认价格。"
        return "本轮未通过确定性质量门禁，已停止自动执行并建议人工确认。"
    if state.get("exit_reason") == "generation_queued":
        return "方案生成任务已进入后台队列，可以继续留在当前工作台等待结果。"
    result = state.get("result") or {}
    if state["intent"] == "catalog_search":
        return f"已找到 {result.get('candidate_count', 0)} 件符合当前硬约束的商品。"
    if state["intent"] == "scene_edit":
        return str(result.get("message") or "已完成场景修改。")
    if state["intent"] == "plan_refine":
        return str(result.get("message") or "已按要求调整方案。")
    if state["intent"] == "custom_furniture":
        return "已生成通过参数校验且报价可复算的定制家具预览。"
    if state["intent"] == "open_geometry":
        return str(result.get("message") or "开放几何家具状态已更新。")
    if state["intent"] == "action_plan":
        return str(result.get("message") or "已完成受控家具与场景动作。")
    contains_drafts = any(
        event.get("payload", {}).get("contains_unverified_drafts")
        for event in state.get("tool_events", [])
        if event.get("tool") == "catalog_search"
    )
    suffix = "，其中商品资料仍包含待人工复核初稿" if contains_drafts else ""
    return (
        f"已生成 {result.get('plan_count', 0)} 套通过结构与报价校验的方案"
        f"{suffix}。"
    )


def _events_from_state(
    task_id: int,
    turn_id: int,
    state: dict[str, Any],
) -> list[DesignAgentEvent]:
    events: list[DesignAgentEvent] = []
    sequence = 1
    if state.get("pending_questions"):
        pending_fields = [q["field"] for q in state["pending_questions"]]
        fact_evidence = state.get("fact_evidence") or {}
        pending_evidence: dict[str, Any] = {}
        for field in pending_fields:
            if field == "room_dimensions":
                pending_evidence[field] = {
                    key: deepcopy(fact_evidence[key])
                    for key in ("room_width_m", "room_depth_m")
                    if key in fact_evidence
                }
            elif field in fact_evidence:
                pending_evidence[field] = deepcopy(fact_evidence[field])
        events.append(
            DesignAgentEvent(
                task_id=task_id,
                turn_id=turn_id,
                sequence=sequence,
                event_type="question_created",
                node="request_clarification",
                status="waiting_user",
                source="deterministic",
                summary="需要用户确认关键事实",
                details_json={
                    "fields": pending_fields,
                    "fact_evidence": pending_evidence,
                },
            )
        )
        sequence += 1
    for raw in state.get("tool_events", []):
        completed = raw["status"] == "completed"
        generation_queued = (
            raw["tool"] == "design_generation" and raw["status"] == "queued"
        )
        events.append(
            DesignAgentEvent(
                task_id=task_id,
                turn_id=turn_id,
                sequence=sequence,
                event_type=(
                    "generation_queued"
                    if generation_queued
                    else "tool_completed" if completed else "validation_failed"
                ),
                node=raw["tool"],
                status=raw["status"],
                source=(
                    "deterministic"
                    if raw["tool"] in {
                        "catalog_search",
                        "custom_furniture_preview",
                        "safety_intent_gate",
                    }
                    else "agent"
                ),
                summary=(
                    "方案生成任务已进入持久化队列"
                    if generation_queued
                    else f"工具 {raw['tool']} 执行完成"
                    if completed
                    else f"工具 {raw['tool']} 未通过质量门禁"
                ),
                details_json=raw.get("payload") or {},
            )
        )
        sequence += 1
    events.append(
        DesignAgentEvent(
            task_id=task_id,
            turn_id=turn_id,
            sequence=sequence,
            event_type=(
                "human_handoff"
                if state["status"] == "needs_human"
                else "state_changed"
            ),
            node=state["current_node"],
            status=state["status"],
            source="orchestrator",
            summary=f"本轮退出原因：{state['exit_reason']}",
            details_json={
                "hard_errors": state.get("hard_errors", []),
                "approval_required": state.get("approval_required", False),
            },
        )
    )
    return events


def _event_payload(event: DesignAgentEvent) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "turn_id": event.turn_id,
        "sequence": event.sequence,
        "type": event.event_type,
        "node": event.node,
        "status": event.status,
        "source": event.source,
        "summary": event.summary,
        "details": event.details_json or {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _record_agent_timeline_event(
    db: Session,
    *,
    event: DesignAgentEvent,
    state: str | None = None,
    model_attempted: bool = False,
    model_capture: llm_service.ModelCallCapture | None = None,
) -> None:
    normalized_state = state
    if normalized_state is None:
        normalized_state = {
            "waiting_user": "waiting_user",
            "failed": "failed",
            "conflict": "conflict",
        }.get(event.status, "completed")
    captured_attempts = (
        model_capture.attempt_count if model_capture is not None else 0
    )
    attempt_count = max(captured_attempts, 1 if model_attempted else 0)
    _, model_cost_cny = task_timeline_service.billing_for_model_call(
        attempted=attempt_count > 0,
        usage=model_capture.usage if model_capture is not None else None,
        input_price_per_mtok=settings.llm_input_price_per_mtok,
        output_price_per_mtok=settings.llm_output_price_per_mtok,
    )
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=event.task_id,
        source_type="agent",
        source_id=event.turn_id,
        state=normalized_state,
        attempt=attempt_count or None,
        model_cost_cny=model_cost_cny,
        occurred_at=event.created_at,
    )


_PUBLIC_EVENT_TYPES = {
    "state_changed",
    "question_created",
    "tool_started",
    "tool_completed",
    "validation_failed",
    "scene_committed",
    "generation_queued",
    "fallback_used",
    "human_handoff",
    "failed",
    "turn_recovered",
    "state_conflict",
}
_PUBLIC_EVENT_NODES = {
    "start",
    "validate_facts",
    "request_clarification",
    "retrieve_catalog",
    "catalog_search",
    "plan_design",
    "verify_plan",
    "verify_result",
    "replan_or_escalate",
    "execute_tool",
    "design_generation",
    "scene_edit",
    "plan_refine",
    "custom_furniture_preview",
    "open_geometry_edit",
    "action_plan",
    "safety_intent_gate",
    "checkpoint_commit",
    "turn_recovery",
    "failed",
}
_PUBLIC_EVENT_STATUSES = {
    "draft",
    "analyzing",
    "waiting_user",
    "ready",
    "running",
    "queued",
    "completed",
    "rejected",
    "conflict",
    "waiting_approval",
    "needs_human",
    "failed",
    "cancelled",
}
_PUBLIC_EVENT_SOURCES = {"deterministic", "agent", "orchestrator"}
_PUBLIC_NODE_LABELS = {
    "catalog_search": "商品检索",
    "design_generation": "方案生成",
    "scene_edit": "3D 场景调整",
    "plan_refine": "方案精修",
    "custom_furniture_preview": "定制家具预览",
    "open_geometry_edit": "开放几何编辑",
    "action_plan": "统一家具与场景动作",
    "safety_intent_gate": "安全意图检查",
}


def _public_event_payload(event: DesignAgentEvent) -> dict[str, Any]:
    event_type = (
        event.event_type
        if event.event_type in _PUBLIC_EVENT_TYPES
        else "state_changed"
    )
    node = event.node if event.node in _PUBLIC_EVENT_NODES else "execute_tool"
    status = event.status if event.status in _PUBLIC_EVENT_STATUSES else "running"
    source = event.source if event.source in _PUBLIC_EVENT_SOURCES else "orchestrator"
    if event_type == "question_created":
        summary = "需要确认关键事实"
    elif event_type == "generation_queued":
        summary = "方案生成已进入队列"
    elif event_type == "human_handoff":
        summary = "任务已转入人工处理"
    elif event_type == "turn_recovered":
        summary = "中断任务已转入人工恢复"
    elif event_type == "state_conflict":
        summary = "任务状态发生并发冲突"
    elif event_type == "failed":
        summary = "本轮执行已安全停止"
    elif event_type == "validation_failed":
        summary = f"{_PUBLIC_NODE_LABELS.get(node, '质量门禁')}未通过"
    elif event_type == "tool_started":
        summary = f"{_PUBLIC_NODE_LABELS.get(node, '受控工具')}正在执行"
    elif event_type == "tool_completed":
        summary = f"{_PUBLIC_NODE_LABELS.get(node, '受控工具')}已完成"
    elif event_type == "scene_committed":
        summary = "3D 场景版本已保存"
    elif event_type == "fallback_used":
        summary = "已使用受控降级路径"
    else:
        summary = "任务状态已更新"
    return {
        "event_id": event.id,
        "turn_id": event.turn_id,
        "sequence": event.sequence,
        "type": event_type,
        "node": node,
        "status": status,
        "source": source,
        "summary": summary,
        "details": {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def list_public_events(
    db: Session,
    *,
    task_id: int,
    limit: int,
    before_id: int | None = None,
) -> dict[str, Any]:
    filters = [DesignAgentEvent.task_id == task_id]
    if before_id is not None:
        filters.append(DesignAgentEvent.id < before_id)
    rows = db.scalars(
        select(DesignAgentEvent)
        .where(*filters)
        .order_by(DesignAgentEvent.id.desc())
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    selected = rows[:limit]
    selected.reverse()
    return {
        "events": [_public_event_payload(event) for event in selected],
        "has_more": has_more,
        "next_before_id": selected[0].id if has_more and selected else None,
    }


def _assert_same_turn_request(
    turn: DesignAgentTurn,
    payload: AgentTurnRequest,
) -> None:
    try:
        persisted_request = AgentTurnRequest.model_validate(
            turn.request_json
        ).model_dump(mode="json")
    except ValueError as exc:
        raise AgentIdempotencyConflict(
            "client_turn_id 对应的历史请求无法验证"
        ) from exc
    if persisted_request != payload.model_dump(mode="json"):
        raise AgentIdempotencyConflict(
            "client_turn_id 已用于不同的 Agent 请求"
        )


def _turn_lease_expired(turn: DesignAgentTurn, *, now: datetime) -> bool:
    if turn.created_at is None:
        return True
    deadline = _turn_execution_deadline(turn)
    return deadline <= _as_utc(now)


def replay_turn(
    db: Session,
    *,
    task_id: int,
    payload: AgentTurnRequest,
) -> dict[str, Any] | None:
    """在任何开放几何额度消耗前返回已持久化的幂等结果。"""
    turn = db.scalar(
        select(DesignAgentTurn).where(
            DesignAgentTurn.task_id == task_id,
            DesignAgentTurn.client_turn_id == payload.client_turn_id,
        )
    )
    if turn is None:
        return None
    _assert_same_turn_request(turn, payload)
    if turn.response_json is not None:
        return _existing_turn_result(turn, payload)
    if not _turn_lease_expired(turn, now=_utc_now()):
        raise AgentTurnInProgress("相同 client_turn_id 的请求仍在处理中")
    return None


def _turn_execution_deadline(turn: DesignAgentTurn) -> datetime:
    if turn.created_at is None:
        return _utc_now()
    return _as_utc(turn.created_at) + timedelta(
        seconds=settings.design_agent_turn_lease_seconds
    )


def _lock_task_for_turn(db: Session, task_id: int) -> DesignTask:
    task = aggregate_lock_service.lock_task(db, task_id)
    if task is None:
        raise ValueError("DesignTask 不存在")
    return task


def _existing_turn_result(
    turn: DesignAgentTurn,
    payload: AgentTurnRequest,
) -> dict[str, Any]:
    _assert_same_turn_request(turn, payload)
    if turn.status == "conflict" and isinstance(turn.response_json, dict):
        state_version = turn.response_json.get("state_version")
        raise AgentStateVersionConflict(
            str(turn.response_json.get("message") or "Agent 状态版本发生冲突"),
            state_version=state_version if isinstance(state_version, int) else 0,
        )
    if turn.response_json is not None:
        return deepcopy(turn.response_json)
    raise AgentTurnInProgress("相同 client_turn_id 的请求仍在处理中")


def _recovery_checkpoint(
    task: DesignTask,
    turn: DesignAgentTurn,
) -> dict[str, Any]:
    prior = task.agent_state_json if isinstance(task.agent_state_json, dict) else {}
    max_steps = prior.get("max_steps", 12)
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
        max_steps = 12
    max_retries = prior.get("max_retries", 2)
    if (
        not isinstance(max_retries, int)
        or isinstance(max_retries, bool)
        or max_retries < 0
    ):
        max_retries = 2
    step_count = prior.get("step_count", 0)
    if not isinstance(step_count, int) or isinstance(step_count, bool) or step_count < 0:
        step_count = 0
    retry_count = prior.get("retry_count", 0)
    if (
        not isinstance(retry_count, int)
        or isinstance(retry_count, bool)
        or retry_count < 0
    ):
        retry_count = 0
    return {
        **deepcopy(prior),
        "status": "needs_human",
        "active_mode": turn.active_mode,
        "active_room_id": prior.get("active_room_id"),
        "intent": turn.intent,
        "current_node": "turn_recovery",
        "facts": deepcopy(prior.get("facts") or {}),
        "fact_evidence": deepcopy(prior.get("fact_evidence") or {}),
        "pending_questions": [],
        "step_count": step_count,
        "retry_count": retry_count,
        "max_steps": max_steps,
        "max_retries": max_retries,
        "hard_errors": list(
            dict.fromkeys([*(prior.get("hard_errors") or []), "turn_lease_expired"])
        ),
        "custom_furniture_spec": deepcopy(prior.get("custom_furniture_spec")),
        "approval_required": True,
        "exit_reason": "turn_lease_expired",
        "scene_ref": deepcopy(prior.get("scene_ref")),
        "run_id": prior.get("run_id"),
        "result": deepcopy(prior.get("result")),
    }


def _recover_stale_turn(
    db: Session,
    *,
    task: DesignTask,
    turn: DesignAgentTurn,
) -> dict[str, Any]:
    checkpoint = _recovery_checkpoint(task, turn)
    task.agent_state_version = (task.agent_state_version or 0) + 1
    task.agent_state_json = checkpoint
    task.active_mode = turn.active_mode
    task.status = "needs_human"
    sequence = (
        db.scalar(
            select(func.max(DesignAgentEvent.sequence)).where(
                DesignAgentEvent.turn_id == turn.id
            )
        )
        or 0
    ) + 1
    event = DesignAgentEvent(
        task_id=task.id,
        turn_id=turn.id,
        sequence=sequence,
        event_type="turn_recovered",
        node="turn_recovery",
        status="needs_human",
        source="orchestrator",
        summary="Agent turn 租约已过期，已停止旧执行并转人工恢复",
        details_json={"code": "turn_lease_expired"},
    )
    db.add(event)
    db.flush()
    _record_agent_timeline_event(db, event=event, state="recovered")
    agent_approval_service.ensure_for_agent_handoff(
        db,
        task=task,
        turn=turn,
        state=checkpoint,
    )
    reply = "上一轮执行在完成前中断，系统已停止旧执行并转为人工恢复。"
    response = {
        "task_id": task.id,
        "turn_id": turn.id,
        "state_version": task.agent_state_version,
        "status": "needs_human",
        "active_mode": turn.active_mode,
        "active_room_id": checkpoint.get("active_room_id"),
        "intent": turn.intent,
        "reply": reply,
        "state": checkpoint,
        "pending_questions": [],
        "events": [_event_payload(event)],
        "approval_required": True,
        "scene_ref": checkpoint.get("scene_ref"),
        "run_id": checkpoint.get("run_id"),
        "exit_reason": "turn_lease_expired",
        "result": checkpoint.get("result"),
    }
    turn.status = "needs_human"
    turn.response_json = deepcopy(response)
    turn.completed_at = _utc_now()
    message = turn.request_json.get("message") if isinstance(turn.request_json, dict) else ""
    db.add(ChatLog(task_id=task.id, role="user", content=str(message or "")))
    db.add(ChatLog(task_id=task.id, role="ai", content=reply))
    return response


def _claim_turn(
    db: Session,
    *,
    task_id: int,
    payload: AgentTurnRequest,
) -> tuple[DesignTask, DesignAgentTurn, dict[str, Any] | None, bool]:
    task = _lock_task_for_turn(db, task_id)
    now = _utc_now()
    running_turns = db.scalars(
        select(DesignAgentTurn)
        .where(
            DesignAgentTurn.task_id == task.id,
            DesignAgentTurn.status == "running",
            DesignAgentTurn.response_json.is_(None),
            DesignAgentTurn.completed_at.is_(None),
        )
        .order_by(DesignAgentTurn.id)
    ).all()
    existing = next(
        (turn for turn in running_turns if turn.client_turn_id == payload.client_turn_id),
        None,
    )
    if existing is None:
        existing = db.scalar(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task.id,
                DesignAgentTurn.client_turn_id == payload.client_turn_id,
            )
        )
    if existing is not None:
        _assert_same_turn_request(existing, payload)
        if existing.response_json is not None:
            return task, existing, _existing_turn_result(existing, payload), False
        if not _turn_lease_expired(existing, now=now):
            raise AgentTurnInProgress("相同 client_turn_id 的请求仍在处理中")
        checkpoint_saver = _checkpoint_saver(
            db,
            task_id=task.id,
            turn_id=existing.id,
        )
        if checkpoint_saver.has_checkpoint():
            # 任务行锁保护租约重领；created_at 目前也是既有租约起点。
            existing.created_at = now
            db.commit()
            db.refresh(existing)
            db.refresh(task)
            return task, existing, None, True
        response = _recover_stale_turn(db, task=task, turn=existing)
        db.commit()
        return task, existing, response, False

    if (
        payload.base_state_version is not None
        and payload.base_state_version != int(task.agent_state_version or 0)
    ):
        raise AgentStateVersionConflict(
            "Agent 状态版本已变化，请刷新后重试",
            state_version=int(task.agent_state_version or 0),
        )

    for running in running_turns:
        if not _turn_lease_expired(running, now=now):
            raise AgentTurnInProgress("任务已有 Agent turn 正在处理中")
        _recover_stale_turn(db, task=task, turn=running)

    turn = DesignAgentTurn(
        task_id=task.id,
        client_turn_id=payload.client_turn_id,
        active_mode=payload.active_mode,
        intent=_intent_for(payload),
        status="running",
        request_json=payload.model_dump(mode="json"),
    )
    db.add(turn)
    try:
        db.commit()
        db.refresh(turn)
        db.refresh(task)
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task.id,
                DesignAgentTurn.client_turn_id == payload.client_turn_id,
            )
        )
        if existing is not None:
            return task, existing, _existing_turn_result(existing, payload), False
        raise AgentTurnInProgress("相同 client_turn_id 的请求仍在处理中") from exc
    return task, turn, None, False


def _checkpoint_saver(
    db: Session,
    *,
    task_id: int,
    turn_id: int,
) -> SqlAlchemyCheckpointSaver:
    factory = sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    return SqlAlchemyCheckpointSaver(factory, task_id=task_id, turn_id=turn_id)


def _record_state_conflict(
    db: Session,
    *,
    task_id: int,
    payload: AgentTurnRequest,
    model_capture: llm_service.ModelCallCapture | None = None,
) -> dict[str, Any] | AgentStateVersionConflict:
    db.rollback()
    task = _lock_task_for_turn(db, task_id)
    turn = db.scalar(
        select(DesignAgentTurn).where(
            DesignAgentTurn.task_id == task_id,
            DesignAgentTurn.client_turn_id == payload.client_turn_id,
        )
    )
    if turn is None:
        return AgentStateVersionConflict(
            "Agent 状态版本发生冲突",
            state_version=task.agent_state_version or 0,
        )
    if turn.response_json is not None:
        if turn.status == "conflict":
            return AgentStateVersionConflict(
                str(turn.response_json.get("message") or "Agent 状态版本发生冲突"),
                state_version=task.agent_state_version or 0,
            )
        return deepcopy(turn.response_json)
    message = "Agent 状态版本发生并发冲突，本轮副作用已回滚"
    conflict = {
        "code": "agent_state_conflict",
        "message": message,
        "state_version": task.agent_state_version or 0,
    }
    turn.status = "conflict"
    turn.response_json = conflict
    turn.completed_at = _utc_now()
    event = DesignAgentEvent(
        task_id=task.id,
        turn_id=turn.id,
        sequence=1,
        event_type="state_conflict",
        node="checkpoint_commit",
        status="conflict",
        source="orchestrator",
        summary=message,
        details_json={
            "code": "agent_state_conflict",
            "state_version": task.agent_state_version or 0,
        },
    )
    db.add(event)
    db.flush()
    _record_agent_timeline_event(
        db,
        event=event,
        state="conflict",
        model_capture=model_capture,
    )
    db.commit()
    return AgentStateVersionConflict(
        message,
        state_version=task.agent_state_version or 0,
    )


def _run_turn(
    db: Session,
    *,
    task: DesignTask,
    payload: AgentTurnRequest,
    model_capture: llm_service.ModelCallCapture | None = None,
) -> dict[str, Any]:
    task, turn, claimed_response, resume_turn = _claim_turn(
        db,
        task_id=task.id,
        payload=payload,
    )
    if claimed_response is not None:
        return claimed_response
    intent = _intent_for(payload)
    if payload.scene_id is not None:
        scene = _load_task_scene(
            db,
            task_id=task.id,
            scene_id=payload.scene_id,
        )
        if scene is None:
            raise AgentSceneNotFound("场景不存在或不属于当前任务")
        if scene.current_version != payload.base_scene_version:
            raise AgentSceneVersionConflict(
                f"场景已经更新到版本 {scene.current_version}"
            )
    prior_checkpoint = (
        task.agent_state_json if isinstance(task.agent_state_json, dict) else {}
    )
    opening_state_version = int(task.agent_state_version or 0)
    max_steps = prior_checkpoint.get("max_steps", 12)
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
        max_steps = 12
    max_retries = prior_checkpoint.get("max_retries", 2)
    if (
        not isinstance(max_retries, int)
        or isinstance(max_retries, bool)
        or max_retries < 0
    ):
        max_retries = 2
    initial_step_count = prior_checkpoint.get("step_count", 0)
    if (
        not isinstance(initial_step_count, int)
        or isinstance(initial_step_count, bool)
        or initial_step_count < 0
    ):
        initial_step_count = 0
    initial_retry_count = prior_checkpoint.get("retry_count", 0)
    if (
        not isinstance(initial_retry_count, int)
        or isinstance(initial_retry_count, bool)
        or initial_retry_count < 0
    ):
        initial_retry_count = 0
    retry_budget_exhausted = (
        prior_checkpoint.get("status") == "needs_human"
        and prior_checkpoint.get("exit_reason")
        in {"retry_exhausted", "safety_blocked", "tool_failed"}
        and initial_retry_count >= max_retries
    )
    step_budget_exhausted = initial_step_count >= max_steps
    budget_exhausted = retry_budget_exhausted or step_budget_exhausted
    initial_hard_errors = list(prior_checkpoint.get("hard_errors") or [])
    initial_exit_reason = str(prior_checkpoint.get("exit_reason") or "")
    if initial_exit_reason in {"goal_completed", "unsupported_geometry"}:
        initial_step_count = 0
        initial_retry_count = 0
        initial_hard_errors = []
        initial_exit_reason = ""
        retry_budget_exhausted = False
        step_budget_exhausted = False
        budget_exhausted = False
    if step_budget_exhausted:
        initial_hard_errors = list(
            dict.fromkeys([*initial_hard_errors, "step_limit_exceeded"])
        )
        initial_exit_reason = "retry_exhausted"

    next_state_version = opening_state_version + 1
    turn_execution_deadline_at = _turn_execution_deadline(turn)
    checkpoint_saver = _checkpoint_saver(
        db,
        task_id=task.id,
        turn_id=turn.id,
    )

    def defer_before_side_effect(callback):
        def execute(state):
            # 先等待在途检查点写入结束，防止独立事务干扰业务未提交写入。
            checkpoint_saver.defer()
            return callback(state)

        return execute

    resumed_model_capture: dict[str, Any] | None = None

    def preserve_model_call_capture(callback):
        def execute(state):
            nonlocal resumed_model_capture
            if resumed_model_capture is None:
                resumed_model_capture = _normalized_model_call_capture(
                    state.get("model_call_capture")
                )
            result = callback(state)
            return {
                **result,
                "_model_call_capture": _merge_model_call_capture(
                    resumed_model_capture,
                    _runtime_model_call_capture(model_capture),
                ),
            }

        return execute

    model_attempted = False

    def mark_model_attempted() -> None:
        nonlocal model_attempted
        model_attempted = True

    registry = DesignAgentToolRegistry()

    def resolve_facts(state: dict[str, Any]) -> dict[str, Any]:
        mark_model_attempted()
        extracted = agent_fact_extraction_service.extract_fact_patch(
            message=payload.message,
            current_facts=state.get("facts") or {},
            pending_questions=prior_checkpoint.get("pending_questions") or [],
        )
        values = deepcopy(state.get("facts") or {})
        evidence = deepcopy(state.get("fact_evidence") or {})
        for field_name, value in extracted.patch.model_dump(exclude_unset=True).items():
            values[field_name] = value
            evidence[field_name] = {
                "source": "user_message", "confidence": 1.0, "turn_id": turn.id,
                "accepted": value is not None, "confirmation_required": value is None,
                "quote": extracted.evidence[field_name],
            }
        if payload.answers is not None:
            for field_name, value in payload.answers.model_dump(exclude_none=True).items():
                values[field_name] = value
                evidence[field_name] = {
                    "source": "user_turn", "confidence": 1.0, "turn_id": turn.id,
                    "accepted": True, "confirmation_required": False,
                }
        try:
            AgentFactsPatch.model_validate({key: value for key, value in values.items()
                                           if key in AgentFactsPatch.model_fields})
        except ValidationError as exc:
            raise agent_fact_extraction_service.FactExtractionError(
                "新需求与已确认需求存在冲突，请明确预算区间或尺寸。"
            ) from exc
        return {"facts": values, "fact_evidence": evidence,
                "model_call_capture": _runtime_model_call_capture(model_capture)}

    registry.register("catalog_search", _catalog_tool(db))
    registry.register(
        "design_generation",
        defer_before_side_effect(
            _design_tool(db, task, next_state_version=next_state_version)
        ),
    )
    registry.register(
        "scene_edit",
        preserve_model_call_capture(
            defer_before_side_effect(
                _scene_tool(
                    db,
                    task,
                    payload,
                    turn.id,
                    turn_execution_deadline_at=turn_execution_deadline_at,
                    on_model_attempt=mark_model_attempted,
                )
            )
        ),
    )
    registry.register(
        "plan_refine",
        preserve_model_call_capture(
            defer_before_side_effect(
                _plan_refine_tool(
                    db,
                    task,
                    payload,
                    on_model_attempt=mark_model_attempted,
                )
            )
        ),
    )
    registry.register("custom_furniture_preview", _custom_furniture_tool(db))
    registry.register(
        "open_geometry_edit",
        preserve_model_call_capture(_open_geometry_tool()),
    )
    registry.register(
        "action_plan",
        preserve_model_call_capture(
            defer_before_side_effect(
                _action_plan_tool(
                    db,
                    task,
                    payload,
                    turn.id,
                    turn_execution_deadline_at=turn_execution_deadline_at,
                    on_model_attempt=mark_model_attempted,
                )
            )
        ),
    )
    workflow = DesignAgentWorkflow(
        retrieve_catalog=registry.get("catalog_search"),
        execute_design=registry.get("design_generation"),
        execute_scene=registry.get("scene_edit"),
        execute_plan_refine=registry.get("plan_refine"),
        execute_custom=registry.get("custom_furniture_preview"),
        execute_open_geometry=registry.get("open_geometry_edit"),
        execute_action_plan=registry.get("action_plan"),
        resolve_facts=resolve_facts,
        max_steps=max_steps,
        max_retries=max_retries,
        checkpointer=checkpoint_saver,
    )
    facts, fact_evidence = _facts_for_turn(
        db,
        task,
        payload,
        turn_id=turn.id,
    )
    custom_furniture_spec = _custom_spec_for_turn(task, payload)
    scene_context = (
        {
            "scene_id": payload.scene_id,
            "base_version": payload.base_scene_version,
            "active_room_id": payload.active_room_id,
            "selected_instance_id": payload.selected_instance_id,
        }
        if payload.scene_id is not None
        else None
    )
    state = workflow.run(
        task_id=task.id,
        turn_id=turn.id,
        active_mode=payload.active_mode,
        intent=intent,
        message=payload.message,
        facts=facts,
        fact_evidence=fact_evidence,
        scene_context=scene_context,
        custom_furniture_spec=custom_furniture_spec,
        plan_id=payload.plan_id,
        initial_step_count=initial_step_count,
        initial_retry_count=initial_retry_count,
        initial_hard_errors=initial_hard_errors,
        budget_exhausted=budget_exhausted,
        initial_exit_reason=initial_exit_reason,
        task_state_version=opening_state_version,
        open_geometry_extension=deepcopy(
            prior_checkpoint.get("open_geometry_furniture") or {}
        ),
        turn_execution_deadline_at=turn_execution_deadline_at,
        resume=resume_turn,
    )
    if intent == "action_plan" and state.get("hard_errors"):
        raise AgentActionPlanFailed(state.get("hard_errors") or [])
    facts = deepcopy(state.get("facts") or facts)
    fact_evidence = deepcopy(state.get("fact_evidence") or fact_evidence)
    effective_model_capture = _effective_model_call_capture(
        state,
        model_capture,
    )
    checkpoint_base_version = state.get("task_state_version", opening_state_version)
    if (
        not isinstance(checkpoint_base_version, int)
        or isinstance(checkpoint_base_version, bool)
        or checkpoint_base_version < 0
    ):
        checkpoint_base_version = opening_state_version
    next_state_version = checkpoint_base_version + 1

    requirement = deepcopy(task.confirmed_requirement_json or {})
    requirement.update(facts)
    public_result = _public_result(state.get("result"))
    scene_ref = (public_result or {}).get("scene_ref") or prior_checkpoint.get(
        "scene_ref"
    )
    run_id = (
        public_result.get("run_id")
        if intent == "design" and isinstance(public_result, dict)
        else None
    )
    generation_run = db.get(GenerationRun, run_id) if isinstance(run_id, int) else None
    checkpoint = {
        "status": state["status"],
        "active_mode": payload.active_mode,
        "active_room_id": payload.active_room_id,
        "intent": intent,
        "current_node": state["current_node"],
        "facts": facts,
        "fact_evidence": state.get("fact_evidence", fact_evidence),
        "pending_questions": state.get("pending_questions", []),
        "step_count": state["step_count"],
        "retry_count": state["retry_count"],
        "max_steps": state["max_steps"],
        "max_retries": state["max_retries"],
        "hard_errors": state.get("hard_errors", []),
        "custom_furniture_spec": (
            state.get("custom_furniture_spec") or None
        ),
        "approval_required": state.get("approval_required", False),
        "exit_reason": state["exit_reason"],
        "scene_ref": scene_ref,
        "run_id": run_id,
        "turn_execution_deadline_at": state.get("turn_execution_deadline_at"),
        **generation_run_service.agent_execution_control(generation_run),
        "result": public_result,
    }
    candidate_open_geometry = None
    if intent == "open_geometry":
        candidate_open_geometry = _validated_open_geometry_extension(
            task.id,
            state.get("open_geometry_extension"),
            result=public_result,
            prior_state=prior_checkpoint.get("open_geometry_furniture"),
        )
    elif intent == "action_plan":
        geometry_result = next(
            (
                action.get("result")
                for action in (public_result or {}).get("actions", [])
                if action.get("tool") == "open_geometry.edit"
            ),
            None,
        )
        validated_action_extension = _validated_open_geometry_extension(
            task.id,
            state.get("open_geometry_extension"),
            result=geometry_result,
            prior_state=prior_checkpoint.get("open_geometry_furniture"),
        )
        if geometry_result is not None:
            candidate_open_geometry = validated_action_extension
    checkpoint = _preserve_agent_state_extensions(
        prior_checkpoint,
        checkpoint,
        extension=(
            {"open_geometry_furniture": candidate_open_geometry}
            if candidate_open_geometry is not None
            else None
        ),
    )
    state_update = db.execute(
        update(DesignTask)
        .where(
            DesignTask.id == task.id,
            DesignTask.agent_state_version == next_state_version - 1,
        )
        .values(
            agent_state_version=next_state_version,
            agent_state_json=checkpoint,
            active_mode=payload.active_mode,
            status=state["status"],
            confirmed_requirement_json=requirement,
            space_type=facts.get("space_type"),
            style=facts.get("style"),
            budget_min=facts.get("budget_min"),
            budget_max=facts.get("budget_max"),
        )
        .execution_options(synchronize_session=False)
    )
    if state_update.rowcount != 1:
        conflict = _record_state_conflict(
            db,
            task_id=task.id,
            payload=payload,
            model_capture=effective_model_capture,
        )
        if isinstance(conflict, dict):
            return conflict
        raise conflict

    events = _events_from_state(task.id, turn.id, state)
    db.add_all(events)
    db.flush()
    _record_agent_timeline_event(
        db,
        event=events[-1],
        model_attempted=model_attempted,
        model_capture=effective_model_capture,
    )
    agent_approval_service.ensure_for_agent_handoff(
        db,
        task=task,
        turn=turn,
        state=state,
    )
    reply = _reply(state)
    response = {
        "task_id": task.id,
        "turn_id": turn.id,
        "state_version": next_state_version,
        "status": state["status"],
        "active_mode": payload.active_mode,
        "active_room_id": payload.active_room_id,
        "intent": intent,
        "reply": reply,
        "state": checkpoint,
        "pending_questions": state.get("pending_questions", []),
        "events": [_event_payload(event) for event in events],
        "approval_required": state.get("approval_required", False),
        "scene_ref": scene_ref,
        "run_id": run_id,
        "exit_reason": state["exit_reason"],
        "result": public_result,
        "open_geometry": _open_geometry_payload(
            task.id, checkpoint.get("open_geometry_furniture")
        ),
        "partialCompletion": False,
    }
    turn.status = state["status"]
    turn.response_json = deepcopy(response)
    turn.completed_at = _utc_now()
    db.add(ChatLog(task_id=task.id, role="user", content=payload.message))
    db.add(ChatLog(task_id=task.id, role="ai", content=reply))
    db.commit()
    checkpoint_saver.flush_deferred()
    return response


def _persist_failed_turn(
    db: Session,
    *,
    task_id: int,
    payload: AgentTurnRequest,
    error: Exception,
    model_capture: llm_service.ModelCallCapture | None = None,
) -> dict[str, Any]:
    db.rollback()
    task = _lock_task_for_turn(db, task_id)
    turn = db.scalars(
        select(DesignAgentTurn).where(
            DesignAgentTurn.task_id == task_id,
            DesignAgentTurn.client_turn_id == payload.client_turn_id,
        )
    ).first()
    if task is None or turn is None:
        raise error
    if turn.response_json is not None:
        return deepcopy(turn.response_json)

    task.agent_state_version = (task.agent_state_version or 0) + 1
    task.active_mode = payload.active_mode
    task.status = "failed"
    prior_checkpoint = (
        task.agent_state_json if isinstance(task.agent_state_json, dict) else {}
    )
    prior_facts = prior_checkpoint.get("facts") or {}
    prior_fact_evidence = prior_checkpoint.get("fact_evidence") or {}
    failure_codes = (
        error.codes
        if isinstance(error, AgentActionPlanFailed)
        else ["fact_extraction_failed"]
        if isinstance(error, agent_fact_extraction_service.FactExtractionError)
        else ["llm_unavailable"]
        if isinstance(error, LLMUnavailable)
        else ["tool_timeout"]
        if isinstance(error, TimeoutError)
        else ["internal_error"]
    )
    step_count = prior_checkpoint.get("step_count", 0)
    if (
        not isinstance(step_count, int)
        or isinstance(step_count, bool)
        or step_count < 0
    ):
        step_count = 0
    retry_count = prior_checkpoint.get("retry_count", 0)
    if (
        not isinstance(retry_count, int)
        or isinstance(retry_count, bool)
        or retry_count < 0
    ):
        retry_count = 0
    max_steps = prior_checkpoint.get("max_steps", 12)
    if (
        not isinstance(max_steps, int)
        or isinstance(max_steps, bool)
        or max_steps < 1
    ):
        max_steps = 12
    max_retries = prior_checkpoint.get("max_retries", 2)
    if (
        not isinstance(max_retries, int)
        or isinstance(max_retries, bool)
        or max_retries < 0
    ):
        max_retries = 2
    checkpoint = {
        "status": "failed",
        "active_mode": payload.active_mode,
        "active_room_id": payload.active_room_id,
        "intent": turn.intent,
        "current_node": "failed",
        "facts": deepcopy(prior_facts),
        "fact_evidence": deepcopy(prior_fact_evidence),
        "pending_questions": [],
        "step_count": step_count,
        "retry_count": retry_count,
        "max_steps": max_steps,
        "max_retries": max_retries,
        "hard_errors": list(
            dict.fromkeys(
                [*(prior_checkpoint.get("hard_errors") or []), *failure_codes]
            )
        ),
        "custom_furniture_spec": deepcopy(
            (task.agent_state_json or {}).get("custom_furniture_spec")
        ),
        "approval_required": False,
        "exit_reason": "tool_failed",
        "scene_ref": deepcopy(prior_checkpoint.get("scene_ref")),
        "run_id": None,
        "turn_execution_deadline_at": prior_checkpoint.get(
            "turn_execution_deadline_at"
        ),
        **generation_run_service.agent_execution_control(None),
        "result": (
            {
                "status": "failed",
                "code": failure_codes[0],
                "message": "本轮动作未通过确定性门禁，未提交任何家具或场景变更。",
                "partialCompletion": False,
            }
            if isinstance(error, AgentActionPlanFailed)
            else None
        ),
    }
    checkpoint = _preserve_agent_state_extensions(prior_checkpoint, checkpoint)
    task.agent_state_json = checkpoint
    event = DesignAgentEvent(
        task_id=task.id,
        turn_id=turn.id,
        sequence=1,
        event_type="failed",
        node="failed",
        status="failed",
        source="orchestrator",
        summary="本轮执行失败，未提交方案或场景副作用",
        details_json={
            "error_type": type(error).__name__,
            "reason_codes": failure_codes,
        },
    )
    db.add(event)
    db.flush()
    _record_agent_timeline_event(
        db,
        event=event,
        state="failed",
        model_capture=model_capture,
    )
    reply = (
        "本轮动作未通过确定性门禁，未提交任何家具或场景变更。"
        if isinstance(error, AgentActionPlanFailed)
        else "本轮执行失败，已安全停止。请稍后重试或由人工继续处理。"
    )
    response = {
        "task_id": task.id,
        "turn_id": turn.id,
        "state_version": task.agent_state_version,
        "status": "failed",
        "active_mode": payload.active_mode,
        "active_room_id": payload.active_room_id,
        "intent": turn.intent,
        "reply": reply,
        "state": checkpoint,
        "pending_questions": [],
        "events": [_event_payload(event)],
        "approval_required": False,
        "scene_ref": deepcopy(prior_checkpoint.get("scene_ref")),
        "run_id": None,
        "exit_reason": "tool_failed",
        "result": checkpoint["result"],
        "open_geometry": _open_geometry_payload(
            task.id, checkpoint.get("open_geometry_furniture")
        ),
        "partialCompletion": False,
    }
    turn.status = "failed"
    turn.response_json = deepcopy(response)
    turn.completed_at = _utc_now()
    db.add(ChatLog(task_id=task.id, role="user", content=payload.message))
    db.add(ChatLog(task_id=task.id, role="ai", content=reply))
    db.commit()
    return response


def run_turn(
    db: Session,
    *,
    task: DesignTask,
    payload: AgentTurnRequest,
) -> dict[str, Any]:
    task_id = task.id
    with (
        model_call_governance_service.govern_task_model_calls(
            db,
            task_id=task_id,
            operation_key=f"agent-turn:{payload.client_turn_id}",
        ),
        llm_service.capture_model_call() as model_capture,
    ):
        try:
            return _run_turn(
                db,
                task=task,
                payload=payload,
                model_capture=model_capture,
            )
        except (
            AgentSceneNotFound,
            AgentSceneVersionConflict,
            AgentIdempotencyConflict,
            AgentTurnInProgress,
            AgentStateVersionConflict,
        ):
            raise
        except Exception as exc:
            logger.exception(
                "Design Agent turn 执行失败: task_id=%s client_turn_id=%s",
                task_id,
                payload.client_turn_id,
            )
            return _persist_failed_turn(
                db,
                task_id=task_id,
                payload=payload,
                error=exc,
                model_capture=model_capture,
            )


def get_checkpoint(db: Session, task: DesignTask) -> dict[str, Any]:
    generation_run_service.synchronize_agent_checkpoint(db, task=task)
    state = _checkpoint_state(task)
    room_model = None
    room_source = None
    images = db.scalars(
        select(UploadedImage)
        .where(UploadedImage.task_id == task.id)
        .order_by(UploadedImage.id.desc())
    ).all()
    for image in images:
        raw_room_model = (image.analysis_json or {}).get("room_model")
        if not isinstance(raw_room_model, dict):
            continue
        try:
            room_model = RoomModel.model_validate(raw_room_model).model_dump(
                by_alias=True,
                mode="json",
            )
        except (TypeError, ValueError):
            continue
        room_source = {
            "image_id": image.id,
            "image_url": image.file_url,
            "file_name": image.file_name,
        }
        break
    messages = db.scalars(
        select(ChatLog)
        .where(ChatLog.task_id == task.id)
        .order_by(ChatLog.id)
    ).all()
    latest_draft = db.scalar(
        select(CustomFurnitureDraftMutation)
        .where(CustomFurnitureDraftMutation.task_id == task.id)
        .order_by(CustomFurnitureDraftMutation.id.desc())
        .limit(1)
    )
    draft_ref = None
    if latest_draft is not None and isinstance(latest_draft.response_json, dict):
        response = latest_draft.response_json
        if (
            response.get("custom_furniture_spec")
            == state.get("custom_furniture_draft")
            and isinstance(response.get("state_version"), int)
        ):
            draft_ref = {
                "client_mutation_id": latest_draft.client_mutation_id,
                "state_version": response["state_version"],
            }
    return {
        "task_id": task.id,
        "state_version": task.agent_state_version or 0,
        "confirmed_requirement": deepcopy(task.confirmed_requirement_json or {}),
        **state,
        "room_model": room_model,
        "room_source": room_source,
        "custom_furniture_draft_ref": draft_ref,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in messages
        ],
        "open_geometry": _open_geometry_payload(
            task.id, state.get("open_geometry_furniture")
        ),
    }


def _checkpoint_state(task: DesignTask) -> dict[str, Any]:
    defaults = {
        "status": "draft",
        "active_mode": task.active_mode or "catalog_design",
        "active_room_id": None,
        "intent": "unknown",
        "current_node": "start",
        "facts": _normalize_requirement_facts(task.confirmed_requirement_json or {}),
        "fact_evidence": {},
        "pending_questions": [],
        "step_count": 0,
        "retry_count": 0,
        "max_steps": 12,
        "max_retries": 2,
        "hard_errors": [],
        "custom_furniture_spec": None,
        "custom_furniture_draft": None,
        "approval_required": False,
        "exit_reason": "missing_facts",
        "scene_ref": None,
        "run_id": None,
        "turn_execution_deadline_at": None,
        **generation_run_service.agent_execution_control(None),
        "result": None,
    }
    defaults.update(deepcopy(task.agent_state_json or {}))
    return defaults


def record_scene_reference(
    db: Session,
    *,
    task_id: int,
    scene_id: int,
    version: int,
) -> None:
    task = db.scalar(
        select(DesignTask).where(DesignTask.id == task_id).with_for_update()
    )
    if task is None:
        raise AgentSceneNotFound("设计任务不存在")
    checkpoint = _checkpoint_state(task)
    checkpoint["scene_ref"] = {"scene_id": scene_id, "version": version}
    task.agent_state_json = checkpoint
    task.agent_state_version = int(task.agent_state_version or 0) + 1
    db.flush()


def save_custom_furniture_draft(
    db: Session,
    *,
    task: DesignTask,
    payload: CustomFurnitureDraftRequest,
) -> dict[str, Any]:
    """在调用方已持有 DesignTask 聚合锁的事务内保存草稿。"""

    request_json = payload.model_dump(mode="json")
    existing = db.scalar(
        select(CustomFurnitureDraftMutation).where(
            CustomFurnitureDraftMutation.task_id == task.id,
            CustomFurnitureDraftMutation.client_mutation_id == payload.client_mutation_id,
        )
    )
    if existing is not None:
        if existing.request_json != request_json:
            raise AgentIdempotencyConflict("client_mutation_id 已用于不同请求")
        return deepcopy(existing.response_json)

    current_version = int(task.agent_state_version or 0)
    if current_version != payload.base_state_version:
        checkpoint = _checkpoint_state(task)
        raise AgentStateVersionConflict(
            "定制家具草稿已更新，请刷新后重试",
            state_version=current_version,
            custom_furniture_draft=checkpoint.get("custom_furniture_draft"),
            scene_ref=checkpoint.get("scene_ref"),
        )
    next_version = current_version + 1
    spec = payload.custom_furniture_spec.model_dump(mode="json")
    checkpoint = _checkpoint_state(task)
    checkpoint["custom_furniture_draft"] = deepcopy(spec)
    task.agent_state_json = checkpoint
    task.agent_state_version = next_version
    response = {
        "task_id": task.id,
        "state_version": next_version,
        "custom_furniture_spec": spec,
    }
    mutation = CustomFurnitureDraftMutation(
        task_id=task.id,
        client_mutation_id=payload.client_mutation_id,
        request_json=request_json,
        response_json=deepcopy(response),
    )
    db.add(mutation)
    db.flush()
    return response
