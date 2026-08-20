"""新增登录角色与订单池：users 角色字段 + 短信验证码 + 订单意向 + 厂家报价。

Revision ID: e7f8a9b0c1d2
Revises: d4e6f8a0b2c4
Create Date: 2026-08-17 14:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d4e6f8a0b2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users 增加角色、手机号验证与最后登录时间
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="customer",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "phone_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    # 短信验证码
    op.create_table(
        "sms_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sms_codes_id"), "sms_codes", ["id"], unique=False)
    op.create_index(op.f("ix_sms_codes_phone"), "sms_codes", ["phone"], unique=False)

    # 订单意向
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_no", sa.String(length=40), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("plan_version_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("budget_min", sa.Integer(), nullable=True),
        sa.Column("budget_max", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("assigned_factory_id", sa.Integer(), nullable=True),
        sa.Column("assigned_quote_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_factory_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["plan_version_id"], ["design_plan_versions.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["design_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "order_no", "customer_id", "task_id", "status"):
        op.create_index(
            op.f(f"ix_orders_{column}"),
            "orders",
            [column],
            unique=(column == "order_no"),
        )

    # 厂家报价
    op.create_table(
        "order_quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("factory_id", sa.Integer(), nullable=False),
        sa.Column("total_price", sa.Integer(), nullable=False),
        sa.Column("price_min", sa.Integer(), nullable=True),
        sa.Column("price_max", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["factory_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "order_id", "factory_id", "status"):
        op.create_index(
            op.f(f"ix_order_quotes_{column}"),
            "order_quotes",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("order_quotes")
    op.drop_table("orders")
    for column in ("id", "phone"):
        op.drop_index(op.f(f"ix_sms_codes_{column}"), table_name="sms_codes")
    op.drop_table("sms_codes")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "phone_verified")
    op.drop_column("users", "role")
