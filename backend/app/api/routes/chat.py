from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import (
    SessionIdHeader,
    require_active_session,
    require_owned_design_task,
)
from app.db.database import get_db
from app.db.models import ChatLog, DesignTask
from app.schemas.tasks import ChatRequest, ChatResponse
from app.services import llm_service
from app.services import anonymous_session_service
from app.services.llm_service import LLMUnavailable

router = APIRouter()


@router.post("", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    """对话式需求确认。LLM 不可用时返回 503，前端降级到本地规则回复。"""
    require_active_session(db, x_session_id)
    if req.task_id is None:
        task = DesignTask(
            status="waiting_user",
            raw_user_input=req.message,
            active_mode="catalog_design",
        )
        db.add(task)
        db.flush()
        anonymous_session_service.attach_task(db, x_session_id, task.id)
        task_id = task.id
    else:
        require_owned_design_task(
            db,
            session_id=x_session_id,
            task_id=req.task_id,
        )
        task_id = req.task_id

    try:
        reply = llm_service.chat_reply(
            message=req.message,
            history=req.history,
            requirement=req.requirement,
        )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    db.add(ChatLog(task_id=task_id, role="user", content=req.message))
    db.add(ChatLog(task_id=task_id, role="ai", content=reply))
    db.commit()

    return ChatResponse(reply=reply, source="llm", task_id=task_id)
