"""整屋家装文档、历史和确定性校验。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from typing import Literal
from sqlalchemy.orm import Session

from app.api.dependencies import (
    SessionIdHeader,
    private_session_headers,
    protect_private_http_exception,
    require_owned_design_task,
    set_private_session_headers,
)
from app.db.database import get_db
from app.schemas.home_design import (
    HomeDesignDocument,
    HomeDesignResponse,
    HomeDesignSaveRequest,
    DesignValidation,
)
from app.services import home_design_service as service
from app.services.aggregate_lock_service import AggregateLockBusy
from app.services.spatial_service import SpatialConflict

from app.schemas.home_design_asset import AssetCreate, AssetResponse
from app.services import home_design_asset_service as assets
from app.schemas.home_design_impact import SpaceImpactRequest, SpaceImpactResponse
from app.services import home_design_impact_service as impact

router = APIRouter()


def _owned_asset_task(db, session_id, task_id, response):
    set_private_session_headers(response)
    try:
        return require_owned_design_task(db, session_id=session_id, task_id=task_id)
    except HTTPException as exc:
        raise protect_private_http_exception(exc) from exc


@router.post("/{task_id}/home-design/space-impact", response_model=SpaceImpactResponse)
def space_impact(
    task_id: int,
    payload: SpaceImpactRequest,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    _owned_asset_task(db, x_session_id, task_id, response)
    try:
        return impact.preview_impact(db, task_id, payload)
    except LookupError as exc:
        raise HTTPException(
            404, detail=str(exc), headers={"Cache-Control": "no-store"}
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            422,
            detail={"code": "home_design_space_impact_invalid", "message": str(exc)},
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get("/{task_id}/home-design/asset-options")
def asset_options(
    task_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    kind: Literal["product", "open_geometry"] = Query(...),
    after_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    task = _owned_asset_task(db, x_session_id, task_id, response)
    return assets.list_options(db, task, kind, after_id, limit)


@router.get("/{task_id}/home-design/assets/{asset_id}", response_model=AssetResponse)
def get_asset(
    task_id: int,
    asset_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    _owned_asset_task(db, x_session_id, task_id, response)
    try:
        return assets.get_asset(db, task_id, asset_id)
    except assets.AssetError as exc:
        raise HTTPException(
            exc.status,
            detail={"code": exc.code, "message": str(exc)},
            headers=private_session_headers(),
        ) from exc


@router.post("/{task_id}/home-design/assets", response_model=AssetResponse)
def create_asset(
    task_id: int,
    payload: AssetCreate,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    _owned_asset_task(db, x_session_id, task_id, response)
    try:
        return assets.create_asset(
            db, task_id=task_id, session_id=x_session_id, payload=payload
        )
    except assets.AssetError as exc:
        db.rollback()
        raise HTTPException(
            exc.status,
            detail={"code": exc.code, "message": str(exc)},
            headers={"Cache-Control": "no-store"},
        ) from exc
    except AggregateLockBusy as exc:
        db.rollback()
        raise HTTPException(
            409,
            detail={"code": "home_asset_busy", "message": str(exc)},
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get("/{task_id}/home-design", response_model=HomeDesignResponse)
def get_design(
    task_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    _owned_asset_task(db, x_session_id, task_id, response)
    return service.get_design(db, task_id)


@router.get("/{task_id}/home-design/versions")
def list_versions(
    task_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    before_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    _owned_asset_task(db, x_session_id, task_id, response)
    return service.list_versions(db, task_id, before_version, limit)


@router.get(
    "/{task_id}/home-design/versions/{version}", response_model=HomeDesignResponse
)
def get_version(
    task_id: int,
    version: int,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    _owned_asset_task(db, x_session_id, task_id, response)
    try:
        return service.get_version(db, task_id, version)
    except LookupError as exc:
        raise HTTPException(
            404, detail=str(exc), headers=private_session_headers()
        ) from exc


@router.post("/{task_id}/home-design/validate", response_model=DesignValidation)
def validate(
    task_id: int,
    payload: HomeDesignDocument,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    try:
        return service.validate_document(db, task_id, payload)
    except ValueError as exc:
        raise HTTPException(
            422, detail={"code": "home_design_reference_invalid", "message": str(exc)}
        ) from exc


@router.put("/{task_id}/home-design", response_model=HomeDesignResponse)
def save(
    task_id: int,
    payload: HomeDesignSaveRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    try:
        return service.save_design(
            db, task_id=task_id, session_id=x_session_id, payload=payload
        )
    except SpatialConflict as exc:
        db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": exc.code,
                "current_version": exc.current_version,
                "message": "家装版本已变化或请求标识被复用",
            },
        ) from exc
    except AggregateLockBusy as exc:
        db.rollback()
        raise HTTPException(
            409, detail={"code": "home_design_busy", "message": str(exc)}
        ) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            422, detail={"code": "home_design_reference_invalid", "message": str(exc)}
        ) from exc
