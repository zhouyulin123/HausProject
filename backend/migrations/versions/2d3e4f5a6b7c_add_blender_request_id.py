"""为 Blender 渲染作业增加请求关联 ID。

Revision ID: 2d3e4f5a6b7c
Revises: 1c2d3e4f5a6b
Create Date: 2026-09-08 19:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2d3e4f5a6b7c"
down_revision: Union[str, Sequence[str], None] = "1c2d3e4f5a6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "blender_render_jobs",
        sa.Column("request_id", sa.String(length=100), nullable=True),
    )
    op.create_index(
        op.f("ix_blender_render_jobs_request_id"),
        "blender_render_jobs",
        ["request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_blender_render_jobs_request_id"),
        table_name="blender_render_jobs",
    )
    op.drop_column("blender_render_jobs", "request_id")
