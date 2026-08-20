"""手机号验证码登录接口。"""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.database import get_db
from app.db.models import User
from app.services import auth_service

router = APIRouter()

PHONE_PATTERN = re.compile(r"^1\d{10}$")


class SendCodeRequest(BaseModel):
    phone: str = Field(min_length=11, max_length=11)


class LoginRequest(BaseModel):
    phone: str = Field(min_length=11, max_length=11)
    code: str = Field(min_length=4, max_length=10)
    session_id: Optional[str] = Field(default=None, min_length=36, max_length=36)


def _validate_phone(phone: str) -> None:
    if not PHONE_PATTERN.match(phone):
        raise HTTPException(status_code=422, detail="手机号格式不正确")


@router.post("/send-code")
def send_code(req: SendCodeRequest, db: Session = Depends(get_db)):
    _validate_phone(req.phone)
    try:
        code = auth_service.send_sms_code(db, req.phone)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    payload = {"status": "ok"}
    if settings.app_env == "development":
        payload["dev_code"] = code  # 仅开发环境回传，便于联调
    return payload


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    _validate_phone(req.phone)
    try:
        user = auth_service.login_or_register(db, req.phone, req.code)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    # 登录后把该匿名会话此前生成的任务与图片归属到账号，便于后续「我的方案」恢复
    if req.session_id:
        try:
            auth_service.merge_anonymous_session(db, req.session_id, user.id)
        except Exception:
            # 合并不影响登录本身，失败仅记录日志
            import logging

            logging.getLogger(__name__).exception("合并匿名会话失败")
    token = auth_service.issue_token(user)
    return {"token": token, "user": auth_service.user_to_dict(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"user": auth_service.user_to_dict(user)}
