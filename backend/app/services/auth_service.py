"""手机号验证码登录与 JWT 鉴权服务。

Mock 阶段验证码固定为 settings.sms_mock_code，开发环境会在日志打印并返回
dev_code 便于联调；生产切换真实短信服务商时只需替换 _send_sms 的实现。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import SmsCode, User

logger = logging.getLogger(__name__)

ROLE_CUSTOMER = "customer"
ROLE_FACTORY = "factory"
ROLE_ADMIN = "admin"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AuthError(Exception):
    """认证/验证码相关的可预期错误，路由层转成 4xx。"""


def _send_sms(phone: str, code: str) -> None:
    """真实短信发送的占位实现；生产环境替换为短信服务商调用。"""
    if settings.app_env == "development":
        logger.info("[mock-sms] 验证码 %s 已发送到 %s", code, phone)
    else:
        logger.info("[sms] 向 %s 发送验证码（生产环境待接入短信服务商）", phone)


def send_sms_code(
    db: Session,
    phone: str,
    *,
    now: datetime | None = None,
) -> str:
    """生成并发送验证码；返回 code（开发环境可回传给前端联调）。"""
    current = now or _utc_now()
    latest = db.scalars(
        select(SmsCode).where(SmsCode.phone == phone).order_by(SmsCode.id.desc())
    ).first()
    if latest and _as_utc(latest.created_at) + timedelta(
        seconds=settings.sms_code_resend_seconds
    ) > _as_utc(current):
        raise AuthError("发送太频繁，请稍后再试")

    code = settings.sms_mock_code
    expires_at = current + timedelta(seconds=settings.sms_code_expire_seconds)
    db.add(
        SmsCode(
            phone=phone,
            code=code,
            purpose="login",
            expires_at=expires_at,
            created_at=current,
        )
    )
    db.commit()
    _send_sms(phone, code)
    return code


def _consume_code(db: Session, phone: str, code: str, *, now: datetime | None) -> SmsCode:
    current = now or _utc_now()
    record = db.scalars(
        select(SmsCode)
        .where(
            SmsCode.phone == phone,
            SmsCode.code == code,
            SmsCode.consumed.is_(False),
        )
        .order_by(SmsCode.id.desc())
    ).first()
    if not record or _as_utc(record.expires_at) <= _as_utc(current):
        raise AuthError("验证码错误或已过期")
    record.consumed = True
    db.commit()
    return record


def login_or_register(
    db: Session,
    phone: str,
    code: str,
    *,
    now: datetime | None = None,
) -> User:
    """验证码校验通过后，按手机号登录；不存在则自动注册为普通用户。"""
    current = now or _utc_now()
    _consume_code(db, phone, code, now=current)

    user = db.scalars(select(User).where(User.phone == phone)).first()
    if not user:
        user = User(
            phone=phone,
            nickname=phone,
            role=ROLE_CUSTOMER,
            phone_verified=True,
            last_login_at=current,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    user.phone_verified = True
    user.last_login_at = current
    db.commit()
    return user


def issue_token(user: User, *, now: datetime | None = None) -> str:
    current = now or _utc_now()
    payload = {
        "sub": str(user.id),
        "phone": user.phone,
        "role": user.role,
        "exp": current + timedelta(minutes=settings.jwt_expire_minutes),
        "iat": current,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """解析并校验 JWT；失败抛 AuthError。"""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise AuthError("登录已失效，请重新登录") from exc


def user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "phone": user.phone,
        "nickname": user.nickname,
        "avatar": user.avatar,
        "role": user.role,
    }


def merge_anonymous_session(db: Session, session_id: str, user_id: int) -> int:
    """把匿名会话已生成的设计任务与图片归属到登录用户，返回合并的任务数。"""
    from app.db.models import AnonymousSessionImage, UploadedImage
    from app.services import anonymous_session_service

    merged_tasks = 0
    for task in anonymous_session_service.list_session_tasks(db, session_id):
        if task.user_id is None:
            task.user_id = user_id
            merged_tasks += 1

    image_ids = db.scalars(
        select(AnonymousSessionImage.image_id).where(
            AnonymousSessionImage.session_id == session_id
        )
    ).all()
    merged_images = 0
    if image_ids:
        for image in db.scalars(
            select(UploadedImage).where(UploadedImage.id.in_(image_ids))
        ).all():
            if image.user_id is None:
                image.user_id = user_id
                merged_images += 1

    db.commit()
    logger.info(
        "合并匿名会话 %s 到用户 %s：%d 个任务、%d 张图片",
        session_id,
        user_id,
        merged_tasks,
        merged_images,
    )
    return merged_tasks
