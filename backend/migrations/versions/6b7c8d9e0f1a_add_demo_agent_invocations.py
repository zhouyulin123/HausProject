"""增加公开 Demo 模型调用的幂等成本账本。

Revision ID: 6b7c8d9e0f1a
Revises: 5a6b7c8d9e0f
Create Date: 2026-09-08 22:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6b7c8d9e0f1a"
down_revision: Union[str, Sequence[str], None] = "5a6b7c8d9e0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "demo_agent_invocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("operation_key", sa.String(length=71), nullable=False),
        sa.Column("request_digest", sa.String(length=71), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("billing_status", sa.String(length=20), nullable=False),
        sa.Column("cost_cny", sa.Float(), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["anonymous_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "operation_key",
            name="uq_demo_agent_invocations_session_operation",
        ),
    )
    op.create_index(
        op.f("ix_demo_agent_invocations_id"),
        "demo_agent_invocations",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_demo_agent_invocations_session_id"),
        "demo_agent_invocations",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_demo_agent_invocations_status"),
        "demo_agent_invocations",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_demo_agent_invocations_request_id"),
        "demo_agent_invocations",
        ["request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_demo_agent_invocations_request_id"),
        table_name="demo_agent_invocations",
    )
    op.drop_index(
        op.f("ix_demo_agent_invocations_status"),
        table_name="demo_agent_invocations",
    )
    op.drop_index(
        op.f("ix_demo_agent_invocations_session_id"),
        table_name="demo_agent_invocations",
    )
    op.drop_index(
        op.f("ix_demo_agent_invocations_id"),
        table_name="demo_agent_invocations",
    )
    op.drop_table("demo_agent_invocations")
