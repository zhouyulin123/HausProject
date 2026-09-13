"""模型调用成本字段改为定点小数。

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-11 15:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ACCOUNT_COLUMNS = (
    "cost_limit_cny",
    "allocated_cost_cny",
    "actual_cost_cny",
)
_LEDGER_COLUMNS = ("estimated_cost_cny", "actual_cost_cny")


def _alter_cost_columns(
    table_name: str,
    column_names: tuple[str, ...],
    *,
    source_type: sa.types.TypeEngine,
    target_type: sa.types.TypeEngine,
) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        for column_name in column_names:
            batch_op.alter_column(
                column_name,
                existing_type=source_type,
                type_=target_type,
                existing_nullable=(table_name == "model_call_ledgers"),
            )


def upgrade() -> None:
    decimal_type = sa.Numeric(precision=18, scale=6)
    _alter_cost_columns(
        "model_call_cost_accounts",
        _ACCOUNT_COLUMNS,
        source_type=sa.Float(),
        target_type=decimal_type,
    )
    _alter_cost_columns(
        "model_call_ledgers",
        _LEDGER_COLUMNS,
        source_type=sa.Float(),
        target_type=decimal_type,
    )


def downgrade() -> None:
    decimal_type = sa.Numeric(precision=18, scale=6)
    _alter_cost_columns(
        "model_call_ledgers",
        _LEDGER_COLUMNS,
        source_type=decimal_type,
        target_type=sa.Float(),
    )
    _alter_cost_columns(
        "model_call_cost_accounts",
        _ACCOUNT_COLUMNS,
        source_type=decimal_type,
        target_type=sa.Float(),
    )
