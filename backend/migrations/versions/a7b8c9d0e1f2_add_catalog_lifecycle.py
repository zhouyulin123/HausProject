"""增加商品生命周期与版本化报价快照。

Revision ID: a7b8c9d0e1f2
Revises: e6f8a0b2c4d6
Create Date: 2026-09-01 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "e6f8a0b2c4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_list_column(name: str) -> sa.Column:
    # MySQL 不允许 JSON 列使用字符串 DEFAULT；先回填再收紧非空约束。
    return sa.Column(name, sa.JSON(), nullable=True)


def _backfill_json_list(table_name: str, column_name: str) -> None:
    table = sa.table(table_name, sa.column(column_name, sa.JSON()))
    op.execute(
        table.update()
        .where(table.c[column_name].is_(None))
        .values({column_name: []})
    )


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(
            sa.Column("verification_status", sa.String(20), server_default="draft", nullable=False)
        )
        batch_op.add_column(
            sa.Column("availability_status", sa.String(20), server_default="unknown", nullable=False)
        )
        batch_op.add_column(_json_list_column("region_codes"))
        batch_op.add_column(sa.Column("stock_quantity", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("lead_time_days_min", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("lead_time_days_max", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("price_valid_from", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("price_valid_to", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("verified_by", sa.String(100), nullable=True))
        batch_op.add_column(
            sa.Column("data_version", sa.String(100), server_default="draft-v1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("record_version", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(_json_list_column("alternative_skus"))
        batch_op.create_index(op.f("ix_products_verification_status"), ["verification_status"])
        batch_op.create_index(op.f("ix_products_availability_status"), ["availability_status"])
        batch_op.create_index(op.f("ix_products_price_valid_from"), ["price_valid_from"])
        batch_op.create_index(op.f("ix_products_price_valid_to"), ["price_valid_to"])

    _backfill_json_list("products", "region_codes")
    _backfill_json_list("products", "alternative_skus")
    with op.batch_alter_table("products") as batch_op:
        batch_op.alter_column("region_codes", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column("alternative_skus", existing_type=sa.JSON(), nullable=False)

    with op.batch_alter_table("quote_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column("catalog_version", sa.String(100), server_default="legacy", nullable=False)
        )
        batch_op.add_column(
            sa.Column("price_version", sa.String(100), server_default="legacy", nullable=False)
        )
        batch_op.add_column(
            sa.Column("rule_version", sa.String(100), server_default="legacy", nullable=False)
        )
        batch_op.add_column(_json_list_column("sku_versions_json"))

    _backfill_json_list("quote_snapshots", "sku_versions_json")
    with op.batch_alter_table("quote_snapshots") as batch_op:
        batch_op.alter_column("sku_versions_json", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("quote_snapshots") as batch_op:
        batch_op.drop_column("sku_versions_json")
        batch_op.drop_column("rule_version")
        batch_op.drop_column("price_version")
        batch_op.drop_column("catalog_version")

    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_index(op.f("ix_products_price_valid_to"))
        batch_op.drop_index(op.f("ix_products_price_valid_from"))
        batch_op.drop_index(op.f("ix_products_availability_status"))
        batch_op.drop_index(op.f("ix_products_verification_status"))
        for column in (
            "alternative_skus",
            "record_version",
            "data_version",
            "verified_by",
            "verified_at",
            "price_valid_to",
            "price_valid_from",
            "lead_time_days_max",
            "lead_time_days_min",
            "stock_quantity",
            "region_codes",
            "availability_status",
            "verification_status",
        ):
            batch_op.drop_column(column)
