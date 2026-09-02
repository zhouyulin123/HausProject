"""DesignTask 聚合根上的统一 Agent turn 服务。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.design_agent import (
    AgentToolRejected,
    DesignAgentToolRegistry,
    DesignAgentWorkflow,
)
from app.agents.design_workflow import DesignWorkflow, WorkflowQualityError
from app.agents.scene_agent import SceneAgentSafetyError, SceneAgentWorkflow
from app.db.models import (
    DesignAgentEvent,
    DesignAgentTurn,
    ChatLog,
    DesignPlanVersion,
    DesignResult,
    DesignRevision,
    DesignScene,
    DesignTask,
    UploadedImage,
)
from app.schemas.design_agent import AgentTurnRequest
from app.schemas.custom_furniture import CustomFurniturePreviewRequest
from app.schemas.room_model import RoomModel
from app.schemas.scene_agent import SceneOperationBatch
from app.schemas.scenes import SceneDocument
from app.services import (
    catalog_service,
    custom_furniture_service,
    design_version_service,
    llm_service,
    scene_service,
    scene_tools,
    task_service,
)
from app.services.llm_service import LLMUnavailable

logger = logging.getLogger(__name__)


class AgentSceneNotFound(ValueError):
    """场景不存在或不属于当前 DesignTask。"""


class AgentSceneVersionConflict(ValueError):
    """场景基线版本已过期，禁止静默覆盖。"""


class AgentTurnInProgress(ValueError):
    """相同幂等键已由另一请求占用且尚未产生最终响应。"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _intent_for(payload: AgentTurnRequest) -> str:
    if payload.scene_id is not None:
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


def _room_facts(db: Session, task_id: int) -> dict[str, Any]:
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
        if model.space_type:
            facts["space_type"] = model.space_type
        # 只有用户校准的绝对尺寸可直接跨过事实门禁。
        if model.scale.source == "user" and room.width_m and room.depth_m:
            facts["room_width_m"] = room.width_m
            facts["room_depth_m"] = room.depth_m
            if room.ceiling_height:
                facts["ceiling_height_m"] = room.ceiling_height
        return facts
    return {}


def _facts_for_turn(
    db: Session,
    task: DesignTask,
    payload: AgentTurnRequest,
) -> dict[str, Any]:
    checkpoint = task.agent_state_json or {}
    facts = deepcopy(checkpoint.get("facts") or {})
    facts.update(
        _normalize_requirement_facts(task.confirmed_requirement_json or {})
    )
    if task.space_type:
        facts["space_type"] = task.space_type
    if task.style:
        facts["style"] = task.style
    if task.budget_min:
        facts["budget_min"] = task.budget_min
    if task.budget_max:
        facts["budget_max"] = task.budget_max
    facts.update(_room_facts(db, task.id))
    if payload.answers is not None:
        facts.update(payload.answers.model_dump(exclude_none=True))
    return facts


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


