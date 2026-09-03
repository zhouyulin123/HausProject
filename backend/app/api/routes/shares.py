"""方案分享：所有者管理接口与无会话公开只读接口。"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_active_session
from app.db.database import get_db
from app.schemas.shares import (
    CreatePlanShareRequest,
    CreatePlanShareResponse,
    PublicPlanShareResponse,
    RevokePlanShareResponse,
)
from app.services import scene_service, share_service


owner_router = APIRouter()
public_router = APIRouter()

_UNAVAILABLE = {
    "code": "share_unavailable",
    "message": "分享链接不存在或已失效",
}


def _unavailable() -> HTTPException:
    return HTTPException(status_code=404, detail=_UNAVAILABLE)


@owner_router.post("", response_model=CreatePlanShareResponse, status_code=201)
def create_plan_share(
    payload: CreatePlanShareRequest,
    response: Response,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    plan_version = scene_service.get_owned_plan_version(
        db,
        session_id=x_session_id,
        plan_version_id=payload.plan_version_id,
    )
    if plan_version is None:
        raise HTTPException(status_code=404, detail="方案版本不存在")
    share, token = share_service.create_share(
        db,
        plan_version=plan_version,
        expires_in_hours=payload.expires_in_hours,
    )
    response.headers["Cache-Control"] = "no-store"
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
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
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
    share = share_service.get_available_share(db, token=token)
    if share is None:
        raise _unavailable()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return PublicPlanShareResponse(
        expires_at=share.expires_at,
        plan=share.snapshot_json,
    )
