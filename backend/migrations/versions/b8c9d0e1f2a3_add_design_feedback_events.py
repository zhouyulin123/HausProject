"""增加任务级设计反馈事件。

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-02 09:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "design_feedback_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("client_event_id", sa.String(length=100), nullable=False),
        sa.Column("action_type", sa.String(length=30), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_version_id", sa.Integer(), nullable=True),
        sa.Column("scene_id", sa.Integer(), nullable=True),
        sa.Column("scene_version", sa.Integer(), nullable=True),
        sa.Column("room_id", sa.String(length=100), nullable=True),
        sa.Column("instance_id", sa.String(length=100), nullable=True),
        sa.Column("source_sku", sa.String(length=50), nullable=True),
        sa.Column("target_sku", sa.String(length=50), nullable=True),
        sa.Column("satisfaction_score", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["plan_version_id"],
            ["design_plan_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scene_id"],
            ["design_scenes.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["design_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "client_event_id",
            name="uq_design_feedback_task_client_event",
        ),
    )
    for column in (
        "id",
        "task_id",
        "action_type",
        "plan_version_id",
        "scene_id",
        "source_sku",
        "target_sku",
    ):
        op.create_index(
            op.f(f"ix_design_feedback_events_{column}"),
            "design_feedback_events",
            [column],
        )


def downgrade() -> None:
    op.drop_table("design_feedback_events")
