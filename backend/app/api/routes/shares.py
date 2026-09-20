"""方案分享：所有者管理接口与无会话公开只读接口。"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    SessionIdHeader,
    private_session_headers,
    protect_private_http_exception,
    require_active_session,
    set_private_session_headers,
)
from app.db.database import get_db
from app.schemas.shares import (
    CreatePlanShareRequest,
    CreatePlanShareResponse,
    PublicPlanShareResponse,
    RevokePlanShareResponse,
)
from app.services import plan_delivery_service, scene_service, share_service


owner_router = APIRouter()
public_router = APIRouter()

_UNAVAILABLE = {
    "code": "share_unavailable",
    "message": "分享链接不存在或已失效",
}
_PUBLIC_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}


def _unavailable(*, public: bool = False) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=_UNAVAILABLE,
        headers=_PUBLIC_HEADERS if public else private_session_headers(),
    )


@owner_router.post("", response_model=CreatePlanShareResponse, status_code=201)
def create_plan_share(
    payload: CreatePlanShareRequest,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    set_private_session_headers(response)
    try:
        require_active_session(db, x_session_id)
    except HTTPException as exc:
        raise protect_private_http_exception(exc) from exc
    plan_version = scene_service.get_owned_plan_version(
        db,
        session_id=x_session_id,
        plan_version_id=payload.plan_version_id,
    )
    if plan_version is None:
        raise HTTPException(
            status_code=404,
            detail="方案版本不存在",
            headers=private_session_headers(),
        )
    try:
        share, token = share_service.create_share(
            db,
            plan_version=plan_version,
            expires_in_hours=payload.expires_in_hours,
        )
    except plan_delivery_service.PlanDeliveryBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail=exc.detail(),
            headers=private_session_headers(),
        ) from exc
    return CreatePlanShareResponse(
        token=token,
        share_url=f"/share/{token}",
        expires_at=share.expires_at,
    )


@owner_router.post(
    "/{token}/revoke", response_model=RevokePlanShareResponse
)
def revoke_plan_share(
    token: str,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    set_private_session_headers(response)
    try:
        require_active_session(db, x_session_id)
    except HTTPException as exc:
        raise protect_private_http_exception(exc) from exc
    if not share_service.revoke_owned_share(
        db, token=token, session_id=x_session_id
    ):
        raise _unavailable()
    return RevokePlanShareResponse(status="revoked")


@public_router.get("/{token}", response_model=PublicPlanShareResponse)
def get_public_plan_share(
    token: str,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        share = share_service.get_available_share(db, token=token)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "share_unavailable",
                "message": "分享服务暂不可用",
            },
            headers=_PUBLIC_HEADERS,
        ) from exc
    if share is None:
        raise _unavailable(public=True)
    response.headers.update(_PUBLIC_HEADERS)
    return PublicPlanShareResponse(
        expires_at=share.expires_at,
        plan=share.snapshot_json,
    )
