"""管理员接口：用户角色管理（把普通用户提升为厂家/管理员）。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.db.database import get_db
from app.db.models import FailureCluster, User
from app.schemas.failure_triage import (
    FailureClusterListResponse,
    FailureClusterResponse,
    FailureClusterSummary,
    FailureClusterUpdate,
    FailureSeverity,
    FailureStatus,
    FailureTriageReportRequest,
    FailureTriageSyncResponse,
)
from app.schemas.quality import QualitySummaryResponse
from app.services import auth_service
from app.services.quality_metrics_service import build_quality_summary
from app.services import failure_triage_service

router = APIRouter()


class RoleUpdate(BaseModel):
    role: str = Field(pattern="^(customer|factory|admin)$")


@router.get("/quality/summary", response_model=QualitySummaryResponse)
def get_quality_summary(
    window_days: int = Query(default=30, ge=1, le=365),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> QualitySummaryResponse:
    return QualitySummaryResponse.model_validate(
        build_quality_summary(db, window_days=window_days)
    )


@router.post(
    "/quality/failure-clusters/sync",
    response_model=FailureTriageSyncResponse,
)
def sync_failure_clusters(
    payload: FailureTriageReportRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FailureTriageSyncResponse:
    try:
        result = failure_triage_service.sync_verified_report(db, payload)
    except failure_triage_service.FailureTriageConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FailureTriageSyncResponse(
        imported=result.imported,
        cluster_count=len(result.clusters),
        clusters=[FailureClusterResponse.model_validate(item) for item in result.clusters],
    )


@router.get(
    "/quality/failure-clusters",
    response_model=FailureClusterListResponse,
)
def list_failure_clusters(
    status: FailureStatus | None = Query(default=None),
    severity: FailureSeverity | None = Query(default=None),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FailureClusterListResponse:
    clusters, summary = failure_triage_service.list_failure_clusters(
        db,
        status=status,
        severity=severity,
    )
    return FailureClusterListResponse(
        items=[FailureClusterResponse.model_validate(item) for item in clusters],
        summary=FailureClusterSummary.model_validate(summary),
    )


@router.patch(
    "/quality/failure-clusters/{cluster_id}",
    response_model=FailureClusterResponse,
)
def patch_failure_cluster(
    cluster_id: int,
    payload: FailureClusterUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FailureClusterResponse:
    cluster = db.get(FailureCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="失败簇不存在")
    try:
        updated = failure_triage_service.update_failure_cluster(db, cluster, payload)
    except failure_triage_service.FailureTriageConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FailureClusterResponse.model_validate(updated)


def _user_to_dict(user: User) -> dict:
    return auth_service.user_to_dict(user) | {
        "created_at": user.created_at.strftime("%Y-%m-%d %H:%M") if user.created_at else None,
        "last_login_at": user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else None,
    }


@router.get("/users")
def list_users(
    q: Optional[str] = None,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.id.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(User.phone.like(like) | User.nickname.like(like))
    users = db.scalars(stmt).all()
    return {"users": [_user_to_dict(u) for u in users]}


@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    data: RoleUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id and data.role != "admin":
        raise HTTPException(status_code=422, detail="不能降低自己的管理员权限")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.role = data.role
    db.commit()
    return {"user": _user_to_dict(user)}
