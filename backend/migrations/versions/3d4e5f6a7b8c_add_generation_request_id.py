"""给方案生成运行增加请求关联 ID。

Revision ID: 3d4e5f6a7b8c
Revises: 1a2b3c4d5e6f
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3d4e5f6a7b8c"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generation_runs",
        sa.Column("request_id", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_generation_runs_request_id",
        "generation_runs",
        ["request_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generation_runs_request_id",
        table_name="generation_runs",
    )
    op.drop_column("generation_runs", "request_id")
