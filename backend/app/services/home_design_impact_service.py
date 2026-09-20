"""只读比较精确空间历史；候选仅替换空间版本，不修补用户设计。"""

from sqlalchemy import select

from app.db.models import DesignSpaceVersion
from app.schemas.home_design_impact import (
    ReferenceIssue,
    SpaceChange,
    SpaceImpactResponse,
)
from app.schemas.spatial import SpatialDocument
from app.services.home_design_asset_service import validate_bindings
from app.services.home_design_validation import validate_design


def _space(db, task_id, version):
    row = db.scalar(
        select(DesignSpaceVersion).where(
            DesignSpaceVersion.task_id == task_id,
            DesignSpaceVersion.version == version,
        )
    )
    if row is None:
        raise LookupError("空间版本不存在或不属于当前任务")
    if not row.document_json.get("rooms"):
        raise ValueError("空间版本必须包含房间")
    return SpatialDocument.model_validate(row.document_json)


def compare_spaces(source, target):
    changes = []
    for field, kind in (("rooms", "room"), ("walls", "wall"), ("openings", "opening")):
        before = {item.id: item for item in getattr(source, field)}
        after = {item.id: item for item in getattr(target, field)}
        for entity_id in sorted(before.keys() | after.keys()):
            if entity_id not in before:
                change = "added"
            elif entity_id not in after:
                change = "removed"
            elif before[entity_id] != after[entity_id]:
                change = "modified"
            else:
                continue
            changes.append(
                SpaceChange(entity_type=kind, entity_id=entity_id, change=change)
            )
    for field in SpatialDocument.model_fields:
        if field not in {"rooms", "walls", "openings"} and getattr(
            source, field
        ) != getattr(target, field):
            changes.append(
                SpaceChange(entity_type="space", entity_id=field, change="modified")
            )
    return changes


def reference_issues(document, space):
    rooms = {room.id for room in space.rooms}
    walls = {wall.id: wall for wall in space.walls}
    points = {point.id: point for point in document.points}
    issues = []
    for item in document.objects:
        if item.point_requirement is None:
            continue
        point = points.get(item.point_requirement.point_id)
        if point is None or point.room_id != item.room_id:
            issues.append(ReferenceIssue(
                entity_type="object", entity_id=item.id,
                code="point_missing" if point is None else "point_room_mismatch",
                message="关联点位不存在或不属于物件房间，请重新关联或解除关联",
            ))
    for kind, items in (
        ("object", document.objects),
        ("surface", document.surfaces),
        ("point", document.points),
    ):
        for item in items:
            if item.room_id not in rooms:
                issues.append(
                    ReferenceIssue(
                        entity_type=kind,
                        entity_id=item.id,
                        code="room_missing",
                        message="目标空间中不存在引用的房间，请重新指定房间",
                    )
                )
            wall_id = (
                item.wall_id
                if kind == "surface"
                else (
                    item.installation.wall_id
                    if kind == "object" and item.installation
                    else None
                )
            )
            if wall_id is None:
                continue
            wall = walls.get(wall_id)
            if wall is None:
                issues.append(
                    ReferenceIssue(
                        entity_type=kind,
                        entity_id=item.id,
                        code="wall_missing",
                        message="目标空间中不存在引用的墙体，请重新指定墙体",
                    )
                )
            elif item.room_id not in wall.room_ids:
                issues.append(
                    ReferenceIssue(
                        entity_type=kind,
                        entity_id=item.id,
                        code="wall_room_mismatch",
                        message="目标墙体不属于指定房间，请重新指定关系",
                    )
                )
    return issues


def preview_impact(db, task_id, payload):
    if payload.document.space_version == payload.target_space_version:
        raise ValueError("请选择不同的目标空间版本")
    # 关闭自动 flush，影响预览自身不产生数据库写入，也不取得写锁。
    with db.no_autoflush:
        source = _space(db, task_id, payload.document.space_version)
        target = _space(db, task_id, payload.target_space_version)
        if target.scale_status != "confirmed":
            raise ValueError("目标空间尺度尚未确认")
        validate_bindings(db, task_id, payload.document)
        candidate = payload.document.model_copy(
            deep=True, update={"space_version": payload.target_space_version}
        )
        issues = reference_issues(candidate, target)
        return SpaceImpactResponse(
            task_id=task_id,
            source_space_version=payload.document.space_version,
            target_space_version=payload.target_space_version,
            target_space=target,
            candidate_document=candidate,
            changes=compare_spaces(source, target),
            reference_issues=issues,
            validation=None if issues else validate_design(candidate, target),
            can_apply=not issues,
        )