def _design_tool(db: Session, task: DesignTask):
    def execute(state: dict[str, Any]) -> dict[str, Any]:
        if state["intent"] != "design":
            raise AgentToolRejected(
                "该工作模式的受控工具尚未接入",
                codes=["tool_not_available"],
            )
        requirement = deepcopy(task.confirmed_requirement_json or {})
        requirement.update(state.get("facts", {}))
        requirement["agent_instruction"] = state["message"]
        image_context: list[str] = []
        for image in db.scalars(
            select(UploadedImage).where(UploadedImage.task_id == task.id)
        ):
            findings = (image.analysis_json or {}).get("findings")
            if isinstance(findings, list):
                image_context.extend(str(item) for item in findings)

        facts = state.get("facts", {})
        region = facts.get("delivery_region")
        if not region:
            raise AgentToolRejected(
                "缺少配送地区，禁止生成商用方案",
                codes=["delivery_region_required"],
            )
        budget = facts.get("budget_max")
        max_dimensions_mm = _max_dimensions_from_facts(facts)

        def strict_enrich(plans: list[dict[str, Any]]) -> None:
            catalog_service.verify_and_enrich_plans(
                db,
                plans,
                region=region,
                budget_max=budget if isinstance(budget, int) else None,
                max_dimensions_mm=max_dimensions_mm,
            )

        workflow = DesignWorkflow(
            generate_plans=llm_service.generate_plans,
            build_template_plans=task_service.build_template_plans,
            enrich_plans=strict_enrich,
        )
        try:
            result = workflow.run(
                requirement=requirement,
                image_context=image_context,
                catalog_context=catalog_service.build_catalog_context(
                    db,
                    region=region,
                    max_unit_price=budget if isinstance(budget, int) else None,
                    max_dimensions_mm=max_dimensions_mm,
                ),
            )
        except WorkflowQualityError as exc:
            codes = list(exc.codes)
            message = str(exc)
            if not codes and ("SKU" in message or "商品" in message):
                codes.append("invalid_sku")
            if not codes and "报价" in message:
                codes.append("invalid_quote")
            raise AgentToolRejected(
                message,
                codes=codes or ["quality_gate_failed"],
            ) from exc

        plans = result["plans"]
        quotes = [plan["shopQuote"]["total"] for plan in plans]
        return {
            "plan_count": len(plans),
            "generator": result["generator"],
            "quotes": quotes,
            "quote_consistent": all(
                plan["shopQuote"]["furnitureTotal"]
                + plan["shopQuote"]["customTotal"]
                == plan["shopQuote"]["total"]
                for plan in plans
            ),
            "invalid_skus": [],
            "_plans": plans,
            "_image_context": image_context,
            "_workflow_trace": result["node_trace"],
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
                details_json={"fields": [q["field"] for q in state["pending_questions"]]},
            )
        )
        sequence += 1
    for raw in state.get("tool_events", []):
        completed = raw["status"] == "completed"
        events.append(
            DesignAgentEvent(
                task_id=task_id,
                turn_id=turn_id,
                sequence=sequence,
                event_type="tool_completed" if completed else "validation_failed",
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
                    f"工具 {raw['tool']} 执行完成"
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


def _run_turn(
    db: Session,
    *,
    task: DesignTask,
    payload: AgentTurnRequest,
) -> dict[str, Any]:
    existing = db.scalars(
        select(DesignAgentTurn).where(
            DesignAgentTurn.task_id == task.id,
            DesignAgentTurn.client_turn_id == payload.client_turn_id,
        )
    ).first()
    if existing is not None and existing.response_json is not None:
        return deepcopy(existing.response_json)
    if existing is not None:
        raise AgentTurnInProgress("相同 client_turn_id 的请求仍在处理中")

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
    turn = DesignAgentTurn(
        task_id=task.id,
        client_turn_id=payload.client_turn_id,
        active_mode=payload.active_mode,
        intent=intent,
        status="running",
        request_json=payload.model_dump(mode="json"),
    )
    db.add(turn)
    try:
        # 先占用幂等键，再执行任何模型或场景工具，阻断并发重复调用。
        db.commit()
        db.refresh(turn)
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalars(
            select(DesignAgentTurn).where(
                DesignAgentTurn.task_id == task.id,
                DesignAgentTurn.client_turn_id == payload.client_turn_id,
            )
        ).first()
        if existing is not None and existing.response_json is not None:
            return deepcopy(existing.response_json)
        raise AgentTurnInProgress("相同 client_turn_id 的请求仍在处理中") from exc

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

    registry = DesignAgentToolRegistry()
    registry.register("catalog_search", _catalog_tool(db))
    registry.register("design_generation", _design_tool(db, task))
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
    facts = _facts_for_turn(db, task, payload)
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
        scene_context=scene_context,
        custom_furniture_spec=custom_furniture_spec,
        initial_step_count=initial_step_count,
        initial_retry_count=initial_retry_count,
        initial_hard_errors=initial_hard_errors,
        budget_exhausted=budget_exhausted,
        initial_exit_reason=initial_exit_reason,
    )

    if state["status"] == "completed" and intent == "design":
        result = state.get("result") or {}
        plans = result.get("_plans") or []
        revision = design_version_service.persist_generation(
            db,
            task=task,
            plans=plans,
            generator=result.get("generator") or "agent",
            image_context=result.get("_image_context") or [],
            workflow_trace=result.get("_workflow_trace") or [],
        )
        db.add(
            DesignResult(
                task_id=task.id,
                plans_json=plans,
                generator=result.get("generator") or "agent",
            )
        )
        state["result"]["revision_version"] = revision.version

    task.agent_state_version = (task.agent_state_version or 0) + 1
    task.active_mode = payload.active_mode
    task.status = state["status"]
    requirement = deepcopy(task.confirmed_requirement_json or {})
    requirement.update(facts)
    task.confirmed_requirement_json = requirement
    task.space_type = facts.get("space_type")
    task.style = facts.get("style")
    task.budget_min = facts.get("budget_min")
    task.budget_max = facts.get("budget_max")
    public_result = _public_result(state.get("result"))
    scene_ref = (public_result or {}).get("scene_ref")
    checkpoint = {
        "status": state["status"],
        "active_mode": payload.active_mode,
        "active_room_id": payload.active_room_id,
        "intent": intent,
        "current_node": state["current_node"],
        "facts": facts,
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
        "result": public_result,
    }
    task.agent_state_json = checkpoint

    events = _events_from_state(task.id, turn.id, state)
    db.add_all(events)
    db.flush()
    reply = _reply(state)
    response = {
        "task_id": task.id,
        "turn_id": turn.id,
        "state_version": task.agent_state_version,
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
    task = db.get(DesignTask, task_id)
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
    prior_facts = (task.agent_state_json or {}).get("facts") or {}
    checkpoint = {
        "status": "failed",
        "active_mode": payload.active_mode,
        "active_room_id": payload.active_room_id,
        "intent": turn.intent,
        "current_node": "failed",
        "facts": deepcopy(prior_facts),
        "pending_questions": [],
        "step_count": 0,
        "retry_count": 0,
        "max_steps": 12,
        "max_retries": 2,
        "hard_errors": ["internal_error"],
        "custom_furniture_spec": deepcopy(
            (task.agent_state_json or {}).get("custom_furniture_spec")
        ),
        "approval_required": False,
        "exit_reason": "tool_failed",
        "scene_ref": None,
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
        AgentTurnInProgress,
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
    state = deepcopy(task.agent_state_json or {})
    if not state:
        state = {
            "status": "draft",
            "active_mode": task.active_mode or "catalog_design",
            "active_room_id": None,
            "intent": "unknown",
            "current_node": "start",
            "facts": _normalize_requirement_facts(
                task.confirmed_requirement_json or {}
            ),
            "pending_questions": [],
            "step_count": 0,
            "retry_count": 0,
            "max_steps": 12,
            "max_retries": 2,
            "hard_errors": [],
            "custom_furniture_spec": None,
            "approval_required": False,
            "exit_reason": "missing_facts",
            "scene_ref": None,
            "result": None,
        }
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
