"""手机号验证码登录接口。"""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
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


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.jwt_expire_minutes * 60,
        path="/api",
        secure=settings.app_env == "production",
        httponly=True,
        samesite="strict",
    )


@router.post("/login")
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
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
    _set_auth_cookie(response, token)
    return {"user": auth_service.user_to_dict(user)}


@router.get("/me")
def me(response: Response, user: User = Depends(get_current_user)):
    # 旧版 Bearer 登录访问一次 /me 后即可迁移到 Cookie 会话。
    _set_auth_cookie(response, auth_service.issue_token(user))
    return {"user": auth_service.user_to_dict(user)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/api",
        secure=settings.app_env == "production",
        httponly=True,
        samesite="strict",
    )
    return {"status": "ok"}
