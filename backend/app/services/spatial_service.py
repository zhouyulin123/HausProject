"""整屋事实的原子追加、重放与版本冲突。"""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DesignSpace, DesignSpaceVersion, UploadedImage
from app.schemas.spatial import SpatialResponse, SpatialSaveRequest
from app.services.aggregate_lock_service import lock_owned_task


class SpatialConflict(ValueError):
    def __init__(self, code: str, current_version: int):
        super().__init__(code)
        self.code = code
        self.current_version = current_version


class SpatialSourceError(ValueError):
    pass


def _response(version: DesignSpaceVersion) -> SpatialResponse:
    return SpatialResponse(
        task_id=version.task_id, version=version.version, document=version.document_json
    )


def get_space(db: Session, task_id: int) -> SpatialResponse:
    # 单条查询避免在并发保存时读到不匹配的指针和历史版本。
    version = db.scalar(
        select(DesignSpaceVersion)
        .join(
            DesignSpace,
            (DesignSpace.task_id == DesignSpaceVersion.task_id)
            & (DesignSpace.current_version == DesignSpaceVersion.version),
        )
        .where(DesignSpace.task_id == task_id)
    )
    return (
        _response(version)
        if version
        else SpatialResponse(task_id=task_id, version=0, document=None)
    )


def get_version(db: Session, task_id: int, version: int) -> SpatialResponse:
    record = db.scalar(
        select(DesignSpaceVersion).where(
            DesignSpaceVersion.task_id == task_id,
            DesignSpaceVersion.version == version,
        )
    )
    if record is None:
        raise LookupError("空间版本不存在")
    return _response(record)


def list_versions(db: Session, task_id: int, before_version: int | None, limit: int):
    query = select(DesignSpaceVersion).where(DesignSpaceVersion.task_id == task_id)
    if before_version is not None:
        query = query.where(DesignSpaceVersion.version < before_version)
    records = db.scalars(
        query.order_by(DesignSpaceVersion.version.desc()).limit(limit + 1)
    ).all()
    return {
        "task_id": task_id,
        "versions": [
            {
                "version": row.version,
                "created_at": row.created_at,
                "room_count": len(row.document_json["rooms"]),
                "scale_status": row.document_json["scale_status"],
            }
            for row in records[:limit]
        ],
        "next_before_version": records[limit - 1].version
        if len(records) > limit
        else None,
    }


def save_space(
    db: Session, *, task_id: int, session_id: str, payload: SpatialSaveRequest
) -> SpatialResponse:
    if lock_owned_task(db, session_id=session_id, task_id=task_id) is None:
        raise LookupError("设计任务不存在或不属于当前会话")
    digest = hashlib.sha256(
        json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    # MySQL 默认 REPEATABLE READ：归属预检可能已经建立旧快照，锁后必须使用当前读。
    current = db.scalar(
        select(DesignSpace)
        .where(DesignSpace.task_id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    version_number = current.current_version if current else 0
    replay = db.scalar(
        select(DesignSpaceVersion)
        .where(
            DesignSpaceVersion.task_id == task_id,
            DesignSpaceVersion.client_mutation_id == payload.client_mutation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if replay:
        if replay.mutation_digest != digest:
            raise SpatialConflict("spatial_idempotency_conflict", version_number)
        result = _response(replay)
        db.commit()
        return result
    if payload.base_version != version_number:
        raise SpatialConflict("spatial_version_conflict", version_number)
    source_id = payload.document.source_image_id
    if (
        source_id is not None
        and db.scalar(
            select(UploadedImage.id)
            .where(
                UploadedImage.id == source_id,
                UploadedImage.task_id == task_id,
            )
            .with_for_update()
        )
        is None
    ):
        raise SpatialSourceError("空间原图不存在或不属于当前任务")
    if current is None:
        current = DesignSpace(task_id=task_id, current_version=1)
        db.add(current)
        db.flush()
    else:
        current.current_version = version_number + 1
    version = DesignSpaceVersion(
        task_id=task_id,
        version=version_number + 1,
        document_json=payload.document.model_dump(mode="json"),
        client_mutation_id=payload.client_mutation_id,
        mutation_digest=digest,
    )
    db.add(version)
    db.flush()
    result = _response(version)
    db.commit()
    return result
