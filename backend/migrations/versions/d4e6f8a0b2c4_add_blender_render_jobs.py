"""新增 Blender Worker 渲染作业表。

Revision ID: d4e6f8a0b2c4
Revises: b7d9e1f3a5c8
Create Date: 2026-07-31 17:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e6f8a0b2c4"
down_revision: Union[str, Sequence[str], None] = "b7d9e1f3a5c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "blender_render_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Integer(), nullable=False),
        sa.Column("scene_version_id", sa.Integer(), nullable=False),
        sa.Column("scene_version", sa.Integer(), nullable=False),
        sa.Column("profile", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_url", sa.String(length=500), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["scene_id"],
            ["design_scenes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scene_version_id"],
            ["design_scene_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scene_version_id",
            "profile",
            name="uq_blender_render_jobs_version_profile",
        ),
    )
    for column in (
        "id",
        "scene_id",
        "scene_version_id",
        "status",
        "worker_id",
        "lease_expires_at",
    ):
        op.create_index(
            op.f(f"ix_blender_render_jobs_{column}"),
            "blender_render_jobs",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in (
        "lease_expires_at",
        "worker_id",
        "status",
        "scene_version_id",
        "scene_id",
        "id",
    ):
        op.drop_index(
            op.f(f"ix_blender_render_jobs_{column}"),
            table_name="blender_render_jobs",
        )
    op.drop_table("blender_render_jobs")
