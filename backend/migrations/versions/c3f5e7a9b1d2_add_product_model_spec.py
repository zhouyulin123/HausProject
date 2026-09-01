"""给 products 增加 3D 建模真实参数列 model_spec_json。

Revision ID: c3f5e7a9b1d2
Revises: b2e4d6f8a0c1
Create Date: 2026-08-21 14:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3f5e7a9b1d2'
down_revision: Union[str, Sequence[str], None] = 'b2e4d6f8a0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.add_column('products', sa.Column('model_spec_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    """回退数据库结构。"""
    op.drop_column('products', 'model_spec_json')
