"""管理员接口：用户角色管理（把普通用户提升为厂家/管理员）。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.db.database import get_db
from app.db.models import User
from app.services import auth_service

router = APIRouter()


class RoleUpdate(BaseModel):
    role: str = Field(pattern="^(customer|factory|admin)$")


def _user_to_dict(user: User) -> dict:
    return auth_service.user_to_dict(user) | {
        "created_at": user.created_at.strftime("%Y-%m-%d %H:%M") if user.created_at else None,
        "last_login_at": user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else None,
    }


@router.get("/users")
def list_users(
    q: Optional[str] = None,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.id.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(User.phone.like(like) | User.nickname.like(like))
    users = db.scalars(stmt).all()
    return {"users": [_user_to_dict(u) for u in users]}


@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    data: RoleUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id and data.role != "admin":
        raise HTTPException(status_code=422, detail="不能降低自己的管理员权限")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.role = data.role
    db.commit()
    return {"user": _user_to_dict(user)}
