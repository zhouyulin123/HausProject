"""任务级整屋空间 API。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_owned_design_task
from app.db.database import get_db
from app.schemas.spatial import SpatialResponse, SpatialSaveRequest
from app.services import spatial_service
from app.services.aggregate_lock_service import AggregateLockBusy


router = APIRouter()


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
