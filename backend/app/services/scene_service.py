"""3D 场景的归属校验、语义验证与版本持久化。"""

from copy import deepcopy
import hashlib
import json

from collections import Counter
from itertools import combinations
from math import hypot

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AnonymousSessionTask,
    CustomFurnitureDraftMutation,
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    DesignTask,
    Product,
)
from app.schemas.scenes import (
    CustomFurnitureSceneItemRequest,
    OpenGeometrySceneItemRequest,
    SceneDocument,
    SceneValidationIssue,
    SceneValidationReport,
    SceneItem,
    Transform,
    Vector3,
    PositiveVector3,
)
from app.schemas.custom_furniture import CustomFurnitureSpec
from app.schemas.open_geometry import OpenGeometryVersion
from app.services import open_geometry_service
from app.services.scene_geometry import (
    DOOR_CLEARANCE_DEPTH,
    NON_BLOCKING_CATEGORIES,
    door_clearance_polygon,
    item_footprint,
    point_in_polygon,
    polygons_overlap,
    vertical_ranges_overlap,
)
from app.services.scene_tools import assert_catalog_skus_eligible


_CUSTOM_SPEC_ADAPTER = TypeAdapter(CustomFurnitureSpec)


class SceneConflictError(ValueError):
    """场景已经存在，或客户端基于过期版本执行更新。"""


class SceneIdempotencyConflict(SceneConflictError):
    """同一个场景幂等键被用于不同请求。"""


class SceneValidationError(ValueError):
    """场景通过结构校验，但未通过商品与空间语义校验。"""

    def __init__(self, report: SceneValidationReport):
        super().__init__("3D 场景语义校验失败")
        self.report = report


class CustomSceneBindingError(ValueError):
    code = "custom_scene_binding_invalid"


class OpenGeometrySceneBindingError(ValueError):
    code = "open_geometry_scene_binding_invalid"


class ScenePlacementError(ValueError):
    code = "scene_hard_constraint_violation"

    def __init__(self, issues: list[SceneValidationIssue]):
        super().__init__("家具落点不满足房间空间硬约束")
        self.issues = issues


