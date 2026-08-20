from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AnonymousSession, DesignTask, User
from app.services import anonymous_session_service, auth_service


SessionIdHeader = Annotated[
    str,
    Header(
        alias="X-Session-ID",
        min_length=36,
        max_length=36,
        description="无需登录客户的匿名会话编号",
    ),
]

AuthorizationHeader = Annotated[
    Optional[str],
    Header(alias="Authorization", description="Bearer <JWT>"),
]


def get_current_user(
    authorization: AuthorizationHeader,
    db: Session = Depends(get_db),
) -> User:
    """解析 Bearer JWT 并返回当前用户；未登录返回 401。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = auth_service.decode_token(token)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    raw_user_id = payload.get("sub")
    if not raw_user_id:
        raise HTTPException(status_code=401, detail="登录凭证无效")
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="登录凭证无效") from exc
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def require_factory(user: User = Depends(get_current_user)) -> User:
    """厂家或管理员可访问（材料/费用编辑、订单池、客户跟单等）。"""
    if user.role not in (auth_service.ROLE_FACTORY, auth_service.ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="需要厂家权限")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """仅管理员可访问（用户角色管理等）。"""
    if user.role != auth_service.ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_active_session(db: Session, session_id: str) -> AnonymousSession:
    session = anonymous_session_service.get_active_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="匿名会话不存在或已过期")
    return session


def require_owned_design_task(
    db: Session,
    *,
    session_id: str,
    task_id: int,
) -> DesignTask:
    require_active_session(db, session_id)
    task = db.get(DesignTask, task_id)
    if not task or not anonymous_session_service.session_owns_task(
        db,
        session_id,
        task_id,
    ):
        # 不区分任务不存在和无权访问，避免通过连续 ID 枚举其他客户任务。
        raise HTTPException(
            status_code=404,
            detail="设计任务不存在或不属于当前会话",
        )
    return task
