from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ChatLog
from app.schemas.tasks import ChatRequest, ChatResponse
from app.services import llm_service
from app.services.llm_service import LLMUnavailable

router = APIRouter()


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """对话式需求确认。LLM 不可用时返回 503，前端降级到本地规则回复。"""
    try:
        reply = llm_service.chat_reply(
            message=req.message,
            history=req.history,
            requirement=req.requirement,
        )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    db.add(ChatLog(task_id=req.task_id, role="user", content=req.message))
    db.add(ChatLog(task_id=req.task_id, role="ai", content=reply))
    db.commit()

    return ChatResponse(reply=reply, source="llm")
