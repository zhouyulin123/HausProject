# -*- coding: utf-8 -*-
"""设置管理员账号：把指定手机号设为 admin（不存在则创建）。

用法：
    python set_admin.py <手机号>

用于首次部署时自举管理员，之后可在 /admin 的「用户管理」中继续授权厂家/管理员。
"""

import sys

from app.db.database import SessionLocal
from app.db.models import User
from app.services.auth_service import ROLE_ADMIN


def main():
    if len(sys.argv) != 2:
        print("用法: python set_admin.py <手机号>")
        sys.exit(1)

    phone = sys.argv[1].strip()
    if len(phone) != 11 or not phone.isdigit():
        print("手机号格式不正确（需 11 位数字）")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == phone).first()
        if not user:
            user = User(phone=phone, nickname=phone, role=ROLE_ADMIN, phone_verified=True)
            db.add(user)
        else:
            user.role = ROLE_ADMIN
        db.commit()
        print(f"OK: 用户 {phone} (id={user.id}) 已设为管理员")
    finally:
        db.close()


if __name__ == "__main__":
    main()
