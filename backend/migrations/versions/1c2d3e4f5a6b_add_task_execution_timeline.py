"""新增统一任务执行时间线。

Revision ID: 1c2d3e4f5a6b
Revises: 0b1c2d3e4f5a
Create Date: 2026-09-08 20:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1c2d3e4f5a6b"
down_revision: Union[str, Sequence[str], None] = "0b1c2d3e4f5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_execution_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("event_code", sa.String(length=50), nullable=False),
        sa.Column("billing_status", sa.String(length=20), nullable=False),
        sa.Column("cost_cny", sa.Float(), nullable=True),
        sa.Column("event_key", sa.String(length=150), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["design_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_key", name="uq_task_execution_events_event_key"
        ),
    )
    for column in (
        "id",
        "task_id",
        "source_type",
        "event_code",
        "billing_status",
        "occurred_at",
    ):
        op.create_index(
            op.f(f"ix_task_execution_events_{column}"),
            "task_execution_events",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in reversed(
        (
            "id",
            "task_id",
            "source_type",
            "event_code",
            "billing_status",
            "occurred_at",
        )
    ):
        op.drop_index(
            op.f(f"ix_task_execution_events_{column}"),
            table_name="task_execution_events",
        )
    op.drop_table("task_execution_events")
