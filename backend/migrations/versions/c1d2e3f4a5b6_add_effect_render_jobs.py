"""新增可恢复的效果图生成任务。

Revision ID: c1d2e3f4a5b6
Revises: bf2a3b4c5d6e
Create Date: 2026-09-03 11:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "bf2a3b4c5d6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "effect_render_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("plan_version_id", sa.Integer(), nullable=False),
        sa.Column("source_image_id", sa.Integer(), nullable=True),
        sa.Column("source_image_digest", sa.String(length=71), nullable=True),
        sa.Column("prompt_snapshot", sa.Text(), nullable=False),
        sa.Column("prompt_digest", sa.String(length=71), nullable=False),
        sa.Column("request_digest", sa.String(length=71), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rendered_image_id", sa.Integer(), nullable=True),
        sa.Column("output_url", sa.String(length=500), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plan_version_id"], ["design_plan_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rendered_image_id"], ["rendered_images.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_image_id"], ["uploaded_images.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["design_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rendered_image_id"),
        sa.UniqueConstraint("task_id", "idempotency_key", name="uq_effect_render_jobs_task_idempotency"),
    )
    for column in (
        "id",
        "task_id",
        "plan_version_id",
        "source_image_id",
        "request_id",
        "status",
        "worker_id",
        "lease_expires_at",
        "execution_deadline_at",
        "next_retry_at",
        "dead_lettered_at",
        "rendered_image_id",
    ):
        op.create_index(
            op.f(f"ix_effect_render_jobs_{column}"),
            "effect_render_jobs",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in reversed(
        (
            "id",
            "task_id",
            "plan_version_id",
            "source_image_id",
            "request_id",
            "status",
            "worker_id",
            "lease_expires_at",
            "execution_deadline_at",
            "next_retry_at",
            "dead_lettered_at",
            "rendered_image_id",
        )
    ):
        op.drop_index(op.f(f"ix_effect_render_jobs_{column}"), table_name="effect_render_jobs")
    op.drop_table("effect_render_jobs")
