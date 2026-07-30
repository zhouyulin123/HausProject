"""新增方案版本与报价快照表。

Revision ID: 6c4679cf9722
Revises: 3e9d6b1a7c42
Create Date: 2026-07-30 08:54:42.909508
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6c4679cf9722"
down_revision: Union[str, Sequence[str], None] = "3e9d6b1a7c42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.create_table(
        "design_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("requirement_snapshot", sa.JSON(), nullable=False),
        sa.Column("image_context_snapshot", sa.JSON(), nullable=True),
        sa.Column("generator", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["design_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "version",
            name="uq_design_revisions_task_version",
        ),
    )
    op.create_index(
        op.f("ix_design_revisions_id"),
        "design_revisions",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_design_revisions_task_id"),
        "design_revisions",
        ["task_id"],
        unique=False,
    )
    op.create_table(
        "design_plan_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("plan_key", sa.String(length=50), nullable=False),
        sa.Column("plan_name", sa.String(length=200), nullable=False),
        sa.Column("style", sa.String(length=100), nullable=True),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["design_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_id",
            "plan_key",
            name="uq_design_plan_versions_revision_key",
        ),
    )
    op.create_index(
        op.f("ix_design_plan_versions_id"),
        "design_plan_versions",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_design_plan_versions_revision_id"),
        "design_plan_versions",
        ["revision_id"],
        unique=False,
    )
    op.create_table(
        "quote_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_version_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("furniture_total", sa.Integer(), nullable=False),
        sa.Column("custom_total", sa.Integer(), nullable=False),
        sa.Column("grand_total", sa.Integer(), nullable=False),
        sa.Column("quote_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
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
        op.f("ix_quote_snapshots_id"),
        "quote_snapshots",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quote_snapshots_plan_version_id"),
        "quote_snapshots",
        ["plan_version_id"],
        unique=True,
    )


def downgrade() -> None:
    """回退数据库结构。"""
    op.drop_index(
        op.f("ix_quote_snapshots_plan_version_id"),
        table_name="quote_snapshots",
    )
    op.drop_index(op.f("ix_quote_snapshots_id"), table_name="quote_snapshots")
    op.drop_table("quote_snapshots")
    op.drop_index(
        op.f("ix_design_plan_versions_revision_id"),
        table_name="design_plan_versions",
    )
    op.drop_index(
        op.f("ix_design_plan_versions_id"),
        table_name="design_plan_versions",
    )
    op.drop_table("design_plan_versions")
    op.drop_index(
        op.f("ix_design_revisions_task_id"),
        table_name="design_revisions",
    )
    op.drop_index(op.f("ix_design_revisions_id"), table_name="design_revisions")
    op.drop_table("design_revisions")
