"""效果图绑定不可变方案版本。

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2c3d4e5f6a7b"
down_revision: Union[str, Sequence[str], None] = "1b2c3d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("rendered_images") as batch_op:
        batch_op.add_column(
            sa.Column("plan_version_id", sa.Integer(), nullable=True),
        )
        batch_op.create_foreign_key(
            "fk_rendered_images_plan_version_id",
            "design_plan_versions",
            ["plan_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_rendered_images_plan_version_id",
        "rendered_images",
        ["plan_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rendered_images_plan_version_id",
        table_name="rendered_images",
    )
    with op.batch_alter_table("rendered_images") as batch_op:
        batch_op.drop_constraint(
            "fk_rendered_images_plan_version_id",
            type_="foreignkey",
        )
        batch_op.drop_column("plan_version_id")
