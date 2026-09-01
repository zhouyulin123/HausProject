"""新增统一设计智能体检查点、幂等 turn 与事件。

Revision ID: f1a2b3c4d5e6
Revises: d5e7f9a1b3c4
Create Date: 2026-09-01 16:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "d5e7f9a1b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "design_tasks",
        sa.Column("agent_state_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "design_tasks",
        sa.Column(
            "agent_state_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "design_tasks",
        sa.Column(
            "active_mode",
            sa.String(length=30),
            server_default="catalog_design",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_design_tasks_active_mode",
        "design_tasks",
        ["active_mode"],
    )

    op.create_table(
        "design_agent_turns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("client_turn_id", sa.String(length=100), nullable=False),
        sa.Column("active_mode", sa.String(length=30), nullable=False),
        sa.Column(
            "intent",
            sa.String(length=50),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="running",
            nullable=False,
        ),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id"], ["design_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "client_turn_id",
            name="uq_design_agent_turns_task_client_turn",
        ),
    )
    op.create_index("ix_design_agent_turns_id", "design_agent_turns", ["id"])
    op.create_index(
        "ix_design_agent_turns_task_id", "design_agent_turns", ["task_id"]
    )
    op.create_index(
        "ix_design_agent_turns_status", "design_agent_turns", ["status"]
    )

    op.create_table(
        "design_agent_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("node", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["design_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["design_agent_turns.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "turn_id",
            "sequence",
            name="uq_design_agent_events_turn_sequence",
        ),
    )
    op.create_index("ix_design_agent_events_id", "design_agent_events", ["id"])
    op.create_index(
        "ix_design_agent_events_task_id", "design_agent_events", ["task_id"]
    )
    op.create_index(
        "ix_design_agent_events_turn_id", "design_agent_events", ["turn_id"]
    )

def downgrade() -> None:
    op.drop_index("ix_design_agent_events_turn_id", table_name="design_agent_events")
    op.drop_index("ix_design_agent_events_task_id", table_name="design_agent_events")
    op.drop_index("ix_design_agent_events_id", table_name="design_agent_events")
    op.drop_table("design_agent_events")
    op.drop_index("ix_design_agent_turns_status", table_name="design_agent_turns")
    op.drop_index("ix_design_agent_turns_task_id", table_name="design_agent_turns")
    op.drop_index("ix_design_agent_turns_id", table_name="design_agent_turns")
    op.drop_table("design_agent_turns")
    op.drop_index("ix_design_tasks_active_mode", table_name="design_tasks")
    op.drop_column("design_tasks", "active_mode")
    op.drop_column("design_tasks", "agent_state_version")
    op.drop_column("design_tasks", "agent_state_json")
