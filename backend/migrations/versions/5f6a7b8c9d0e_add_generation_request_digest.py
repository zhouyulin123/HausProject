"""增加生成请求幂等输入摘要。

Revision ID: 5f6a7b8c9d0e
Revises: 2b3c4d5e6f7a
Create Date: 2026-09-02 16:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5f6a7b8c9d0e"
down_revision: Union[str, Sequence[str], None] = "2b3c4d5e6f7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generation_runs",
        sa.Column("request_digest", sa.String(length=71), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_runs", "request_digest")
