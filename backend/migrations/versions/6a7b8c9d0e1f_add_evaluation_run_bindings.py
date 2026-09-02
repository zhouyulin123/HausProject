"""增加评测运行输入绑定与完整生成来源摘要。

Revision ID: 6a7b8c9d0e1f
Revises: 5f6a7b8c9d0e
Create Date: 2026-09-02 20:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a7b8c9d0e1f"
down_revision: Union[str, Sequence[str], None] = "5f6a7b8c9d0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "uploaded_images",
        sa.Column("content_digest", sa.String(length=71), nullable=True),
    )
    op.add_column(
        "generation_runs",
        sa.Column("input_digest", sa.String(length=71), nullable=True),
    )
    op.add_column(
        "generation_runs",
        sa.Column("provenance_schema_version", sa.Integer(), nullable=True),
    )
    op.create_table(
        "evaluation_run_bindings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generation_run_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("case_fingerprint", sa.String(length=71), nullable=False),
        sa.Column("asset_digest", sa.String(length=71), nullable=False),
        sa.Column("task_input_digest", sa.String(length=71), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["generation_run_id"],
            ["generation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["design_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_run_id"),
    )
    op.create_index(
        "ix_evaluation_run_bindings_generation_run_id",
        "evaluation_run_bindings",
        ["generation_run_id"],
        unique=True,
    )
    op.create_index(
        "ix_evaluation_run_bindings_task_id",
        "evaluation_run_bindings",
        ["task_id"],
    )
    op.create_index(
        "ix_evaluation_run_bindings_case_fingerprint",
        "evaluation_run_bindings",
        ["case_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluation_run_bindings_case_fingerprint",
        table_name="evaluation_run_bindings",
    )
    op.drop_index(
        "ix_evaluation_run_bindings_task_id",
        table_name="evaluation_run_bindings",
    )
    op.drop_index(
        "ix_evaluation_run_bindings_generation_run_id",
        table_name="evaluation_run_bindings",
    )
    op.drop_table("evaluation_run_bindings")
    op.drop_column("generation_runs", "provenance_schema_version")
    op.drop_column("generation_runs", "input_digest")
    op.drop_column("uploaded_images", "content_digest")
