from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.sessions import (
    AnonymousSessionResponse,
    SessionTaskListResponse,
    SessionTaskSummary,
)
from app.services import anonymous_session_service

router = APIRouter()


def _response(session) -> AnonymousSessionResponse:
    return AnonymousSessionResponse(
        session_id=session.id,
        status=session.status,
        expires_at=session.expires_at,
    )


@router.post("", response_model=AnonymousSessionResponse)
def create_session(db: Session = Depends(get_db)):
    return _response(anonymous_session_service.create_anonymous_session(db))


@router.get("/{session_id}", response_model=AnonymousSessionResponse)
def resume_session(session_id: str, db: Session = Depends(get_db)):
    session = anonymous_session_service.get_active_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="匿名会话不存在或已过期")
    return _response(session)


@router.get("/{session_id}/tasks", response_model=SessionTaskListResponse)
def get_session_tasks(session_id: str, db: Session = Depends(get_db)):
    session = anonymous_session_service.get_active_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="匿名会话不存在或已过期")
    tasks = anonymous_session_service.list_session_tasks(db, session_id)
    return SessionTaskListResponse(
        tasks=[
            SessionTaskSummary(
                task_id=task.id,
                status=task.status,
                progress=task.progress or 0,
                space_type=task.space_type,
                style=task.style,
                created_at=task.created_at,
            )
            for task in tasks
        ]
    )
