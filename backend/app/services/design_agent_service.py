"""DesignTask 聚合根上的统一 Agent turn 服务。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
from math import isclose
import re
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
    DesignTask,
    RoomFactConfirmation,
    UploadedImage,
)
from app.schemas.design_agent import AgentTurnRequest, CustomFurnitureDraftRequest
from app.schemas.custom_furniture import CustomFurniturePreviewRequest
from app.schemas.room_model import RoomModel
from app.schemas.scene_agent import SceneOperationBatch
from app.schemas.scenes import SceneDocument
from app.services import (
    aggregate_lock_service,
    catalog_service,
    custom_furniture_service,
    generation_request_service,
    generation_run_service,
    llm_service,
    scene_service,
    scene_tools,
)
from app.services.llm_service import LLMUnavailable

logger = logging.getLogger(__name__)
ROOM_FACT_CONFIDENCE_THRESHOLD = 0.8


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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _intent_for(payload: AgentTurnRequest) -> str:
    if payload.scene_id is not None:
        return "scene_edit"
    if (
        payload.active_mode in {"catalog_design", "room_reconstruction"}
        and classify_scene_edit_intent(payload.message)
    ):
        return "scene_edit"
    if payload.active_mode != "catalog_design":
        return payload.active_mode
    return "design"


def _normalize_requirement_facts(requirement: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    aliases = {
        "space_type": ("space_type", "spaceType"),
        "style": ("style",),
        "budget_min": ("budget_min", "budgetMin"),
        "budget_max": ("budget_max", "budgetMax", "budget"),
        "room_width_m": ("room_width_m", "roomWidthM", "roomWidth"),
        "room_depth_m": ("room_depth_m", "roomDepthM", "roomDepth"),
        "ceiling_height_m": (
            "ceiling_height_m",
            "ceilingHeightM",
            "ceilingHeight",
        ),
        "delivery_region": (
            "delivery_region",
            "deliveryRegion",
            "region_code",
            "regionCode",
        ),
    }
    for target, keys in aliases.items():
        for key in keys:
            value = requirement.get(key)
            if value not in (None, "", 0):
                facts[target] = value
                break
    rooms = requirement.get("rooms")
    if "space_type" not in facts and isinstance(rooms, list) and rooms:
        if isinstance(rooms[0], str) and rooms[0].strip():
            facts["space_type"] = rooms[0].strip()
    styles = requirement.get("styles")
    if "style" not in facts and isinstance(styles, list) and styles:
        if isinstance(styles[0], str) and styles[0].strip():
            facts["style"] = styles[0].strip()
    budget_min, budget_max = _parse_budget_range(requirement.get("budgetRange"))
    if "budget_min" not in facts and budget_min is not None:
        facts["budget_min"] = budget_min
    if "budget_max" not in facts and budget_max is not None:
        facts["budget_max"] = budget_max
    if "delivery_region" in facts:
        facts["delivery_region"] = str(facts["delivery_region"]).strip().upper()
    return facts


def confirmed_generation_facts(task: DesignTask) -> dict[str, Any]:
    """返回生成链可使用的已确认事实，不从未确认输入推断硬约束。"""
    facts = _normalize_requirement_facts(task.confirmed_requirement_json or {})
    if task.budget_max is not None:
        facts["budget_max"] = task.budget_max
    return facts


def missing_confirmed_generation_facts(task: DesignTask) -> list[str]:
    """返回旧生成入口缺失的已确认硬事实，语义与 Agent 事实门禁一致。"""
    facts = confirmed_generation_facts(task)

    def positive_number(value: Any) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
        )

    missing: list[str] = []
    if not positive_number(facts.get("budget_max")):
        missing.append("budget_max")
    if not (
        positive_number(facts.get("room_width_m"))
        and positive_number(facts.get("room_depth_m"))
    ):
        missing.append("room_dimensions")
    return missing


def _parse_budget_range(value: Any) -> tuple[int | None, int | None]:
    """解析现有 UserRequirement 的中文预算范围，不从面积推测预算。"""
    if not isinstance(value, str) or not value.strip():
        return None, None
    normalized = value.replace("，", "").replace(",", "").strip()
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", normalized)]
    if not numbers:
        return None, None
    multiplier = 10_000 if "万" in normalized else 1
    amounts = [round(number * multiplier) for number in numbers]
    if len(amounts) >= 2 and any(mark in normalized for mark in ("-", "~", "至")):
        low, high = amounts[0], amounts[1]
        return min(low, high), max(low, high)
    amount = amounts[0]
    if any(mark in normalized for mark in ("以上", "起")):
        return amount, None
    return None, amount


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
    width = facts.get("room_width_m")
    depth = facts.get("room_depth_m")
    if not isinstance(width, (int, float)) or not isinstance(depth, (int, float)):
        return None
    dimensions = {
        "width": round(float(width) * 1000),
        "depth": round(float(depth) * 1000),
    }
    height = facts.get("ceiling_height_m")
    if isinstance(height, (int, float)):
        dimensions["height"] = round(float(height) * 1000)
    return dimensions


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
        products.sort(key=lambda product: (product.price, product.id or 0))
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
                }
                for product in products[:20]
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


def _scene_tool(db: Session, task: DesignTask, payload: AgentTurnRequest):
    def execute(state: dict[str, Any]) -> dict[str, Any]:
        if payload.scene_id is None or payload.base_scene_version is None:
            raise AgentToolRejected(
                "场景修改缺少场景版本",
                codes=["scene_context_missing"],
            )
        scene = _load_task_scene(db, task_id=task.id, scene_id=payload.scene_id)
        if scene is None:
            raise AgentSceneNotFound("场景不存在或不属于当前任务")
        if scene.current_version != payload.base_scene_version:
            raise AgentSceneVersionConflict(
                f"场景已经更新到版本 {scene.current_version}"
            )
        current = scene_service.get_current_version(db, scene)
        document = SceneDocument.model_validate(current.scene_json)
        context = scene_tools.build_scene_agent_context(db, document)
        try:
            batch: SceneOperationBatch = llm_service.plan_scene_operations(
                instruction=state["message"],
                context=context,
            )
            workflow = SceneAgentWorkflow(
                plan_operations=lambda **_: batch,
                execute_operations=lambda source, operations: (
                    scene_tools.apply_scene_operations(db, source, operations)
                ),
                validate_scene=lambda candidate: scene_service.validate_scene(
                    db, candidate
                ),
            )
            workflow_result = workflow.run(
                instruction=state["message"],
                context=context,
                source_scene=document,
            )
        except LLMUnavailable as exc:
            raise AgentToolRejected(str(exc), codes=["model_unavailable"]) from exc
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
        try:
            version = scene_service.update_scene(
                db,
                scene=refreshed,
                base_version=payload.base_scene_version,
                document=proposed,
                source="scene_agent",
            )
        except scene_service.SceneConflictError as exc:
            raise AgentSceneVersionConflict(str(exc)) from exc
        except scene_service.SceneValidationError as exc:
            codes = [issue.code for issue in exc.report.errors]
            raise AgentToolRejected(str(exc), codes=codes) from exc
        return {
            "operation_count": len(batch.operations),
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
    if state["intent"] == "custom_furniture":
        return "已生成通过参数校验且报价可复算的定制家具预览。"
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
        "sequence": event.sequence,
        "type": event.event_type,
        "node": event.node,
        "status": event.status,
        "source": event.source,
        "summary": event.summary,
        "details": event.details_json or {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
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
    deadline = _as_utc(turn.created_at) + timedelta(
        seconds=settings.design_agent_turn_lease_seconds
    )
    return deadline <= _as_utc(now)


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
) -> tuple[DesignTask, DesignAgentTurn, dict[str, Any] | None]:
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
            return task, existing, _existing_turn_result(existing, payload)
        if not _turn_lease_expired(existing, now=now):
            raise AgentTurnInProgress("相同 client_turn_id 的请求仍在处理中")
        response = _recover_stale_turn(db, task=task, turn=existing)
        db.commit()
        return task, existing, response

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
            return task, existing, _existing_turn_result(existing, payload)
        raise AgentTurnInProgress("相同 client_turn_id 的请求仍在处理中") from exc
    return task, turn, None


def _record_state_conflict(
    db: Session,
    *,
    task_id: int,
    payload: AgentTurnRequest,
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
    db.add(
        DesignAgentEvent(
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
) -> dict[str, Any]:
    task, turn, claimed_response = _claim_turn(
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
    checkpoint = (
        task.agent_state_json if isinstance(task.agent_state_json, dict) else {}
    )
    max_steps = checkpoint.get("max_steps", 12)
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
        max_steps = 12
    max_retries = checkpoint.get("max_retries", 2)
    if (
        not isinstance(max_retries, int)
        or isinstance(max_retries, bool)
        or max_retries < 0
    ):
        max_retries = 2
    initial_step_count = checkpoint.get("step_count", 0)
    if (
        not isinstance(initial_step_count, int)
        or isinstance(initial_step_count, bool)
        or initial_step_count < 0
    ):
        initial_step_count = 0
    initial_retry_count = checkpoint.get("retry_count", 0)
    if (
        not isinstance(initial_retry_count, int)
        or isinstance(initial_retry_count, bool)
        or initial_retry_count < 0
    ):
        initial_retry_count = 0
    retry_budget_exhausted = (
        checkpoint.get("status") == "needs_human"
        and checkpoint.get("exit_reason")
        in {"retry_exhausted", "safety_blocked", "tool_failed"}
        and initial_retry_count >= max_retries
    )
    step_budget_exhausted = initial_step_count >= max_steps
    budget_exhausted = retry_budget_exhausted or step_budget_exhausted
    initial_hard_errors = list(checkpoint.get("hard_errors") or [])
    initial_exit_reason = str(checkpoint.get("exit_reason") or "")
    if step_budget_exhausted:
        initial_hard_errors = list(
            dict.fromkeys([*initial_hard_errors, "step_limit_exceeded"])
        )
        initial_exit_reason = "retry_exhausted"

    next_state_version = (task.agent_state_version or 0) + 1
    registry = DesignAgentToolRegistry()
    registry.register("catalog_search", _catalog_tool(db))
    registry.register(
        "design_generation",
        _design_tool(db, task, next_state_version=next_state_version),
    )
    registry.register("scene_edit", _scene_tool(db, task, payload))
    registry.register("custom_furniture_preview", _custom_furniture_tool(db))
    workflow = DesignAgentWorkflow(
        retrieve_catalog=registry.get("catalog_search"),
        execute_design=registry.get("design_generation"),
        execute_scene=registry.get("scene_edit"),
        execute_custom=registry.get("custom_furniture_preview"),
        max_steps=max_steps,
        max_retries=max_retries,
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
        initial_step_count=initial_step_count,
        initial_retry_count=initial_retry_count,
        initial_hard_errors=initial_hard_errors,
        budget_exhausted=budget_exhausted,
        initial_exit_reason=initial_exit_reason,
    )

    requirement = deepcopy(task.confirmed_requirement_json or {})
    requirement.update(facts)
    public_result = _public_result(state.get("result"))
    scene_ref = (public_result or {}).get("scene_ref")
    run_id = (
        public_result.get("run_id")
        if intent == "design" and isinstance(public_result, dict)
        else None
    )
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
        "result": public_result,
    }
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
        )
        if isinstance(conflict, dict):
            return conflict
        raise conflict

    events = _events_from_state(task.id, turn.id, state)
    db.add_all(events)
    db.flush()
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
    }
    turn.status = state["status"]
    turn.response_json = deepcopy(response)
    turn.completed_at = _utc_now()
    db.add(ChatLog(task_id=task.id, role="user", content=payload.message))
    db.add(ChatLog(task_id=task.id, role="ai", content=reply))
    db.commit()
    return response


def _persist_failed_turn(
    db: Session,
    *,
    task_id: int,
    payload: AgentTurnRequest,
    error: Exception,
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
                [*(prior_checkpoint.get("hard_errors") or []), "internal_error"]
            )
        ),
        "custom_furniture_spec": deepcopy(
            (task.agent_state_json or {}).get("custom_furniture_spec")
        ),
        "approval_required": False,
        "exit_reason": "tool_failed",
        "scene_ref": None,
        "run_id": None,
        "result": None,
    }
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
        details_json={"error_type": type(error).__name__},
    )
    db.add(event)
    db.flush()
    reply = "本轮执行失败，已安全停止。请稍后重试或由人工继续处理。"
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
        "scene_ref": None,
        "run_id": None,
        "exit_reason": "tool_failed",
        "result": None,
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
    try:
        return _run_turn(db, task=task, payload=payload)
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
            task.id,
            payload.client_turn_id,
        )
        return _persist_failed_turn(
            db,
            task_id=task.id,
            payload=payload,
            error=exc,
        )


def get_checkpoint(db: Session, task: DesignTask) -> dict[str, Any]:
    generation_run_service.synchronize_agent_checkpoint(db, task=task)
    state = _checkpoint_state(task)
    messages = db.scalars(
        select(ChatLog)
        .where(ChatLog.task_id == task.id)
        .order_by(ChatLog.id)
    ).all()
    return {
        "task_id": task.id,
        "state_version": task.agent_state_version or 0,
        **state,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in messages
        ],
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
