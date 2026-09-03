"""新增 LangGraph 节点级持久化检查点。

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-09-03 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "langgraph_checkpoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.String(length=191), nullable=False),
        sa.Column("checkpoint_ns", sa.String(length=191), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=64), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_type", sa.String(length=32), nullable=False),
        sa.Column(
            "checkpoint_blob",
            sa.LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql"),
            nullable=False,
        ),
        sa.Column("metadata_type", sa.String(length=32), nullable=False),
        sa.Column("metadata_blob", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["design_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"],
            ["design_agent_turns.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            name="uq_langgraph_checkpoint_scope_id",
        ),
    )
    op.create_index(
        op.f("ix_langgraph_checkpoints_id"),
        "langgraph_checkpoints",
        ["id"],
    )
    op.create_index(
        op.f("ix_langgraph_checkpoints_task_id"),
        "langgraph_checkpoints",
        ["task_id"],
    )
    op.create_index(
        op.f("ix_langgraph_checkpoints_turn_id"),
        "langgraph_checkpoints",
        ["turn_id"],
    )
    op.create_index(
        op.f("ix_langgraph_checkpoints_thread_id"),
        "langgraph_checkpoints",
        ["thread_id"],
    )
    op.create_index(
        op.f("ix_langgraph_checkpoints_checkpoint_ns"),
        "langgraph_checkpoints",
        ["checkpoint_ns"],
    )

    op.create_table(
        "langgraph_checkpoint_writes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.String(length=191), nullable=False),
        sa.Column("checkpoint_ns", sa.String(length=191), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=64), nullable=False),
        sa.Column("writer_task_id", sa.String(length=191), nullable=False),
        sa.Column(
            "task_path",
            sa.String(length=500),
            server_default="",
            nullable=False,
        ),
        sa.Column("write_index", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=191), nullable=False),
        sa.Column("value_type", sa.String(length=32), nullable=False),
        sa.Column(
            "value_blob",
            sa.LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["design_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"],
            ["design_agent_turns.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "writer_task_id",
            "write_index",
            name="uq_langgraph_checkpoint_write_task_index",
        ),
    )
    op.create_index(
        op.f("ix_langgraph_checkpoint_writes_id"),
        "langgraph_checkpoint_writes",
        ["id"],
    )
    op.create_index(
        op.f("ix_langgraph_checkpoint_writes_task_id"),
        "langgraph_checkpoint_writes",
        ["task_id"],
    )
    op.create_index(
        op.f("ix_langgraph_checkpoint_writes_turn_id"),
        "langgraph_checkpoint_writes",
        ["turn_id"],
    )
    op.create_index(
        op.f("ix_langgraph_checkpoint_writes_thread_id"),
        "langgraph_checkpoint_writes",
        ["thread_id"],
    )
    op.create_index(
        op.f("ix_langgraph_checkpoint_writes_checkpoint_ns"),
        "langgraph_checkpoint_writes",
        ["checkpoint_ns"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_langgraph_checkpoint_writes_checkpoint_ns"),
        table_name="langgraph_checkpoint_writes",
    )
    op.drop_index(
        op.f("ix_langgraph_checkpoint_writes_thread_id"),
        table_name="langgraph_checkpoint_writes",
    )
    op.drop_index(
        op.f("ix_langgraph_checkpoint_writes_turn_id"),
        table_name="langgraph_checkpoint_writes",
    )
    op.drop_index(
        op.f("ix_langgraph_checkpoint_writes_task_id"),
        table_name="langgraph_checkpoint_writes",
    )
    op.drop_index(
        op.f("ix_langgraph_checkpoint_writes_id"),
        table_name="langgraph_checkpoint_writes",
    )
    op.drop_table("langgraph_checkpoint_writes")
    op.drop_index(
        op.f("ix_langgraph_checkpoints_checkpoint_ns"),
        table_name="langgraph_checkpoints",
    )
    op.drop_index(
        op.f("ix_langgraph_checkpoints_thread_id"),
        table_name="langgraph_checkpoints",
    )
    op.drop_index(
        op.f("ix_langgraph_checkpoints_turn_id"),
        table_name="langgraph_checkpoints",
    )
    op.drop_index(
        op.f("ix_langgraph_checkpoints_task_id"),
        table_name="langgraph_checkpoints",
    )
    op.drop_index(
        op.f("ix_langgraph_checkpoints_id"),
        table_name="langgraph_checkpoints",
    )
    op.drop_table("langgraph_checkpoints")
