"""增加独立定制家具草稿幂等记录。

Revision ID: ae1f2a3b4c5d
Revises: 9d0e1f2a3b4c
Create Date: 2026-09-02 22:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ae1f2a3b4c5d"
down_revision: Union[str, Sequence[str], None] = "9d0e1f2a3b4c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "custom_furniture_draft_mutations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("client_mutation_id", sa.String(length=100), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["design_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "client_mutation_id",
            name="uq_custom_draft_mutations_task_client_mutation",
        ),
    )
    op.create_index(
        op.f("ix_custom_furniture_draft_mutations_id"),
        "custom_furniture_draft_mutations",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_custom_furniture_draft_mutations_task_id"),
        "custom_furniture_draft_mutations",
        ["task_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_custom_furniture_draft_mutations_task_id"),
        table_name="custom_furniture_draft_mutations",
    )
    op.drop_index(
        op.f("ix_custom_furniture_draft_mutations_id"),
        table_name="custom_furniture_draft_mutations",
    )
    op.drop_table("custom_furniture_draft_mutations")
