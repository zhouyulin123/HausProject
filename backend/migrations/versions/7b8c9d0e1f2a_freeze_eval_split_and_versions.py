"""冻结评测分组与执行前生成版本。

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2026-09-02 22:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b8c9d0e1f2a"
down_revision: Union[str, Sequence[str], None] = "6a7b8c9d0e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in (
        sa.Column("dataset_split", sa.String(length=20), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_digest", sa.String(length=71), nullable=True),
        sa.Column("rules_digest", sa.String(length=71), nullable=True),
        sa.Column("data_digest", sa.String(length=71), nullable=True),
        sa.Column("input_digest", sa.String(length=71), nullable=True),
        sa.Column("provenance_schema_version", sa.Integer(), nullable=True),
    ):
        op.add_column("evaluation_run_bindings", column)


def downgrade() -> None:
    for column_name in (
        "provenance_schema_version",
        "input_digest",
        "data_digest",
        "rules_digest",
        "prompt_digest",
        "model",
        "dataset_split",
    ):
        op.drop_column("evaluation_run_bindings", column_name)
