"""效果图任务绑定不可变场景快照。

Revision ID: 0b1c2d3e4f5a
Revises: f6b7c8d9e0a1
Create Date: 2026-09-08 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0b1c2d3e4f5a"
down_revision: Union[str, Sequence[str], None] = "f6b7c8d9e0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "effect_render_jobs",
        sa.Column("scene_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "effect_render_jobs",
        sa.Column("scene_version_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "effect_render_jobs",
        sa.Column("scene_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "effect_render_jobs",
        sa.Column("scene_snapshot_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "effect_render_jobs",
        sa.Column("scene_digest", sa.String(length=71), nullable=True),
    )
    op.add_column(
        "rendered_images",
        sa.Column("scene_version_id", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("effect_render_jobs") as batch_op:
        batch_op.create_foreign_key(
            "fk_effect_render_jobs_scene_id",
            "design_scenes",
            ["scene_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_effect_render_jobs_scene_version_id",
            "design_scene_versions",
            ["scene_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("rendered_images") as batch_op:
        batch_op.create_foreign_key(
            "fk_rendered_images_scene_version_id",
            "design_scene_versions",
            ["scene_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        op.f("ix_effect_render_jobs_scene_id"),
        "effect_render_jobs",
        ["scene_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_effect_render_jobs_scene_version_id"),
        "effect_render_jobs",
        ["scene_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rendered_images_scene_version_id"),
        "rendered_images",
        ["scene_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_rendered_images_scene_version_id"),
        table_name="rendered_images",
    )
    op.drop_index(
        op.f("ix_effect_render_jobs_scene_version_id"),
        table_name="effect_render_jobs",
    )
    op.drop_index(
        op.f("ix_effect_render_jobs_scene_id"),
        table_name="effect_render_jobs",
    )
    with op.batch_alter_table("rendered_images") as batch_op:
        batch_op.drop_constraint(
            "fk_rendered_images_scene_version_id",
            type_="foreignkey",
        )
    with op.batch_alter_table("effect_render_jobs") as batch_op:
        batch_op.drop_constraint(
            "fk_effect_render_jobs_scene_version_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_effect_render_jobs_scene_id",
            type_="foreignkey",
        )
    op.drop_column("rendered_images", "scene_version_id")
    op.drop_column("effect_render_jobs", "scene_digest")
    op.drop_column("effect_render_jobs", "scene_snapshot_json")
    op.drop_column("effect_render_jobs", "scene_version")
    op.drop_column("effect_render_jobs", "scene_version_id")
    op.drop_column("effect_render_jobs", "scene_id")
