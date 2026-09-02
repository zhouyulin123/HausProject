"""给方案生成任务增加成本上限与预留账本。

Revision ID: 1a2b3c4d5e6f
Revises: 0a1b2c3d4e5f
Create Date: 2026-09-02 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "0a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("generation_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "cost_reserved_cny",
                sa.Float(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("cost_limit_cny", sa.Float(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_runs") as batch_op:
        batch_op.drop_column("cost_limit_cny")
        batch_op.drop_column("cost_reserved_cny")
