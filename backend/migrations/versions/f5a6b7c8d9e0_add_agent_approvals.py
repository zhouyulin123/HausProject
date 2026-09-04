"""新增 Agent 人工审批请求与决定记录。

Revision ID: f5a6b7c8d9e0
Revises: f4a5b6c7d8e9
Create Date: 2026-09-04 10:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("approval_type", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("request_context_json", sa.JSON(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("client_decision_id", sa.String(length=100), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("decided_by_type", sa.String(length=30), nullable=True),
        sa.Column("decided_by_id", sa.String(length=100), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "approval_type IN ('quote_review', 'construction_risk', 'quality_gate')",
            name="ck_agent_approvals_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_agent_approvals_status",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('approve', 'reject')",
            name="ck_agent_approvals_decision",
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
            "turn_id",
            "approval_type",
            name="uq_agent_approvals_turn_type",
        ),
        sa.UniqueConstraint(
            "task_id",
            "client_decision_id",
            name="uq_agent_approvals_task_client_decision",
        ),
    )
    for column in (
        "task_id",
        "turn_id",
        "approval_type",
        "status",
        "reason_code",
        "requested_at",
        "decided_by_id",
        "decided_at",
    ):
        op.create_index(
            op.f(f"ix_agent_approvals_{column}"),
            "agent_approvals",
            [column],
        )


def downgrade() -> None:
    for column in reversed(
        (
            "task_id",
            "turn_id",
            "approval_type",
            "status",
            "reason_code",
            "requested_at",
            "decided_by_id",
            "decided_at",
        )
    ):
        op.drop_index(
            op.f(f"ix_agent_approvals_{column}"),
            table_name="agent_approvals",
        )
    op.drop_table("agent_approvals")
