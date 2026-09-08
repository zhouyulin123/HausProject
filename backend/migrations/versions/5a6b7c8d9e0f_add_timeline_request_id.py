"""为统一任务时间线增加请求追踪 ID。

Revision ID: 5a6b7c8d9e0f
Revises: 4f5a6b7c8d9e
Create Date: 2026-09-08 20:50:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5a6b7c8d9e0f"
down_revision: Union[str, Sequence[str], None] = "4f5a6b7c8d9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_execution_events",
        sa.Column("request_id", sa.String(length=100), nullable=True),
    )
    op.create_index(
        op.f("ix_task_execution_events_request_id"),
        "task_execution_events",
        ["request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_task_execution_events_request_id"),
        table_name="task_execution_events",
    )
    op.drop_column("task_execution_events", "request_id")
