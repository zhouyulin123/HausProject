"""新增开放几何数据库共享滑动窗口限流状态。

Revision ID: d4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-11 18:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "open_geometry_rate_limit_buckets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("attempted_at_json", sa.JSON(), nullable=False),
        sa.Column(
            "record_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "record_version > 0",
            name="ck_open_geometry_rate_limit_record_version",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["anonymous_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["design_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "task_id",
            name="uq_open_geometry_rate_limit_scope",
        ),
    )
    op.create_index(
        op.f("ix_open_geometry_rate_limit_buckets_id"),
        "open_geometry_rate_limit_buckets",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_open_geometry_rate_limit_buckets_session_id"),
        "open_geometry_rate_limit_buckets",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_open_geometry_rate_limit_buckets_task_id"),
        "open_geometry_rate_limit_buckets",
        ["task_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_open_geometry_rate_limit_buckets_task_id"),
        table_name="open_geometry_rate_limit_buckets",
    )
    op.drop_index(
        op.f("ix_open_geometry_rate_limit_buckets_session_id"),
        table_name="open_geometry_rate_limit_buckets",
    )
    op.drop_index(
        op.f("ix_open_geometry_rate_limit_buckets_id"),
        table_name="open_geometry_rate_limit_buckets",
    )
    op.drop_table("open_geometry_rate_limit_buckets")
