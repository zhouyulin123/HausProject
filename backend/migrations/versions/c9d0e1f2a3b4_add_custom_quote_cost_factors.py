"""增加定制报价地区与确定性费用因子。

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-02 10:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_list_column(name: str) -> sa.Column:
    # MySQL 不允许 JSON 列使用字符串 DEFAULT；先回填再收紧非空约束。
    return sa.Column(name, sa.JSON(), nullable=True)


def upgrade() -> None:
    with op.batch_alter_table("custom_quote_rules") as batch_op:
        batch_op.add_column(_json_list_column("region_codes"))
        batch_op.add_column(
            sa.Column("waste_rate_bps", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("minimum_quantity", sa.Float(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("installation_fee", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("shipping_fee", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("tax_rate_bps", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "data_version",
                sa.String(length=100),
                server_default="draft-v1",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("record_version", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_custom_quote_rules_waste_rate_bps",
            "waste_rate_bps >= 0 AND waste_rate_bps <= 10000",
        )
        batch_op.create_check_constraint(
            "ck_custom_quote_rules_minimum_quantity",
            "minimum_quantity >= 0",
        )
        batch_op.create_check_constraint(
            "ck_custom_quote_rules_installation_fee",
            "installation_fee >= 0",
        )
        batch_op.create_check_constraint(
            "ck_custom_quote_rules_shipping_fee",
            "shipping_fee >= 0",
        )
        batch_op.create_check_constraint(
            "ck_custom_quote_rules_tax_rate_bps",
            "tax_rate_bps >= 0 AND tax_rate_bps <= 10000",
        )
        batch_op.create_check_constraint(
            "ck_custom_quote_rules_record_version",
            "record_version >= 1",
        )

    table = sa.table("custom_quote_rules", sa.column("region_codes", sa.JSON()))
    op.execute(
        table.update()
        .where(table.c.region_codes.is_(None))
        .values(region_codes=[])
    )
    with op.batch_alter_table("custom_quote_rules") as batch_op:
        batch_op.alter_column(
            "region_codes",
            existing_type=sa.JSON(),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("custom_quote_rules") as batch_op:
        for name in (
            "ck_custom_quote_rules_record_version",
            "ck_custom_quote_rules_tax_rate_bps",
            "ck_custom_quote_rules_shipping_fee",
            "ck_custom_quote_rules_installation_fee",
            "ck_custom_quote_rules_minimum_quantity",
            "ck_custom_quote_rules_waste_rate_bps",
        ):
            batch_op.drop_constraint(name, type_="check")
        for column in (
            "record_version",
            "data_version",
            "tax_rate_bps",
            "shipping_fee",
            "installation_fee",
            "minimum_quantity",
            "waste_rate_bps",
            "region_codes",
        ):
            batch_op.drop_column(column)
