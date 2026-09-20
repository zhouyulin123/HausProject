"""所有者交付管理与无会话公开投影。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.api.dependencies import SessionIdHeader, require_owned_design_task
from app.db.database import get_db
from app.db.models import (
    HomeDeliveryConfirmation,
    HomeDeliveryShare,
)
from app.schemas.home_delivery_snapshot import (
    DeliveryCreate,
    DeliverySummaryPage,
    ConfirmationCreate,
    ShareCreate,
)
from app.services import home_delivery_snapshot_service as service
from app.services.aggregate_lock_service import AggregateLockBusy
from app.services.home_quote_service import HomeQuoteConflict

router = APIRouter()
public_router = APIRouter()
HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}


def _run(response, action):
    response.headers.update(HEADERS)
    try:
        return action()
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), **HEADERS}
        raise
    except LookupError as exc:
        raise HTTPException(
            404,
            detail={"code": "home_delivery_unavailable", "message": str(exc)},
            headers=HEADERS,
        ) from exc
    except (service.DeliveryError, HomeQuoteConflict, AggregateLockBusy) as exc:
        raise HTTPException(
            409,
            detail={"code": "home_delivery_conflict", "message": str(exc)},
            headers=HEADERS,
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            422,
            detail={"code": "home_delivery_invalid", "message": "交付数据无法校验"},
            headers=HEADERS,
        ) from exc


def _owned(db, task_id, session_id, action):
    require_owned_design_task(db, task_id=task_id, session_id=session_id)
    return action()


@router.post("/{task_id}/home-design/deliveries")
def create(
    task_id: int,
    payload: DeliveryCreate,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    return _run(
        response,
        lambda: _owned(
            db,
            task_id,
            x_session_id,
            lambda: service.create_delivery(db, task_id, x_session_id, payload),
        ),
    )


@router.get(
    "/{task_id}/home-design/deliveries", response_model=DeliverySummaryPage
)
def deliveries(
    task_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    home_version: int | None = Query(default=None, ge=1),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=10, ge=1, le=20),
    db: Session = Depends(get_db),
):
    return _run(
        response,
        lambda: _owned(
            db,
            task_id,
            x_session_id,
            lambda: service.page_deliveries(
                db,
                task_id,
                before_id,
                limit,
                home_version=home_version,
            ),
        ),
    )


@router.get("/{task_id}/home-design/deliveries/{delivery_id}")
def delivery(
    task_id: int,
    delivery_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    return _run(
        response,
        lambda: _owned(
            db,
            task_id,
            x_session_id,
            lambda: service.read_delivery(db, task_id, delivery_id),
        ),
    )


@router.post("/{task_id}/home-design/deliveries/{delivery_id}/confirmations")
def confirm(
    task_id: int,
    delivery_id: int,
    payload: ConfirmationCreate,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    return _run(
        response,
        lambda: _owned(
            db,
            task_id,
            x_session_id,
            lambda: service.confirm(db, task_id, x_session_id, delivery_id, payload),
        ),
    )


@router.get("/{task_id}/home-design/deliveries/{delivery_id}/confirmations")
def confirmations(
    task_id: int,
    delivery_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=10, ge=1, le=20),
    db: Session = Depends(get_db),
):
    def action():
        service.read_delivery(db, task_id, delivery_id)
        return service.page(
            db,
            HomeDeliveryConfirmation,
            task_id,
            before_id,
            limit,
            service.confirmation_response,
            delivery_id=delivery_id,
        )

    return _run(response, lambda: _owned(db, task_id, x_session_id, action))


@router.post("/{task_id}/home-design/deliveries/{delivery_id}/shares")
def create_share(
    task_id: int,
    delivery_id: int,
    payload: ShareCreate,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    return _run(
        response,
        lambda: _owned(
            db,
            task_id,
            x_session_id,
            lambda: service.create_share(
                db, task_id, x_session_id, delivery_id, payload
            ),
        ),
    )


@router.get("/{task_id}/home-design/shares")
def shares(
    task_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=10, ge=1, le=20),
    db: Session = Depends(get_db),
):
    return _run(
        response,
        lambda: _owned(
            db,
            task_id,
            x_session_id,
            lambda: service.page(
                db, HomeDeliveryShare, task_id, before_id, limit, service.share_response
            ),
        ),
    )


@router.post("/{task_id}/home-design/shares/{share_id}/revoke")
def revoke(
    task_id: int,
    share_id: int,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    return _run(
        response,
        lambda: _owned(
            db,
            task_id,
            x_session_id,
            lambda: service.revoke(db, task_id, x_session_id, share_id),
        ),
    )


@public_router.get("/{token}")
def public(token: str, response: Response, db: Session = Depends(get_db)):
    try:
        return _run(response, lambda: service.public_share(db, token))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            503,
            detail={"code": "home_share_unavailable", "message": "分享服务暂不可用"},
            headers=HEADERS,
        ) from exc
