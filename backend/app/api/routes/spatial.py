"""任务级整屋空间 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_owned_design_task
from app.db.database import get_db
from app.db.models import UploadedImage
from app.schemas.spatial import SpatialResponse, SpatialSaveRequest
from app.services import spatial_service
from app.services.spatial_projection import project_room
from app.services.aggregate_lock_service import AggregateLockBusy


router = APIRouter()


def _owned_version(db, task_id, version, session_id):
    require_owned_design_task(db, session_id=session_id, task_id=task_id)
    try:
        return spatial_service.get_version(db, task_id, version)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{task_id}/space/versions")
def list_space_versions(
    task_id: int,
    x_session_id: SessionIdHeader,
    before_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    return spatial_service.list_versions(db, task_id, before_version, limit)


@router.get("/{task_id}/space/versions/{version}", response_model=SpatialResponse)
def get_space_version(
    task_id: int,
    version: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    return _owned_version(db, task_id, version, x_session_id)


@router.get("/{task_id}/space/versions/{version}/source")
def get_space_source(
    task_id: int,
    version: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    snapshot = _owned_version(db, task_id, version, x_session_id)
    image_id = snapshot.document.source_image_id
    image = db.get(UploadedImage, image_id) if image_id else None
    if image is None or image.task_id != task_id:
        return None
    return {
        "image_id": image.id,
        "image_url": image.file_url,
        "file_name": image.file_name,
    }


@router.get("/{task_id}/space/versions/{version}/rooms/{room_id}/scene")
def get_room_projection(
    task_id: int,
    version: int,
    room_id: str,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    snapshot = _owned_version(db, task_id, version, x_session_id)
    try:
        scene = project_room(snapshot.document, room_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "task_id": task_id,
        "space_version": version,
        "room_id": room_id,
        "scene": scene.model_dump(mode="json", by_alias=True),
    }


@router.get("/{task_id}/space/sources/{image_id}")
def get_draft_source(
    task_id: int,
    image_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    image = db.get(UploadedImage, image_id)
    if image is None or image.task_id != task_id:
        raise HTTPException(status_code=404, detail="原图不存在")
    return {
        "image_id": image.id,
        "image_url": image.file_url,
        "file_name": image.file_name,
    }


@router.get("/{task_id}/space", response_model=SpatialResponse)
def get_space(
    task_id: int, x_session_id: SessionIdHeader, db: Session = Depends(get_db)
):
    require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    return spatial_service.get_space(db, task_id)


@router.put("/{task_id}/space", response_model=SpatialResponse)
def put_space(
    task_id: int,
    payload: SpatialSaveRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    try:
        return spatial_service.save_space(
            db, task_id=task_id, session_id=x_session_id, payload=payload
        )
    except spatial_service.SpatialConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "current_version": exc.current_version,
                "message": "空间版本已变化或请求标识被复用",
            },
        ) from exc
    except spatial_service.SpatialSourceError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "spatial_source_invalid", "message": str(exc)},
        ) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AggregateLockBusy as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "spatial_busy", "message": str(exc)}
        ) from exc
