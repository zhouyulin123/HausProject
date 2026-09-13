"""工作台商品操作的版本化、幂等和原子持久化。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from math import pi

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    DesignFeedbackEvent,
    DesignPlanVersion,
    DesignRevision,
    Product,
)
from app.schemas.feedback import DesignFeedbackEventRequest
from app.schemas.scenes import (
    PositiveVector3,
    SceneDocument,
    SceneItem,
    Transform,
    Vector3,
)
from app.schemas.tasks import PlanMutationRequest
from app.services import (
    catalog_service,
    design_version_service,
    feedback_service,
    scene_service,
)
from app.services.product_asset_service import product_asset_contract


class PlanMutationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PlanMutationConflict(PlanMutationError):
    pass


class PlacementNotFound(PlanMutationError):
    pass


def _digest(payload: PlanMutationRequest) -> str:
    encoded = json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _latest_revision(db: Session, task_id: int) -> DesignRevision | None:
    return db.scalars(
        select(DesignRevision)
        .options(selectinload(DesignRevision.plans))
        .where(DesignRevision.task_id == task_id)
        .order_by(DesignRevision.version.desc())
        .with_for_update()
    ).first()


def _owned_plan(
    db: Session,
    *,
    task_id: int,
    plan_version_id: int,
) -> DesignPlanVersion | None:
    return db.scalars(
        select(DesignPlanVersion)
        .options(selectinload(DesignPlanVersion.scene))
        .join(DesignRevision, DesignRevision.id == DesignPlanVersion.revision_id)
        .where(
            DesignPlanVersion.id == plan_version_id,
            DesignRevision.task_id == task_id,
        )
    ).first()


def _require_product(db: Session, sku: str, *, region: str | None) -> Product:
    normalized = sku.strip().upper()
    product = db.scalar(select(Product).where(Product.sku == normalized))
    if product is None:
        raise PlanMutationError("sku_not_found", f"商品 {normalized} 不存在")
    eligibility = catalog_service.is_product_eligible(product, region=region)
    if not eligibility.eligible:
        raise PlanMutationError(
            eligibility.reason_codes[0],
            f"商品 {normalized} 当前不可用于商用方案",
        )
    return product


def _product_item(
    product: Product,
    *,
    instance_id: str,
    transform: Transform,
) -> SceneItem:
    contract = product_asset_contract(product)
    return SceneItem(
        instance_id=instance_id,
        sku=product.sku or "",
        category=product.category,
        dimensions=PositiveVector3(
            x=float(product.model_width_mm or 0) / 1000,
            y=float(product.model_height_mm or 0) / 1000,
            z=float(product.model_depth_mm or 0) / 1000,
        ),
        transform=transform,
        asset_mode=contract["asset_mode"],
        fallback_reason=contract["fallback_reason"],
    )


_PLACEMENT_BLOCKERS = {
    "item_outside_room",
    "item_exceeds_room",
    "item_collision",
    "door_clearance_blocked",
}


def _placement_is_valid(db: Session, document: SceneDocument, instance_id: str) -> bool:
    report = scene_service.validate_scene(db, document)
    if not report.valid:
        return False
    return not any(
        issue.code in _PLACEMENT_BLOCKERS
        and (issue.path is None or instance_id in issue.path)
        for issue in report.warnings
    )


def _place_new_item(
    db: Session,
    *,
    document: SceneDocument,
    product: Product,
    payload: PlanMutationRequest,
) -> SceneItem:
    mutation_suffix = hashlib.sha256(
        payload.client_mutation_id.encode("utf-8")
    ).hexdigest()[:16]
    instance_id = f"workspace-{mutation_suffix}"
    height = float(product.model_height_mm or 0) / 1000
    if payload.placement_mode == "explicit":
        item = _product_item(
            product,
            instance_id=instance_id,
            transform=payload.placement_transform,
        )
        candidate = document.model_copy(deep=True)
        candidate.items.append(item)
        if _placement_is_valid(db, candidate, instance_id):
            return item
        raise PlacementNotFound("placement_not_found", "所选落点不满足空间硬约束")

    xs = [point.x for point in document.room.floor_polygon]
    zs = [point.z for point in document.room.floor_polygon]
    for rotation_y in (0.0, pi / 2):
        width = float(
            product.model_width_mm if rotation_y == 0 else product.model_depth_mm
        ) / 1000
        depth = float(
            product.model_depth_mm if rotation_y == 0 else product.model_width_mm
        ) / 1000
        x = min(xs) + width / 2
        while x <= max(xs) - width / 2 + 1e-9:
            z = min(zs) + depth / 2
            while z <= max(zs) - depth / 2 + 1e-9:
                item = _product_item(
                    product,
                    instance_id=instance_id,
                    transform=Transform(
                        position=Vector3(x=round(x, 4), y=height / 2, z=round(z, 4)),
                        rotation=Vector3(x=0, y=rotation_y, z=0),
                    ),
                )
                candidate = document.model_copy(deep=True)
                candidate.items.append(item)
                if _placement_is_valid(db, candidate, instance_id):
                    return item
                z += 0.25
            x += 0.25
    raise PlacementNotFound("placement_not_found", "房间内没有满足碰撞约束的可用落点")


def _mutate_plan_items(
    plan: dict,
    *,
    action: str,
    source_sku: str | None,
    target_sku: str | None,
) -> None:
    items = [deepcopy(item) for item in plan.get("furnitureSuggestions") or []]
    if action == "adopt":
        items.append({"sku": target_sku, "quantity": 1})
    else:
        remaining = 1
        result: list[dict] = []
        for item in items:
            sku = item.get("sku") or item.get("id")
            quantity = max(1, int(item.get("quantity") or 1))
            if sku == source_sku and remaining:
                if quantity > 1:
                    item["quantity"] = quantity - 1
                    result.append(item)
                if action == "replace":
                    result.append({"sku": target_sku, "quantity": 1})
                remaining = 0
            else:
                result.append(item)
        if remaining:
            raise PlanMutationError("instance_plan_mismatch", "场景实例与方案商品不一致")
        items = result
    plan["furnitureSuggestions"] = items


def _response_parts(db: Session, revision: DesignRevision, plan_key: str):
    plan = next(item for item in revision.plans if item.plan_key == plan_key)
    scene = scene_service.get_scene_by_plan_version(db, plan.id)
    if scene is None:
        raise RuntimeError("工作台变更缺少场景版本")
    version = scene_service.get_current_version(db, scene)
    feedback = db.scalar(
        select(DesignFeedbackEvent).where(
            DesignFeedbackEvent.task_id == revision.task_id,
            DesignFeedbackEvent.client_event_id == revision.client_mutation_id,
        )
    )
    if feedback is None:
        raise RuntimeError("工作台变更缺少派生反馈")
    plan_payload = deepcopy(plan.plan_json or {})
    plan_payload["planVersionId"] = plan.id
    plan_payload["planKey"] = plan.plan_key
    return plan_payload, scene, version, feedback


def mutate_plan(db: Session, *, task, payload: PlanMutationRequest):
    digest = _digest(payload)
    existing = db.scalars(
        select(DesignRevision)
        .options(selectinload(DesignRevision.plans))
        .where(
            DesignRevision.task_id == task.id,
            DesignRevision.client_mutation_id == payload.client_mutation_id,
        )
    ).first()
    source_plan = _owned_plan(
        db,
        task_id=task.id,
        plan_version_id=payload.plan_version_id,
    )
    if source_plan is None:
        raise PlanMutationError("plan_not_found", "方案不存在或不属于当前任务")
    if existing is not None:
        if existing.mutation_digest != digest:
            raise PlanMutationConflict("idempotency_conflict", "幂等键已用于不同变更")
        return (existing, *_response_parts(db, existing, source_plan.plan_key))

    latest = _latest_revision(db, task.id)
    if latest is None or latest.version != payload.base_revision_version:
        raise PlanMutationConflict("revision_conflict", "方案已更新，请刷新后重试")
    if source_plan.revision_id != latest.id:
        raise PlanMutationConflict("revision_conflict", "只能修改任务的最新方案版本")
    source_scene = source_plan.scene
    if source_scene is None:
        raise PlanMutationError("scene_not_found", "当前方案尚无可编辑场景")
    document = SceneDocument.model_validate(
        scene_service.get_current_version(db, source_scene).scene_json
    ).model_copy(deep=True)
    region = (task.confirmed_requirement_json or {}).get("delivery_region")
    budget = (task.confirmed_requirement_json or {}).get("budget_max") or task.budget_max

    source_item = None
    if payload.source_instance_id:
        source_item = next(
            (item for item in document.items if item.instance_id == payload.source_instance_id),
            None,
        )
        if source_item is None:
            raise PlanMutationError("instance_not_found", "指定家具实例不存在")
    product = (
        _require_product(db, payload.target_sku, region=region)
        if payload.target_sku
        else None
    )
    source_sku = source_item.sku if source_item else None

    if payload.action == "adopt":
        document.items.append(
            _place_new_item(db, document=document, product=product, payload=payload)
        )
    elif payload.action == "remove":
        document.items = [
            item for item in document.items if item.instance_id != source_item.instance_id
        ]
    else:
        replacement = _product_item(
            product,
            instance_id=source_item.instance_id,
            transform=source_item.transform.model_copy(deep=True),
        )
        document.items = [
            replacement if item.instance_id == source_item.instance_id else item
            for item in document.items
        ]
        if not _placement_is_valid(db, document, replacement.instance_id):
            raise PlacementNotFound(
                "placement_not_found",
                "替代商品在原位置不满足空间硬约束",
            )

    mutated_plan = deepcopy(source_plan.plan_json or {})
    _mutate_plan_items(
        mutated_plan,
        action=payload.action,
        source_sku=source_sku,
        target_sku=product.sku if product else None,
    )
    catalog_service.verify_and_enrich_plans(
        db,
        [mutated_plan],
        region=region,
        budget_max=budget,
        allow_empty_furniture=True,
    )
    errors = (mutated_plan.get("catalogValidation") or {}).get("hardErrors") or []
    if errors:
        raise PlanMutationError(errors[0], "商品变更未通过目录、地区或预算门禁")
    if any(item.get("replacedSku") for item in mutated_plan["furnitureSuggestions"]):
        raise PlanMutationError("explicit_sku_unavailable", "指定商品不可用，禁止静默替代")

    plans = []
    for plan in latest.plans:
        value = mutated_plan if plan.id == source_plan.id else deepcopy(plan.plan_json or {})
        plans.append(value)
    revision = design_version_service.persist_generation(
        db,
        task=task,
        plans=plans,
        generator="workspace_edit",
        requirement_snapshot=deepcopy(latest.requirement_snapshot or {}),
        workflow_trace=[
            {
                "node": "workspace_plan_mutation",
                "action": payload.action,
                "plan_key": source_plan.plan_key,
                "source_revision_id": latest.id,
                "source_revision_version": latest.version,
            }
        ],
    )
    revision.client_mutation_id = payload.client_mutation_id
    revision.mutation_digest = digest
    target_plan = next(item for item in revision.plans if item.plan_key == source_plan.plan_key)
    new_scene, new_version = scene_service.create_scene(
        db,
        plan_version=target_plan,
        document=document,
        source="manual",
    )
    feedback = feedback_service.create_feedback_event(
        db,
        task_id=task.id,
        payload=DesignFeedbackEventRequest(
            client_event_id=payload.client_mutation_id,
            action_type=payload.action,
            plan_version_id=target_plan.id,
            scene_id=new_scene.id,
            scene_version=new_version.version,
            room_id=payload.room_id,
            instance_id=(source_item.instance_id if source_item else None),
            source_sku=source_sku,
            target_sku=product.sku if product else None,
        ),
        commit=False,
        mutation_verified=True,
    )
    db.flush()
    return revision, deepcopy(target_plan.plan_json), new_scene, new_version, feedback
