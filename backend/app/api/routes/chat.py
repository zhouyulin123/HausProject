from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_active_session
from app.db.database import get_db
from app.schemas.tasks import ChatRequest, ChatResponse

router = APIRouter()


@router.post("", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    """保留旧路由的会话边界，但禁止绕过统一 Design Agent。"""
    require_active_session(db, x_session_id)
    raise HTTPException(
        status_code=410,
        detail={
            "code": "legacy_chat_retired",
            "message": "旧聊天入口已停用，请使用统一设计智能体工作台",
        },
    )
