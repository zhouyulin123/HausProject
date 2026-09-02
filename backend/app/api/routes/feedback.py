"""任务级设计反馈事件接口。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_owned_design_task
from app.db.database import get_db
from app.schemas.feedback import (
    DesignFeedbackEventRequest,
    DesignFeedbackEventResponse,
)
from app.services import feedback_service


router = APIRouter()


@router.post(
    "/{task_id}/feedback-events",
    response_model=DesignFeedbackEventResponse,
)
def create_feedback_event(
    task_id: int,
    payload: DesignFeedbackEventRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
) -> DesignFeedbackEventResponse:
    require_owned_design_task(db, session_id=x_session_id, task_id=task_id)
    try:
        event = feedback_service.create_feedback_event(
            db,
            task_id=task_id,
            payload=payload,
        )
    except feedback_service.FeedbackResourceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except feedback_service.FeedbackIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DesignFeedbackEventResponse.model_validate(event)
