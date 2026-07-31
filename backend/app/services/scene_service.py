"""3D 场景的归属校验、语义验证与版本持久化。"""

from math import hypot

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

    for opening in scene.openings:
        start = polygon[opening.wall_index]
        end = polygon[(opening.wall_index + 1) % len(polygon)]
        wall_length = hypot(end[0] - start[0], end[1] - start[1])
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