def _stable_custom_identity(
    *,
    task_id: int,
    draft_client_mutation_id: str,
    placement_client_mutation_id: str,
) -> tuple[str, str]:
    digest = hashlib.sha256(
        (
            f"{task_id}:{draft_client_mutation_id}:"
            f"{placement_client_mutation_id}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"custom-{digest}", f"CUSTOM-{digest.upper()}"


def _spec_digest(spec: dict) -> str:
    encoded = json.dumps(
        spec,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _stable_open_geometry_identity(
    *,
    task_id: int,
    open_geometry_version: int,
    placement_client_mutation_id: str,
) -> str:
    digest = hashlib.sha256(
        (
            f"{task_id}:{open_geometry_version}:"
            f"{placement_client_mutation_id}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"open-geometry-{digest}"


def _open_geometry_placement_digest(
    payload: OpenGeometrySceneItemRequest,
) -> str:
    encoded = json.dumps(
        payload.model_dump(by_alias=True, mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_item_placement(
    scene: SceneDocument,
    instance_id: str,
) -> list[SceneValidationIssue]:
    """仅校验指定物件的房间边界、碰撞、门洞净空和垂直边界。"""
    item = next(
        (candidate for candidate in scene.items if candidate.instance_id == instance_id),
        None,
    )
    if item is None or item.dimensions is None:
        raise OpenGeometrySceneBindingError("开放几何场景物件缺少可信尺寸")

    issues: list[SceneValidationIssue] = []
    polygon = [(point.x, point.z) for point in scene.room.floor_polygon]
    position = item.transform.position
    path = f"items.{item.instance_id}.transform"
    if not point_in_polygon((position.x, position.z), polygon):
        issues.append(
            SceneValidationIssue(
                code="item_outside_room",
                message=f"家具 {item.instance_id} 的中心点位于房间外",
                path=f"{path}.position",
            )
        )
    footprint = item_footprint(item)
    if footprint and not all(point_in_polygon(point, polygon) for point in footprint):
        issues.append(
            SceneValidationIssue(
                code="item_exceeds_room",
                message=f"家具 {item.instance_id} 的完整占地超出房间",
                path=path,
            )
        )

    half_height = item.dimensions.y * item.transform.scale.y / 2
    bottom = position.y - half_height
    top = position.y + half_height
    if bottom < -1e-6 or top > scene.room.ceiling_height + 1e-6:
        issues.append(
            SceneValidationIssue(
                code="item_exceeds_ceiling",
                message=f"家具 {item.instance_id} 的垂直范围超出房间",
                path=path,
            )
        )

    if item.category not in NON_BLOCKING_CATEGORIES and footprint:
        for other in scene.items:
            if (
                other.instance_id == item.instance_id
                or other.category in NON_BLOCKING_CATEGORIES
                or not vertical_ranges_overlap(item, other)
            ):
                continue
            other_footprint = item_footprint(other)
            if other_footprint and polygons_overlap(footprint, other_footprint):
                issues.append(
                    SceneValidationIssue(
                        code="item_collision",
                        message=(
                            f"家具 {item.instance_id} 与 {other.instance_id} "
                            "发生占地碰撞"
                        ),
                        path=f"items.{item.instance_id},items.{other.instance_id}",
                    )
                )

        for opening in scene.openings:
            if opening.type not in {"door", "passage"}:
                continue
            clearance = door_clearance_polygon(
                polygon,
                wall_index=opening.wall_index,
                offset=opening.offset,
                width=opening.width,
            )
            if polygons_overlap(clearance, footprint):
                issues.append(
                    SceneValidationIssue(
                        code="door_clearance_blocked",
                        message=(
                            f"家具 {item.instance_id} 占用了洞口 {opening.id} "
                            f"内侧 {DOOR_CLEARANCE_DEPTH:g} 米动线"
                        ),
                        path=path,
                    )
                )
    return issues


def add_custom_furniture_draft_to_scene(
    db: Session,
    *,
    scene: DesignScene,
    payload: CustomFurnitureSceneItemRequest,
) -> tuple[DesignSceneVersion, bool]:
    """把属于同一任务的已保存草稿作为参数化预览写入场景快照。"""
    task_id = get_scene_task_id(db, scene.id)
    if task_id is None:
        raise CustomSceneBindingError("场景缺少所属任务")
    replayed = db.scalar(
        select(DesignSceneVersion).where(
            DesignSceneVersion.scene_id == scene.id,
            DesignSceneVersion.client_mutation_id == payload.client_mutation_id,
        )
    )
    if replayed is not None:
        replayed_document = SceneDocument.model_validate(replayed.scene_json)
        expected_instance_id, _ = _stable_custom_identity(
            task_id=task_id,
            draft_client_mutation_id=payload.draft_client_mutation_id,
            placement_client_mutation_id=payload.client_mutation_id,
        )
        item = next(
            (
                candidate
                for candidate in replayed_document.items
                if candidate.instance_id == expected_instance_id
            ),
            None,
        )
        if (
            item is None
            or item.custom_furniture_ref is None
            or item.custom_furniture_ref.draft_client_mutation_id
            != payload.draft_client_mutation_id
            or item.transform.position.x != payload.position.x
            or item.transform.position.z != payload.position.z
            or item.transform.rotation.y != payload.rotation_y
        ):
            raise SceneConflictError("client_mutation_id 已用于不同场景变更")
        return replayed, False
    draft = db.scalar(
        select(CustomFurnitureDraftMutation).where(
            CustomFurnitureDraftMutation.task_id == task_id,
            CustomFurnitureDraftMutation.client_mutation_id
            == payload.draft_client_mutation_id,
        )
    )
    if draft is None:
        raise CustomSceneBindingError("定制家具草稿不存在或不属于当前任务")
    response = draft.response_json if isinstance(draft.response_json, dict) else {}
    raw_spec = response.get("custom_furniture_spec")
    state_version = response.get("state_version")
    if not isinstance(raw_spec, dict) or not isinstance(state_version, int):
        raise CustomSceneBindingError("定制家具草稿快照不完整")
    try:
        spec = _CUSTOM_SPEC_ADAPTER.validate_python(raw_spec)
    except ValidationError as error:
        raise CustomSceneBindingError("定制家具草稿规格无效") from error
    current = get_current_version(db, scene)
    document = SceneDocument.model_validate(current.scene_json).model_copy(deep=True)
    instance_id, synthetic_sku = _stable_custom_identity(
        task_id=task_id,
        draft_client_mutation_id=payload.draft_client_mutation_id,
        placement_client_mutation_id=payload.client_mutation_id,
    )
    dimensions = spec.dimensions
    document.items.append(
        SceneItem(
            instance_id=instance_id,
            sku=synthetic_sku,
            category="定制柜" if spec.family == "cabinet" else "定制桌",
            dimensions=PositiveVector3(
                x=dimensions.width_mm / 1000,
                y=dimensions.height_mm / 1000,
                z=dimensions.depth_mm / 1000,
            ),
            transform=Transform(
                position=Vector3(
                    x=payload.position.x,
                    y=dimensions.height_mm / 2000,
                    z=payload.position.z,
                ),
                rotation=Vector3(x=0, y=payload.rotation_y, z=0),
            ),
            asset_mode="parametric",
            source_type="custom_furniture_draft",
            custom_furniture_ref={
                "taskId": task_id,
                "planVersionId": scene.plan_version_id,
                "introducedSceneVersion": payload.base_version + 1,
                "draftClientMutationId": payload.draft_client_mutation_id,
                "draftStateVersion": state_version,
                "specDigest": _spec_digest(raw_spec),
            },
        )
    )
    return update_scene_idempotent(
        db,
        scene=scene,
        base_version=payload.base_version,
        document=document,
        source="manual",
        client_mutation_id=payload.client_mutation_id,
        mutation_metadata={
            "custom_draft_client_mutation_id": payload.draft_client_mutation_id,
        },
        allow_new_custom=True,
    )


def _add_open_geometry_version_to_scene(
    db: Session,
    *,
    task: DesignTask,
    scene: DesignScene,
    payload: OpenGeometrySceneItemRequest,
    current: OpenGeometryVersion | None,
) -> tuple[DesignSceneVersion, bool]:
    """冻结当前开放几何版本，并以米制占地加入所属房间。"""
    task_id = get_scene_task_id(db, scene.id)
    if task_id != task.id:
        raise OpenGeometrySceneBindingError("开放几何家具与场景不属于同一任务")

    request_digest = _open_geometry_placement_digest(payload)
    replayed = db.scalar(
        select(DesignSceneVersion).where(
            DesignSceneVersion.scene_id == scene.id,
            DesignSceneVersion.client_mutation_id == payload.client_mutation_id,
        )
    )
    if replayed is not None:
        if replayed.mutation_digest != request_digest:
            raise SceneIdempotencyConflict("client_mutation_id 已用于不同场景变更")
        return replayed, False

    if scene.current_version != payload.base_version:
        raise SceneConflictError(
            f"场景已经更新到版本 {scene.current_version}，请刷新后重试"
        )
    if (
        current is None
        or current.version != payload.open_geometry_version
    ):
        raise OpenGeometrySceneBindingError("只能把当前开放几何版本加入房间")

    model_spec = deepcopy(current.model_spec)
    rule = model_spec.get("确定性建模规则")
    dimensions_mm = rule.get("包围尺寸_mm") if isinstance(rule, dict) else None
    model_id = rule.get("模型ID") if isinstance(rule, dict) else None
    if not isinstance(dimensions_mm, dict) or not isinstance(model_id, str):
        raise OpenGeometrySceneBindingError("开放几何模型快照缺少编译尺寸或模型 ID")
    try:
        dimensions = PositiveVector3(
            x=float(dimensions_mm["宽"]) / 1000,
            y=float(dimensions_mm["高"]) / 1000,
            z=float(dimensions_mm["深"]) / 1000,
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise OpenGeometrySceneBindingError("开放几何模型快照尺寸无效") from exc

    current_scene = get_current_version(db, scene)
    document = SceneDocument.model_validate(current_scene.scene_json).model_copy(deep=True)
    document.schema_version = "1.1"
    instance_id = _stable_open_geometry_identity(
        task_id=task.id,
        open_geometry_version=current.version,
        placement_client_mutation_id=payload.client_mutation_id,
    )
    document.items.append(
        SceneItem(
            instance_id=instance_id,
            sku=model_id,
            category="开放几何家具",
            dimensions=dimensions,
            transform=Transform(
                position=Vector3(
                    x=payload.position.x,
                    y=dimensions.y / 2,
                    z=payload.position.z,
                ),
                rotation=Vector3(x=0, y=payload.rotation_y, z=0),
            ),
            asset_mode="parametric",
            source_type="open_geometry_draft",
            open_geometry_ref={
                "taskId": task.id,
                "planVersionId": scene.plan_version_id,
                "introducedSceneVersion": payload.base_version + 1,
                "openGeometryVersion": current.version,
                "modelId": model_id,
                "specDigest": _spec_digest(model_spec),
            },
            open_geometry_model_spec=model_spec,
        )
    )
    placement_issues = validate_item_placement(document, instance_id)
    if placement_issues:
        raise ScenePlacementError(placement_issues)
    return update_scene_idempotent(
        db,
        scene=scene,
        base_version=payload.base_version,
        document=document,
        source="manual",
        client_mutation_id=payload.client_mutation_id,
        mutation_metadata={
            "open_geometry_version": payload.open_geometry_version,
        },
        allow_new_open_geometry=True,
        mutation_digest=request_digest,
    )


def add_open_geometry_to_scene(
    db: Session,
    *,
    task: DesignTask,
    scene: DesignScene,
    payload: OpenGeometrySceneItemRequest,
) -> tuple[DesignSceneVersion, bool]:
    """冻结任务当前开放几何版本，并加入所属房间。"""
    task_id = get_scene_task_id(db, scene.id)
    if task_id != task.id:
        raise OpenGeometrySceneBindingError("开放几何家具与场景不属于同一任务")
    request_digest = _open_geometry_placement_digest(payload)
    replayed = db.scalar(
        select(DesignSceneVersion).where(
            DesignSceneVersion.scene_id == scene.id,
            DesignSceneVersion.client_mutation_id == payload.client_mutation_id,
        )
    )
    if replayed is not None:
        if replayed.mutation_digest != request_digest:
            raise SceneIdempotencyConflict("client_mutation_id 已用于不同场景变更")
        return replayed, False
    try:
        state = open_geometry_service.get_state(task)
    except open_geometry_service.OpenGeometryError as exc:
        raise OpenGeometrySceneBindingError("开放几何当前状态无效") from exc
    return _add_open_geometry_version_to_scene(
        db,
        task=task,
        scene=scene,
        payload=payload,
        current=state.current,
    )


def add_staged_open_geometry_to_scene(
    db: Session,
    *,
    task: DesignTask,
    scene: DesignScene,
    payload: OpenGeometrySceneItemRequest,
    current: OpenGeometryVersion,
) -> tuple[DesignSceneVersion, bool]:
    """把同一事务中尚未提交的已验证几何版本冻结进场景。"""
    return _add_open_geometry_version_to_scene(
        db,
        task=task,
        scene=scene,
        payload=payload,
        current=current,
    )


def _delivery_region_for_plan(db: Session, plan_version_id: int) -> str | None:
    task = db.scalar(
        select(DesignTask)
        .join(DesignRevision, DesignRevision.task_id == DesignTask.id)
        .join(DesignPlanVersion, DesignPlanVersion.revision_id == DesignRevision.id)
        .where(DesignPlanVersion.id == plan_version_id)
    )
    requirement = task.confirmed_requirement_json if task is not None else None
    if not isinstance(requirement, dict):
        return None
    value = requirement.get("delivery_region")
    return value.strip() if isinstance(value, str) and value.strip() else None


def scene_delivery_region(db: Session, scene: DesignScene) -> str | None:
    return _delivery_region_for_plan(db, scene.plan_version_id)


def assert_scene_catalog_mutation(
    db: Session,
    *,
    before: SceneDocument | None,
    after: SceneDocument,
    region: str | None = None,
) -> None:
    """仅校验本次新引入的实例/SKU，历史失效实例仍可移动、删除和回放。"""
    prior = Counter(
        (item.instance_id, item.sku)
        for item in (before.items if before else [])
        if item.source_type == "catalog"
    )
    introduced: list[str] = []
    for item in after.items:
        if item.source_type != "catalog":
            continue
        identity = (item.instance_id, item.sku)
        if prior[identity]:
            prior[identity] -= 1
        else:
            introduced.append(item.sku)
    assert_catalog_skus_eligible(db, introduced, region=region)


def assert_scene_catalog_deliverable(
    db: Session,
    scene: SceneDocument,
    *,
    region: str | None = None,
) -> None:
    assert_catalog_skus_eligible(
        db,
        [item.sku for item in scene.items if item.source_type == "catalog"],
        region=region,
    )


def assert_custom_scene_bindings(
    *,
    before: SceneDocument | None,
    after: SceneDocument,
    allow_new_custom: bool = False,
    historical_custom_items: list[SceneItem] | None = None,
) -> None:
    prior = {
        item.instance_id: item
        for item in (before.items if before else [])
        if item.source_type == "custom_furniture_draft"
    }
    historical = {
        item.instance_id: item for item in (historical_custom_items or [])
    }
    for item in after.items:
        if item.source_type != "custom_furniture_draft":
            continue
        existing = prior.get(item.instance_id)
        if existing is None:
            if allow_new_custom:
                continue
            existing = historical.get(item.instance_id)
            if existing is None:
                raise CustomSceneBindingError(
                    "定制家具只能通过已保存草稿或可信场景历史加入"
                )
        immutable_before = existing.model_dump(exclude={"transform"})
        immutable_after = item.model_dump(exclude={"transform"})
        if immutable_before != immutable_after:
            raise CustomSceneBindingError("定制家具草稿引用、尺寸和材质不可在场景中伪造")


def assert_open_geometry_scene_bindings(
    *,
    before: SceneDocument | None,
    after: SceneDocument,
    allow_new_open_geometry: bool = False,
    historical_open_geometry_items: list[SceneItem] | None = None,
) -> None:
    prior = {
        item.instance_id: item
        for item in (before.items if before else [])
        if item.source_type == "open_geometry_draft"
    }
    historical = {
        item.instance_id: item for item in (historical_open_geometry_items or [])
    }
    for item in after.items:
        if item.source_type != "open_geometry_draft":
            continue
        existing = prior.get(item.instance_id)
        if existing is None:
            if allow_new_open_geometry:
                continue
            existing = historical.get(item.instance_id)
            if existing is None:
                raise OpenGeometrySceneBindingError(
                    "开放几何家具只能通过当前可信版本或可信场景历史加入"
                )
        immutable_before = existing.model_dump(exclude={"transform"})
        immutable_after = item.model_dump(exclude={"transform"})
        if immutable_before != immutable_after:
            raise OpenGeometrySceneBindingError(
                "开放几何家具引用、尺寸、材质和模型快照不可在场景中伪造"
            )
        if item.dimensions is None:
            raise OpenGeometrySceneBindingError("开放几何家具缺少可信尺寸")
        transform = item.transform
        expected_y = item.dimensions.y / 2
        if (
            abs(transform.position.y - expected_y) > 1e-6
            or abs(transform.rotation.x) > 1e-6
            or abs(transform.rotation.z) > 1e-6
            or any(
                abs(value - 1) > 1e-6
                for value in (
                    transform.scale.x,
                    transform.scale.y,
                    transform.scale.z,
                )
            )
        ):
            raise OpenGeometrySceneBindingError(
                "开放几何家具在房间中只允许平面移动和绕 Y 轴旋转"
            )


def _load_reintroduced_custom_items(
    db: Session,
    *,
    scene_id: int,
    before: SceneDocument,
    after: SceneDocument,
) -> list[SceneItem]:
    current_ids = {item.instance_id for item in before.items}
    introduced_versions = {
        item.custom_furniture_ref.introduced_scene_version
        for item in after.items
        if item.source_type == "custom_furniture_draft"
        and item.instance_id not in current_ids
        and item.custom_furniture_ref is not None
    }
    if not introduced_versions:
        return []
    versions = db.scalars(
        select(DesignSceneVersion).where(
            DesignSceneVersion.scene_id == scene_id,
            DesignSceneVersion.version.in_(introduced_versions),
        )
    ).all()
    return [
        item
        for version in versions
        for item in SceneDocument.model_validate(version.scene_json).items
        if item.source_type == "custom_furniture_draft"
    ]


def _load_reintroduced_open_geometry_items(
    db: Session,
    *,
    scene_id: int,
    before: SceneDocument,
    after: SceneDocument,
) -> list[SceneItem]:
    current_ids = {item.instance_id for item in before.items}
    introduced_versions = {
        item.open_geometry_ref.introduced_scene_version
        for item in after.items
        if item.source_type == "open_geometry_draft"
        and item.instance_id not in current_ids
        and item.open_geometry_ref is not None
    }
    if not introduced_versions:
        return []
    versions = db.scalars(
        select(DesignSceneVersion).where(
            DesignSceneVersion.scene_id == scene_id,
            DesignSceneVersion.version.in_(introduced_versions),
        )
    ).all()
    return [
        item
        for version in versions
        for item in SceneDocument.model_validate(version.scene_json).items
        if item.source_type == "open_geometry_draft"
    ]


def get_owned_plan_version(
    db: Session,
    *,
    session_id: str,
    plan_version_id: int,
) -> DesignPlanVersion | None:
    return db.scalars(
        select(DesignPlanVersion)
        .join(
            DesignRevision,
            DesignRevision.id == DesignPlanVersion.revision_id,
        )
        .join(
            AnonymousSessionTask,
            AnonymousSessionTask.task_id == DesignRevision.task_id,
        )
        .where(
            DesignPlanVersion.id == plan_version_id,
            AnonymousSessionTask.session_id == session_id,
        )
    ).first()


def get_owned_scene(
    db: Session,
    *,
    session_id: str,
    scene_id: int,
    for_update: bool = False,
) -> DesignScene | None:
    statement = (
        select(DesignScene)
        .join(
            DesignPlanVersion,
            DesignPlanVersion.id == DesignScene.plan_version_id,
        )
        .join(
            DesignRevision,
            DesignRevision.id == DesignPlanVersion.revision_id,
        )
        .join(
            AnonymousSessionTask,
            AnonymousSessionTask.task_id == DesignRevision.task_id,
        )
        .where(
            DesignScene.id == scene_id,
            AnonymousSessionTask.session_id == session_id,
        )
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalars(statement).first()


def get_scene_by_plan_version(
    db: Session,
    plan_version_id: int,
) -> DesignScene | None:
    return db.scalar(
        select(DesignScene).where(
            DesignScene.plan_version_id == plan_version_id
        )
    )


def validate_scene(
    db: Session,
    scene: SceneDocument,
) -> SceneValidationReport:
    errors: list[SceneValidationIssue] = []
    warnings: list[SceneValidationIssue] = []

    skus = {item.sku for item in scene.items if item.source_type == "catalog"}
    active_skus = set(
        db.scalars(
            select(Product.sku).where(
                Product.sku.in_(skus),
                Product.is_active.is_(True),
            )
        )
    ) if skus else set()
    for item in scene.items:
        if item.source_type != "catalog":
            continue
        if item.sku not in active_skus:
            errors.append(
                SceneValidationIssue(
                    code="unknown_sku",
                    message=f"商品库中不存在可用 SKU：{item.sku}",
                    path=f"items.{item.instance_id}.sku",
                )
            )

    polygon = [(point.x, point.z) for point in scene.room.floor_polygon]
    for item in scene.items:
        position = item.transform.position
        if not point_in_polygon((position.x, position.z), polygon):
            warnings.append(
                SceneValidationIssue(
                    code="item_outside_room",
                    message=f"家具 {item.instance_id} 的中心点位于房间外",
                    path=f"items.{item.instance_id}.transform.position",
                )
            )
        footprint = item_footprint(item)
        if footprint and not all(
            point_in_polygon(point, polygon) for point in footprint
        ):
            warnings.append(
                SceneValidationIssue(
                    code="item_exceeds_room",
                    message=f"家具 {item.instance_id} 的完整占地超出房间",
                    path=f"items.{item.instance_id}.transform",
                )
            )

    physical_items = [
        item
        for item in scene.items
        if item.category not in NON_BLOCKING_CATEGORIES
        and item_footprint(item) is not None
    ]
    for first, second in combinations(physical_items, 2):
        if not vertical_ranges_overlap(first, second):
            continue
        first_footprint = item_footprint(first)
        second_footprint = item_footprint(second)
        if polygons_overlap(first_footprint, second_footprint):
            warnings.append(
                SceneValidationIssue(
                    code="item_collision",
                    message=(
                        f"家具 {first.instance_id} 与 {second.instance_id} "
                        "发生占地碰撞"
                    ),
                    path=f"items.{first.instance_id},items.{second.instance_id}",
                )
            )

    for opening in scene.openings:
        start = polygon[opening.wall_index]
        end = polygon[(opening.wall_index + 1) % len(polygon)]
        wall_length = hypot(end[0] - start[0], end[1] - start[1])
        if wall_length <= 1e-8:
            errors.append(
                SceneValidationIssue(
                    code="invalid_wall_length",
                    message=f"洞口 {opening.id} 所在墙体长度无效",
                    path=f"openings.{opening.id}.wallIndex",
                )
            )
            continue
        if opening.offset + opening.width > wall_length + 1e-6:
            errors.append(
                SceneValidationIssue(
                    code="opening_exceeds_wall",
                    message=f"洞口 {opening.id} 超出所在墙体长度",
                    path=f"openings.{opening.id}",
                )
            )
        if opening.sill_height + opening.height > scene.room.ceiling_height:
            errors.append(
                SceneValidationIssue(
                    code="opening_exceeds_ceiling",
                    message=f"洞口 {opening.id} 超出房间层高",
                    path=f"openings.{opening.id}",
                )
            )
        if opening.type in {"door", "passage"}:
            clearance = door_clearance_polygon(
                polygon,
                wall_index=opening.wall_index,
                offset=opening.offset,
                width=opening.width,
            )
            for item in physical_items:
                footprint = item_footprint(item)
                if footprint and polygons_overlap(clearance, footprint):
                    warnings.append(
                        SceneValidationIssue(
                            code="door_clearance_blocked",
                            message=(
                                f"家具 {item.instance_id} 占用了洞口 "
                                f"{opening.id} 内侧 {DOOR_CLEARANCE_DEPTH:g} 米动线"
                            ),
                            path=f"items.{item.instance_id}.transform",
                        )
                    )

    return SceneValidationReport(
        valid=not errors,
        errors=errors,
        warnings=warnings,
    )


def _scene_json(scene: SceneDocument) -> dict:
    return scene.model_dump(by_alias=True, mode="json")


def create_scene(
    db: Session,
    *,
    plan_version: DesignPlanVersion,
    document: SceneDocument,
    source: str,
) -> tuple[DesignScene, DesignSceneVersion]:
    existing = db.scalar(
        select(DesignScene).where(
            DesignScene.plan_version_id == plan_version.id
        )
    )
    if existing:
        raise SceneConflictError("该方案已经创建 3D 场景")

    report = validate_scene(db, document)
    if not report.valid:
        raise SceneValidationError(report)
    assert_custom_scene_bindings(before=None, after=document)
    assert_open_geometry_scene_bindings(before=None, after=document)
    assert_scene_catalog_mutation(
        db,
        before=None,
        after=document,
        region=_delivery_region_for_plan(db, plan_version.id),
    )

    scene = DesignScene(
        plan_version_id=plan_version.id,
        current_version=1,
    )
    db.add(scene)
    db.flush()
    version = DesignSceneVersion(
        scene_id=scene.id,
        version=1,
        scene_json=_scene_json(document),
        validation_json=report.model_dump(mode="json"),
        source=source,
    )
    db.add(version)
    db.flush()
    return scene, version


def update_scene(
    db: Session,
    *,
    scene: DesignScene,
    base_version: int,
    document: SceneDocument,
    source: str,
    allow_new_custom: bool = False,
    allow_new_open_geometry: bool = False,
) -> DesignSceneVersion:
    if scene.current_version != base_version:
        raise SceneConflictError(
            f"场景已经更新到版本 {scene.current_version}，请刷新后重试"
        )

    report = validate_scene(db, document)
    if not report.valid:
        raise SceneValidationError(report)
    current = get_current_version(db, scene)
    current_document = SceneDocument.model_validate(current.scene_json)
    historical_custom_items = _load_reintroduced_custom_items(
        db,
        scene_id=scene.id,
        before=current_document,
        after=document,
    )
    historical_open_geometry_items = _load_reintroduced_open_geometry_items(
        db,
        scene_id=scene.id,
        before=current_document,
        after=document,
    )
    assert_custom_scene_bindings(
        before=current_document,
        after=document,
        allow_new_custom=allow_new_custom,
        historical_custom_items=historical_custom_items,
    )
    assert_open_geometry_scene_bindings(
        before=current_document,
        after=document,
        allow_new_open_geometry=allow_new_open_geometry,
        historical_open_geometry_items=historical_open_geometry_items,
    )
    assert_scene_catalog_mutation(
        db,
        before=current_document,
        after=document,
        region=scene_delivery_region(db, scene),
    )

    next_version = scene.current_version + 1
    version = DesignSceneVersion(
        scene_id=scene.id,
        version=next_version,
        scene_json=_scene_json(document),
        validation_json=report.model_dump(mode="json"),
        source=source,
    )
    scene.current_version = next_version
    db.add(version)
    db.flush()
    return version


def update_scene_idempotent(
    db: Session,
    *,
    scene: DesignScene,
    base_version: int,
    document: SceneDocument,
    source: str,
    client_mutation_id: str,
    mutation_metadata: dict,
    allow_new_custom: bool = False,
    allow_new_open_geometry: bool = False,
    mutation_digest: str | None = None,
) -> tuple[DesignSceneVersion, bool]:
    encoded = json.dumps(
        {
            "base_version": base_version,
            "scene": _scene_json(document),
            "source": source,
            **mutation_metadata,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = mutation_digest or hashlib.sha256(encoded).hexdigest()
    existing = db.scalar(
        select(DesignSceneVersion).where(
            DesignSceneVersion.scene_id == scene.id,
            DesignSceneVersion.client_mutation_id == client_mutation_id,
        )
    )
    if existing is not None:
        if existing.mutation_digest != digest:
            raise SceneConflictError("client_mutation_id 已用于不同场景变更")
        return existing, False
    version = update_scene(
        db,
        scene=scene,
        base_version=base_version,
        document=document,
        source=source,
        allow_new_custom=allow_new_custom,
        allow_new_open_geometry=allow_new_open_geometry,
    )
    version.client_mutation_id = client_mutation_id
    version.mutation_digest = digest
    db.flush()
    return version, True


def get_scene_task_id(db: Session, scene_id: int) -> int | None:
    return db.scalar(
        select(DesignRevision.task_id)
        .join(DesignPlanVersion, DesignPlanVersion.revision_id == DesignRevision.id)
        .join(DesignScene, DesignScene.plan_version_id == DesignPlanVersion.id)
        .where(DesignScene.id == scene_id)
    )


def get_current_version(
    db: Session,
    scene: DesignScene,
) -> DesignSceneVersion:
    version = db.scalar(
        select(DesignSceneVersion).where(
            DesignSceneVersion.scene_id == scene.id,
            DesignSceneVersion.version == scene.current_version,
        )
    )
    if version is None:
        raise RuntimeError("场景当前版本快照不存在")
    return version


def list_versions(
    db: Session,
    scene_id: int,
) -> list[DesignSceneVersion]:
    return list(
        db.scalars(
            select(DesignSceneVersion)
            .where(DesignSceneVersion.scene_id == scene_id)
            .order_by(DesignSceneVersion.version.desc())
        )
    )
