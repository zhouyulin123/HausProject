"""增加失败簇乐观并发版本号。

Revision ID: 8d9e0f1a2b3c
Revises: 7c8d9e0f1a2b
Create Date: 2026-09-10 10:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8d9e0f1a2b3c"
down_revision: Union[str, Sequence[str], None] = "7c8d9e0f1a2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("failure_clusters") as batch_op:
        batch_op.add_column(
            sa.Column(
                "record_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("failure_clusters") as batch_op:
        batch_op.drop_column("record_version")
