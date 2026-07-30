"""统一设计任务客户关系

Revision ID: 3e9d6b1a7c42
Revises: c0880aafa1bb
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op


revision: str = "3e9d6b1a7c42"
down_revision: Union[str, Sequence[str], None] = "c0880aafa1bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """统一索引命名，并补齐历史手工字段缺少的外键。"""
    with op.batch_alter_table("design_tasks") as batch_op:
        batch_op.drop_index("idx_customer")
        batch_op.create_index(
            "ix_design_tasks_customer_id",
            ["customer_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_design_tasks_customer_id_customers",
            "customers",
            ["customer_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("design_tasks") as batch_op:
        batch_op.drop_constraint(
            "fk_design_tasks_customer_id_customers",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_design_tasks_customer_id")
        batch_op.create_index("idx_customer", ["customer_id"], unique=False)
