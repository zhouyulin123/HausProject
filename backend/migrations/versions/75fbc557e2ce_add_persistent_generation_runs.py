"""新增持久化生成任务与节点事件表。

Revision ID: 75fbc557e2ce
Revises: c19eadef8b8b
Create Date: 2026-07-30 10:15:54.126359
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "75fbc557e2ce"
down_revision: Union[str, Sequence[str], None] = "c19eadef8b8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.create_table(
        "generation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("current_node", sa.String(length=50), nullable=True),
        sa.Column("generator", sa.String(length=20), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["design_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "attempt",
            name="uq_generation_runs_task_attempt",
        ),
    )
    op.create_index(
        op.f("ix_generation_runs_id"),
        "generation_runs",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generation_runs_status"),
        "generation_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generation_runs_task_id"),
        "generation_runs",
        ["task_id"],
        unique=False,
    )
    op.create_table(
        "generation_run_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["generation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_generation_run_events_id"),
        "generation_run_events",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generation_run_events_run_id"),
        "generation_run_events",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    """回退数据库结构。"""
    op.drop_index(
        op.f("ix_generation_run_events_run_id"),
        table_name="generation_run_events",
    )
    op.drop_index(
        op.f("ix_generation_run_events_id"),
        table_name="generation_run_events",
    )
    op.drop_table("generation_run_events")
    op.drop_index(
        op.f("ix_generation_runs_task_id"),
        table_name="generation_runs",
    )
    op.drop_index(
        op.f("ix_generation_runs_status"),
        table_name="generation_runs",
    )
    op.drop_index(
        op.f("ix_generation_runs_id"),
        table_name="generation_runs",
    )
    op.drop_table("generation_runs")
