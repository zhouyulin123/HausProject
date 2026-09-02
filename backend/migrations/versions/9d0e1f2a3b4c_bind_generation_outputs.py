"""绑定生成运行与不可变方案输出。

Revision ID: 9d0e1f2a3b4c
Revises: 8c9d0e1f2a3b
Create Date: 2026-09-02 23:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d0e1f2a3b4c"
down_revision: Union[str, Sequence[str], None] = "8c9d0e1f2a3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("generation_runs") as batch_op:
        batch_op.add_column(
            sa.Column("result_revision_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("output_digest", sa.String(length=71), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_generation_runs_result_revision",
            "design_revisions",
            ["result_revision_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint(
            "uq_generation_runs_result_revision",
            ["result_revision_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_runs") as batch_op:
        batch_op.drop_constraint(
            "uq_generation_runs_result_revision",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_generation_runs_result_revision",
            type_="foreignkey",
        )
        batch_op.drop_column("output_digest")
        batch_op.drop_column("result_revision_id")
