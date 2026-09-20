"""家装版本持久化，锁顺序与空间聚合一致。"""

import hashlib
import json

from sqlalchemy import select

from app.db.models import HomeDesign, HomeDesignVersion, DesignSpaceVersion
from app.schemas.home_design import HomeDesignResponse
from app.schemas.spatial import SpatialDocument
from app.services.aggregate_lock_service import lock_owned_task
from app.services.home_design_validation import validate_design
from app.services.spatial_service import SpatialConflict
from app.services.home_design_asset_service import validate_bindings


def _response(row):
    return HomeDesignResponse(
        task_id=row.task_id,
        version=row.version,
        document=row.document_json,
        validation=row.validation_json,
    )


def get_design(db, task_id):
    row = db.scalar(
        select(HomeDesignVersion)
        .join(
            HomeDesign,
            (HomeDesign.task_id == HomeDesignVersion.task_id)
            & (HomeDesign.current_version == HomeDesignVersion.version),
        )
        .where(HomeDesign.task_id == task_id)
    )
    return (
        _response(row)
        if row
        else HomeDesignResponse(task_id=task_id, version=0, document=None)
    )


def get_version(db, task_id, version):
    row = db.scalar(
        select(HomeDesignVersion).where(
            HomeDesignVersion.task_id == task_id, HomeDesignVersion.version == version
        )
    )
    if row is None:
        raise LookupError("家装版本不存在")
    return _response(row)


def list_versions(db, task_id, before_version, limit):
    query = select(HomeDesignVersion).where(HomeDesignVersion.task_id == task_id)
    if before_version is not None:
        query = query.where(HomeDesignVersion.version < before_version)
    rows = db.scalars(
        query.order_by(HomeDesignVersion.version.desc()).limit(limit + 1)
    ).all()
    return {
        "task_id": task_id,
        "versions": [
            {
                "version": r.version,
                "created_at": r.created_at,
                "space_version": r.document_json["space_version"],
                "object_count": len(r.document_json["objects"]),
                "valid": r.validation_json["valid"],
            }
            for r in rows[:limit]
        ],
        "next_before_version": rows[limit - 1].version if len(rows) > limit else None,
    }


def validate_document(db, task_id, document):
    validate_bindings(db, task_id, document)
    space = db.scalar(
        select(DesignSpaceVersion)
        .where(
            DesignSpaceVersion.task_id == task_id,
            DesignSpaceVersion.version == document.space_version,
        )
        .with_for_update()
    )
    if space is None:
        raise ValueError("绑定的空间版本不存在或不属于当前任务")
    return validate_design(
        document, SpatialDocument.model_validate(space.document_json)
    )


def save_design(db, *, task_id, session_id, payload):
    if lock_owned_task(db, session_id=session_id, task_id=task_id) is None:
        raise LookupError("设计任务不存在或不属于当前会话")
    canonical_payload = payload.model_dump(mode="json")
    # 可空扩展字段不能改变旧客户端请求的幂等摘要。
    for item in canonical_payload["document"]["objects"]:
        if item.get("asset_id") is None:
            item.pop("asset_id", None)
    digest = hashlib.sha256(
        json.dumps(
            canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    current = db.scalar(
        select(HomeDesign)
        .where(HomeDesign.task_id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    version = current.current_version if current else 0
    replay = db.scalar(
        select(HomeDesignVersion)
        .where(
            HomeDesignVersion.task_id == task_id,
            HomeDesignVersion.client_mutation_id == payload.client_mutation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if replay:
        if replay.mutation_digest != digest:
            raise SpatialConflict("home_design_idempotency_conflict", version)
        result = _response(replay)
        db.commit()
        return result
    if payload.base_version != version:
        raise SpatialConflict("home_design_version_conflict", version)
    validation = validate_document(db, task_id, payload.document)
    if current is None:
        current = HomeDesign(task_id=task_id, current_version=1)
        db.add(current)
        db.flush()
    else:
        current.current_version = version + 1
    row = HomeDesignVersion(
        task_id=task_id,
        version=version + 1,
        document_json=payload.document.model_dump(mode="json"),
        validation_json=validation.model_dump(mode="json"),
        client_mutation_id=payload.client_mutation_id,
        mutation_digest=digest,
    )
    db.add(row)
    db.flush()
    result = _response(row)
    db.commit()
    return result
