"""给 generation_runs 增加生成元数据列：模型/Prompt/输入/输出/用量/成本。

Revision ID: b2e4d6f8a0c1
Revises: a1f3c5e7b9d2
Create Date: 2026-08-19 10:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2e4d6f8a0c1'
down_revision: Union[str, Sequence[str], None] = 'a1f3c5e7b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.add_column('generation_runs', sa.Column('model', sa.String(length=100), nullable=True))
    op.add_column('generation_runs', sa.Column('prompt_snapshot', sa.Text(), nullable=True))
    op.add_column('generation_runs', sa.Column('input_snapshot', sa.JSON(), nullable=True))
    op.add_column('generation_runs', sa.Column('output_snapshot', sa.JSON(), nullable=True))
    op.add_column('generation_runs', sa.Column('usage_json', sa.JSON(), nullable=True))
    op.add_column('generation_runs', sa.Column('cost_cny', sa.Float(), nullable=True))


def downgrade() -> None:
    """回退数据库结构。"""
    op.drop_column('generation_runs', 'cost_cny')
    op.drop_column('generation_runs', 'usage_json')
    op.drop_column('generation_runs', 'output_snapshot')
    op.drop_column('generation_runs', 'input_snapshot')
    op.drop_column('generation_runs', 'prompt_snapshot')
    op.drop_column('generation_runs', 'model')
