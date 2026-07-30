"""新增工作流节点轨迹快照。

Revision ID: c19eadef8b8b
Revises: 6c4679cf9722
Create Date: 2026-07-30 09:19:22.757241
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c19eadef8b8b"
down_revision: Union[str, Sequence[str], None] = "6c4679cf9722"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.add_column(
        "design_revisions",
        sa.Column("workflow_trace_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """回退数据库结构。"""
    op.drop_column("design_revisions", "workflow_trace_snapshot")
