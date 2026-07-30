from typing import Annotated

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.db.models import AnonymousSession, DesignTask
from app.services import anonymous_session_service


SessionIdHeader = Annotated[
    str,
    Header(
        alias="X-Session-ID",
        min_length=36,
        max_length=36,
        description="无需登录客户的匿名会话编号",
    ),
]


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
