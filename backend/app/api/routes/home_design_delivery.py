"""权限内只读整屋概念清单与不可变版本比较。"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies import (
    SessionIdHeader,
    private_session_headers,
    protect_private_http_exception,
    require_owned_design_task,
    set_private_session_headers,
)
from app.db.database import get_db
from app.services.home_design_delivery import compare_deliveries, get_delivery
from app.schemas.home_quote import HomeQuoteRequest
from app.services import home_quote_service
from app.services.aggregate_lock_service import AggregateLockBusy

router = APIRouter()


@router.post("/{task_id}/home-design/quotes")
def create_quote(
    task_id: int,
    payload: HomeQuoteRequest,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    set_private_session_headers(response)
    try:
        require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    except HTTPException as exc:
        raise protect_private_http_exception(exc) from exc
    try:
        return home_quote_service.create_quote(
            db, task_id=task_id, session_id=x_session_id, payload=payload
        )
    except (home_quote_service.HomeQuoteConflict, AggregateLockBusy) as exc:
        db.rollback()
        raise HTTPException(
            409,
            detail={"code": "home_quote_conflict", "message": str(exc)},
            headers=private_session_headers(),
        ) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(
            404,
            detail={"code": "home_quote_missing", "message": str(exc)},
            headers=private_session_headers(),
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            422,
            detail={"code": "home_quote_invalid", "message": "方案无法形成可信估价"},
            headers=private_session_headers(),
        ) from exc


@router.get("/{task_id}/home-design/quotes")
def quotes(
    task_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    home_version: int = Query(ge=1),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=10, ge=1, le=20),
    db: Session = Depends(get_db),
):
    set_private_session_headers(response)
    try:
        require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    except HTTPException as exc:
        raise protect_private_http_exception(exc) from exc
    try:
        return home_quote_service.list_quotes(
            db, task_id, home_version, before_id, limit
        )
    except home_quote_service.HomeQuoteConflict as exc:
        raise HTTPException(
            409,
            detail={"code": "home_quote_conflict", "message": str(exc)},
            headers=private_session_headers(),
        ) from exc


@router.get("/{task_id}/home-design/quotes/{quote_id}")
def quote(
    task_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    quote_id: int = Path(ge=1),
    db: Session = Depends(get_db),
):
    set_private_session_headers(response)
    try:
        require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    except HTTPException as exc:
        raise protect_private_http_exception(exc) from exc
    try:
        return home_quote_service.read_quote(db, task_id, quote_id)
    except home_quote_service.HomeQuoteConflict as exc:
        raise HTTPException(
            409,
            detail={"code": "home_quote_conflict", "message": str(exc)},
            headers=private_session_headers(),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            404,
            detail={"code": "home_quote_missing", "message": str(exc)},
            headers=private_session_headers(),
        ) from exc


def _snapshot(db, task_id, version):
    try:
        return get_delivery(db, task_id, version)
    except LookupError as exc:
        raise HTTPException(
            404,
            detail={"code": "home_delivery_version_missing", "message": str(exc)},
            headers=private_session_headers(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            422,
            detail={
                "code": "home_delivery_invalid",
                "message": "该历史版本的空间或家装数据无法形成可信清单",
            },
            headers=private_session_headers(),
        ) from exc


@router.get("/{task_id}/home-design/versions/{version}/delivery")
def delivery(
    task_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    version: int = Path(ge=1),
    db: Session = Depends(get_db),
):
    set_private_session_headers(response)
    try:
        require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    except HTTPException as exc:
        raise protect_private_http_exception(exc) from exc
    return _snapshot(db, task_id, version)


@router.get("/{task_id}/home-design/compare")
def compare(
    task_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    from_version: int = Query(ge=1),
    to_version: int = Query(ge=1),
    db: Session = Depends(get_db),
):
    set_private_session_headers(response)
    try:
        require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    except HTTPException as exc:
        raise protect_private_http_exception(exc) from exc
    return compare_deliveries(
        _snapshot(db, task_id, from_version), _snapshot(db, task_id, to_version)
    )
