"""新增 layout_runs 布局生成元数据表

Revision ID: a1f3c5e7b9d2
Revises: 21b0bc4721d4
Create Date: 2026-08-19 10:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1f3c5e7b9d2'
down_revision: Union[str, Sequence[str], None] = '21b0bc4721d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.create_table(
        'layout_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plan_version_id', sa.Integer(), nullable=False),
        sa.Column('scene_version_id', sa.Integer(), nullable=True),
        sa.Column('room_name', sa.String(length=50), nullable=True),
        sa.Column('room_width_m', sa.Float(), nullable=True),
        sa.Column('room_depth_m', sa.Float(), nullable=True),
        sa.Column('furniture_count', sa.Integer(), nullable=False),
        sa.Column('candidate_count', sa.Integer(), nullable=False),
        sa.Column('best_score', sa.Integer(), nullable=False),
        sa.Column('best_valid', sa.Boolean(), nullable=False),
        sa.Column('issue_codes', sa.JSON(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(
            ['plan_version_id'],
            ['design_plan_versions.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['scene_version_id'],
            ['design_scene_versions.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_layout_runs_id'), 'layout_runs', ['id'], unique=False)
    op.create_index(
        op.f('ix_layout_runs_plan_version_id'),
        'layout_runs',
        ['plan_version_id'],
        unique=False,
    )


def downgrade() -> None:
    """回退数据库结构。"""
    op.drop_index(op.f('ix_layout_runs_plan_version_id'), table_name='layout_runs')
    op.drop_index(op.f('ix_layout_runs_id'), table_name='layout_runs')
    op.drop_table('layout_runs')
