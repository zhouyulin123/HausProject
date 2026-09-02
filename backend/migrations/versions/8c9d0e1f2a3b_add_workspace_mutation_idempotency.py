"""增加工作台方案与场景变更幂等键。

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
Create Date: 2026-09-02 21:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c9d0e1f2a3b"
down_revision: Union[str, Sequence[str], None] = "7b8c9d0e1f2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("design_revisions") as batch_op:
        batch_op.add_column(
            sa.Column("client_mutation_id", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("mutation_digest", sa.String(length=64), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_design_revisions_task_client_mutation",
            ["task_id", "client_mutation_id"],
        )
    with op.batch_alter_table("design_scene_versions") as batch_op:
        batch_op.add_column(
            sa.Column("client_mutation_id", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("mutation_digest", sa.String(length=64), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_scene_versions_scene_client_mutation",
            ["scene_id", "client_mutation_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("design_scene_versions") as batch_op:
        batch_op.drop_constraint(
            "uq_scene_versions_scene_client_mutation",
            type_="unique",
        )
        batch_op.drop_column("mutation_digest")
        batch_op.drop_column("client_mutation_id")
    with op.batch_alter_table("design_revisions") as batch_op:
        batch_op.drop_constraint(
            "uq_design_revisions_task_client_mutation",
            type_="unique",
        )
        batch_op.drop_column("mutation_digest")
        batch_op.drop_column("client_mutation_id")
