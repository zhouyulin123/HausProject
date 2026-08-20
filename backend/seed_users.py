# -*- coding: utf-8 -*-
"""创建/更新三个角色的测试账号（幂等，可重复运行）。

用法：
    python seed_users.py

验证码登录固定为 123456（Mock 阶段）。
"""

from app.db.database import SessionLocal
from app.db.models import User
from app.services.auth_service import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_FACTORY

SEED_USERS = [
    {"phone": "13800000001", "role": ROLE_CUSTOMER, "label": "普通用户"},
    {"phone": "13800000002", "role": ROLE_FACTORY, "label": "厂家"},
    {"phone": "13800000003", "role": ROLE_ADMIN, "label": "管理员"},
]


def main():
    db = SessionLocal()
    try:
        for item in SEED_USERS:
            user = db.query(User).filter(User.phone == item["phone"]).first()
            if user:
                user.role = item["role"]
                user.phone_verified = True
                db.commit()
                print(
                    f"更新 {item['label']} {item['phone']} (id={user.id}) -> {item['role']}"
                )
            else:
                user = User(
                    phone=item["phone"],
                    nickname=item["phone"],
                    role=item["role"],
                    phone_verified=True,
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                print(
                    f"创建 {item['label']} {item['phone']} (id={user.id}) -> {item['role']}"
                )
        print("\n完成。三个账号验证码登录固定为 123456。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
