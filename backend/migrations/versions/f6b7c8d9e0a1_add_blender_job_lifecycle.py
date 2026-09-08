"""补全 Blender 渲染作业租约、重试、取消与死信字段。

Revision ID: f6b7c8d9e0a1
Revises: f5a6b7c8d9e0
Create Date: 2026-09-08 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6b7c8d9e0a1"
down_revision: Union[str, Sequence[str], None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "blender_render_jobs",
        sa.Column("max_attempts", sa.Integer(), server_default="2", nullable=False),
    )
    op.add_column(
        "blender_render_jobs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "blender_render_jobs",
        sa.Column(
            "execution_deadline_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE blender_render_jobs "
            "SET execution_deadline_at = CURRENT_TIMESTAMP "
            "WHERE execution_deadline_at IS NULL"
        )
    )
    with op.batch_alter_table("blender_render_jobs") as batch_op:
        batch_op.alter_column(
            "execution_deadline_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    op.add_column(
        "blender_render_jobs",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "blender_render_jobs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "blender_render_jobs",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "blender_render_jobs",
        sa.Column("error_code", sa.String(length=100), nullable=True),
    )
    for column in ("execution_deadline_at", "next_retry_at", "dead_lettered_at"):
        op.create_index(
            op.f(f"ix_blender_render_jobs_{column}"),
            "blender_render_jobs",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("dead_lettered_at", "next_retry_at", "execution_deadline_at"):
        op.drop_index(
            op.f(f"ix_blender_render_jobs_{column}"),
            table_name="blender_render_jobs",
        )
    for column in (
        "dead_lettered_at",
        "cancel_requested_at",
        "next_retry_at",
        "execution_deadline_at",
        "heartbeat_at",
        "max_attempts",
        "error_code",
    ):
        op.drop_column("blender_render_jobs", column)
