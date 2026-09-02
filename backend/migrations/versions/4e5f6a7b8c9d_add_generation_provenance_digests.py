"""add generation provenance digests

Revision ID: 4e5f6a7b8c9d
Revises: 3d4e5f6a7b8c
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4e5f6a7b8c9d"
down_revision: Union[str, Sequence[str], None] = "3d4e5f6a7b8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generation_runs",
        sa.Column("prompt_digest", sa.String(length=71), nullable=True),
    )
    op.add_column(
        "generation_runs",
        sa.Column("rules_digest", sa.String(length=71), nullable=True),
    )
    op.add_column(
        "generation_runs",
        sa.Column("data_digest", sa.String(length=71), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_runs", "data_digest")
    op.drop_column("generation_runs", "rules_digest")
    op.drop_column("generation_runs", "prompt_digest")
