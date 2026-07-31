"""3D 场景的归属校验、语义验证与版本持久化。"""

from itertools import combinations
from math import cos, hypot, sin

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AnonymousSessionTask,
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    Product,
)
from app.schemas.scenes import (
    SceneDocument,
    SceneValidationIssue,
    SceneValidationReport,
)


class SceneConflictError(ValueError):
    """场景已经存在，或客户端基于过期版本执行更新。"""


class SceneValidationError(ValueError):
    """场景通过结构校验，但未通过商品与空间语义校验。"""

    def __init__(self, report: SceneValidationReport):
        super().__init__("3D 场景语义校验失败")
        self.report = report


_NON_BLOCKING_CATEGORIES = {"地毯", "窗帘"}
_DOOR_CLEARANCE_DEPTH = 0.9


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


def _point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    epsilon: float = 1e-8,
) -> bool:
    px, pz = point
    x1, z1 = start
    x2, z2 = end
    cross = (px - x1) * (z2 - z1) - (pz - z1) * (x2 - x1)
    if abs(cross) > epsilon:
        return False
    return (
        min(x1, x2) - epsilon <= px <= max(x1, x2) + epsilon
        and min(z1, z2) - epsilon <= pz <= max(z1, z2) + epsilon
    )


def _point_in_polygon(
    point: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> bool:
    inside = False
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        if _point_on_segment(point, start, end):
            return True
        x1, z1 = start
        x2, z2 = end
        if (z1 > point[1]) != (z2 > point[1]):
            crossing_x = (x2 - x1) * (point[1] - z1) / (z2 - z1) + x1
            if point[0] < crossing_x:
                inside = not inside
    return inside


def _item_footprint(item) -> list[tuple[float, float]] | None:
    if item.dimensions is None:
        return None
    half_x = item.dimensions.x * item.transform.scale.x / 2
    half_z = item.dimensions.z * item.transform.scale.z / 2
    angle = item.transform.rotation.y
    cosine = cos(angle)
    sine = sin(angle)
    center_x = item.transform.position.x
    center_z = item.transform.position.z
    return [
        (
            center_x + local_x * cosine + local_z * sine,
            center_z - local_x * sine + local_z * cosine,
        )
        for local_x, local_z in (
            (-half_x, -half_z),
            (half_x, -half_z),
            (half_x, half_z),
            (-half_x, half_z),
        )
    ]


def _project_polygon(
    polygon: list[tuple[float, float]],
    axis: tuple[float, float],
) -> tuple[float, float]:
    values = [point[0] * axis[0] + point[1] * axis[1] for point in polygon]
    return min(values), max(values)


def _polygons_overlap(
    first: list[tuple[float, float]],
    second: list[tuple[float, float]],
    epsilon: float = 1e-6,
) -> bool:
    for polygon in (first, second):
        for start, end in zip(polygon, polygon[1:] + polygon[:1]):
            axis = (-(end[1] - start[1]), end[0] - start[0])
            first_range = _project_polygon(first, axis)
            second_range = _project_polygon(second, axis)
            if (
                first_range[1] <= second_range[0] + epsilon
                or second_range[1] <= first_range[0] + epsilon
            ):
                return False
    return True


def _vertical_ranges_overlap(first, second, epsilon: float = 1e-6) -> bool:
    if first.dimensions is None or second.dimensions is None:
        return False
    first_half = first.dimensions.y * first.transform.scale.y / 2
    second_half = second.dimensions.y * second.transform.scale.y / 2
    return (
        first.transform.position.y + first_half
        > second.transform.position.y - second_half + epsilon
        and second.transform.position.y + second_half
        > first.transform.position.y - first_half + epsilon
    )


def _door_clearance_polygon(
    polygon: list[tuple[float, float]],
    *,
    wall_index: int,
    offset: float,
    width: float,
) -> list[tuple[float, float]]:
    start = polygon[wall_index]
    end = polygon[(wall_index + 1) % len(polygon)]
    wall_length = hypot(end[0] - start[0], end[1] - start[1])
    tangent = (
        (end[0] - start[0]) / wall_length,
        (end[1] - start[1]) / wall_length,
    )
    door_center = (
        start[0] + tangent[0] * (offset + width / 2),
        start[1] + tangent[1] * (offset + width / 2),
    )
    left_normal = (-tangent[1], tangent[0])
    probe_distance = 1e-4
    left_probe = (
        door_center[0] + left_normal[0] * probe_distance,
        door_center[1] + left_normal[1] * probe_distance,
    )
    inward = (
        left_normal
        if _point_in_polygon(left_probe, polygon)
        else (-left_normal[0], -left_normal[1])
    )
    half_width = width / 2
    depth = _DOOR_CLEARANCE_DEPTH
    inner_center = (
        door_center[0] + inward[0] * depth / 2,
        door_center[1] + inward[1] * depth / 2,
    )
    return [
        (
            inner_center[0] + tangent[0] * side * half_width
            + inward[0] * direction * depth / 2,
            inner_center[1] + tangent[1] * side * half_width
            + inward[1] * direction * depth / 2,
        )
        for side, direction in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]


def validate_scene(
    db: Session,
    scene: SceneDocument,
) -> SceneValidationReport:
    errors: list[SceneValidationIssue] = []
    warnings: list[SceneValidationIssue] = []

    skus = {item.sku for item in scene.items}
    active_skus = set(
        db.scalars(
            select(Product.sku).where(
                Product.sku.in_(skus),
                Product.is_active.is_(True),
            )
        )
    ) if skus else set()
    for item in scene.items:
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
        if not _point_in_polygon((position.x, position.z), polygon):
            warnings.append(
                SceneValidationIssue(
                    code="item_outside_room",
                    message=f"家具 {item.instance_id} 的中心点位于房间外",
                    path=f"items.{item.instance_id}.transform.position",
                )
            )
        footprint = _item_footprint(item)
        if footprint and not all(
            _point_in_polygon(point, polygon) for point in footprint
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
        if item.category not in _NON_BLOCKING_CATEGORIES
        and _item_footprint(item) is not None
    ]
    for first, second in combinations(physical_items, 2):
        if not _vertical_ranges_overlap(first, second):
            continue
        first_footprint = _item_footprint(first)
        second_footprint = _item_footprint(second)
        if _polygons_overlap(first_footprint, second_footprint):
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
            clearance = _door_clearance_polygon(
                polygon,
                wall_index=opening.wall_index,
                offset=opening.offset,
                width=opening.width,
            )
            for item in physical_items:
                footprint = _item_footprint(item)
                if footprint and _polygons_overlap(clearance, footprint):
                    warnings.append(
                        SceneValidationIssue(
                            code="door_clearance_blocked",
                            message=(
                                f"家具 {item.instance_id} 占用了洞口 "
                                f"{opening.id} 内侧 {_DOOR_CLEARANCE_DEPTH:g} 米动线"
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
) -> DesignSceneVersion:
    if scene.current_version != base_version:
        raise SceneConflictError(
            f"场景已经更新到版本 {scene.current_version}，请刷新后重试"
        )

    report = validate_scene(db, document)
    if not report.valid:
        raise SceneValidationError(report)

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
