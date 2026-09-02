"""冻结生成运行逐方案场景证据。

Revision ID: ad0e1f2a3b4c
Revises: ae1f2a3b4c5d
Create Date: 2026-09-02 23:50:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ad0e1f2a3b4c"
down_revision: Union[str, Sequence[str], None] = "ae1f2a3b4c5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_run_scene_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generation_run_id", sa.Integer(), nullable=False),
        sa.Column("plan_version_id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Integer(), nullable=False),
        sa.Column("scene_version_id", sa.Integer(), nullable=False),
        sa.Column("scene_version", sa.Integer(), nullable=False),
        sa.Column("scene_digest", sa.String(length=71), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["generation_run_id"],
            ["generation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_version_id"],
            ["design_plan_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scene_id"],
            ["design_scenes.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scene_version_id"],
            ["design_scene_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_run_id",
            "plan_version_id",
            name="uq_generation_run_scene_plan",
        ),
        sa.UniqueConstraint(
            "generation_run_id",
            "scene_id",
            name="uq_generation_run_scene",
        ),
    )
    op.create_index(
        op.f("ix_generation_run_scene_evidence_id"),
        "generation_run_scene_evidence",
        ["id"],
        unique=False,
    )
    for column in (
        "generation_run_id",
        "plan_version_id",
        "scene_id",
        "scene_version_id",
    ):
        op.create_index(
            op.f(f"ix_generation_run_scene_evidence_{column}"),
            "generation_run_scene_evidence",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("generation_run_scene_evidence")
