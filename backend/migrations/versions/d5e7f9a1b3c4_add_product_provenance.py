"""给商品增加公开数据来源与价格观测字段。

Revision ID: d5e7f9a1b3c4
Revises: c3f5e7a9b1d2
Create Date: 2026-08-30 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e7f9a1b3c4"
down_revision: Union[str, Sequence[str], None] = "c3f5e7a9b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增溯源字段；既有数据标为 unknown，避免虚构来源。"""
    op.add_column(
        "products",
        sa.Column(
            "data_origin",
            sa.String(length=30),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.add_column("products", sa.Column("source_name", sa.String(length=100)))
    op.add_column("products", sa.Column("source_url", sa.String(length=500)))
    op.add_column("products", sa.Column("source_product_id", sa.String(length=100)))
    op.add_column("products", sa.Column("source_retrieved_at", sa.DateTime(timezone=True)))
    op.add_column("products", sa.Column("price_observed_at", sa.DateTime(timezone=True)))
    op.add_column("products", sa.Column("price_note", sa.String(length=500)))
    op.add_column("products", sa.Column("source_metadata", sa.JSON()))
    op.create_index("ix_products_data_origin", "products", ["data_origin"])


def downgrade() -> None:
    """移除商品溯源字段。"""
    op.drop_index("ix_products_data_origin", table_name="products")
    op.drop_column("products", "source_metadata")
    op.drop_column("products", "price_note")
    op.drop_column("products", "price_observed_at")
    op.drop_column("products", "source_retrieved_at")
    op.drop_column("products", "source_product_id")
    op.drop_column("products", "source_url")
    op.drop_column("products", "source_name")
    op.drop_column("products", "data_origin")
