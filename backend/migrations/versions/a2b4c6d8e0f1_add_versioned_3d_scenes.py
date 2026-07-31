"""新增版本化 3D 场景表。

Revision ID: a2b4c6d8e0f1
Revises: 75fbc557e2ce
Create Date: 2026-07-31 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b4c6d8e0f1"
down_revision: Union[str, Sequence[str], None] = "75fbc557e2ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.create_table(
        "design_scenes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_version_id", sa.Integer(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["plan_version_id"],
            ["design_plan_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_design_scenes_id"),
        "design_scenes",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_design_scenes_plan_version_id"),
        "design_scenes",
        ["plan_version_id"],
        unique=True,
    )

    op.create_table(
        "design_scene_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scene_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["scene_id"],
            ["design_scenes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scene_id",
            "version",
            name="uq_design_scene_versions_scene_version",
        ),
    )
    op.create_index(
        op.f("ix_design_scene_versions_id"),
        "design_scene_versions",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_design_scene_versions_scene_id"),
        "design_scene_versions",
        ["scene_id"],
        unique=False,
    )


def downgrade() -> None:
    """回退数据库结构。"""
    op.drop_index(
        op.f("ix_design_scene_versions_scene_id"),
        table_name="design_scene_versions",
    )
    op.drop_index(
        op.f("ix_design_scene_versions_id"),
        table_name="design_scene_versions",
    )
    op.drop_table("design_scene_versions")
    op.drop_index(
        op.f("ix_design_scenes_plan_version_id"),
        table_name="design_scenes",
    )
    op.drop_index(op.f("ix_design_scenes_id"), table_name="design_scenes")
    op.drop_table("design_scenes")
