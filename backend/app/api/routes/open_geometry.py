"""任务级开放几何家具 API。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_owned_design_task
from app.db.database import get_db
from app.schemas.open_geometry import (
    OpenGeometryCommandRequest,
    OpenGeometryCommandResponse,
    OpenGeometryRestoreRequest,
    OpenGeometryStateResponse,
)
from app.services import open_geometry_service
from app.services.aggregate_lock_service import AggregateLockBusy
from app.services.open_geometry_rate_limit import open_geometry_rate_limiter


router = APIRouter()


def _raise_service_error(exc: open_geometry_service.OpenGeometryError) -> None:
    if isinstance(exc, open_geometry_service.OpenGeometryVersionConflict):
        status = 409
        extra = {"current_version": exc.current_version}
    elif isinstance(exc, open_geometry_service.OpenGeometryIdempotencyConflict):
        status = 409
        extra = {}
    elif exc.code == "llm_unavailable":
        status = 503
        extra = {}
    elif exc.code == "version_not_found":
        status = 404
        extra = {}
    elif exc.code == "invalid_state":
        status = 500
        extra = {}
    else:
        status = 422
        extra = {}
    raise HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": str(exc), "errors": exc.details, **extra},
    ) from exc


@router.get("/{task_id}/open-geometry", response_model=OpenGeometryStateResponse)
def get_open_geometry(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    try:
        return open_geometry_service.get_state(task)
    except open_geometry_service.OpenGeometryError as exc:
        _raise_service_error(exc)


@router.post(
    "/{task_id}/open-geometry/commands",
    response_model=OpenGeometryCommandResponse,
)
def command_open_geometry(
    task_id: int,
    payload: OpenGeometryCommandRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    try:
        replay = open_geometry_service.replay_command(
            db,
            task_id=task_id,
            client_mutation_id=payload.client_mutation_id,
            base_version=payload.base_version,
            instruction=payload.instruction,
        )
        if replay is not None:
            return replay
        retry_after = open_geometry_rate_limiter.retry_after(
            db,
            session_id=x_session_id,
            task_id=task_id,
        )
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail={"code": "rate_limited", "message": "开放几何 AI 请求过于频繁，请稍后重试"},
                headers={"Retry-After": str(retry_after)},
            )
        return open_geometry_service.apply_command(
            db,
            task_id=task_id,
            client_mutation_id=payload.client_mutation_id,
            base_version=payload.base_version,
            instruction=payload.instruction,
        )
    except open_geometry_service.OpenGeometryError as exc:
        db.rollback()
        _raise_service_error(exc)
    except AggregateLockBusy as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "aggregate_busy", "message": str(exc)}) from exc


@router.post(
    "/{task_id}/open-geometry/restore",
    response_model=OpenGeometryCommandResponse,
)
def restore_open_geometry(
    task_id: int,
    payload: OpenGeometryRestoreRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    try:
        return open_geometry_service.restore_version(
            db,
            task_id=task_id,
            client_mutation_id=payload.client_mutation_id,
            base_version=payload.base_version,
            target_version=payload.target_version,
        )
    except open_geometry_service.OpenGeometryError as exc:
        db.rollback()
        _raise_service_error(exc)
    except AggregateLockBusy as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "aggregate_busy", "message": str(exc)}) from exc
