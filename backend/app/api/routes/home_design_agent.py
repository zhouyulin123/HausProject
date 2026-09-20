"""整屋 AI 建议不直接保存或覆盖设计。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_owned_design_task
from app.db.database import get_db
from app.schemas.home_design_agent import (
    HomeDesignAgentRequest,
    HomeDesignAgentResponse,
    HomeDesignAgentHistory,
)
from app.services import home_design_agent_service as service
from app.services.aggregate_lock_service import AggregateLockBusy

router = APIRouter()


def _error(exc):
    headers = {"Cache-Control": "no-store"}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)
    return HTTPException(
        exc.status_code,
        detail={"code": exc.code, "message": exc.message},
        headers=headers,
    )


@router.post(
    "/{task_id}/home-design/agent-turns", response_model=HomeDesignAgentResponse
)
def create_turn(
    task_id: int,
    payload: HomeDesignAgentRequest,
    x_session_id: SessionIdHeader,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
        return service.create_turn(
            db, task_id=task_id, session_id=x_session_id, payload=payload
        )
    except service.HomeAgentError as exc:
        db.rollback()
        raise _error(exc) from exc
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
        raise
    except AggregateLockBusy as exc:
        db.rollback()
        raise HTTPException(
            409,
            detail={"code": "home_agent_busy", "message": "设计正在更新，请稍后重试"},
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get("/{task_id}/home-design/agent-turns", response_model=HomeDesignAgentHistory)
def history(
    task_id: int,
    x_session_id: SessionIdHeader,
    response: Response,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
        return service.history(db, task_id=task_id, before_id=before_id, limit=limit)
    except service.HomeAgentError as exc:
        raise _error(exc) from exc
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
        raise
