"""给方案生成任务增加硬执行截止时间与死信时间。

Revision ID: f2b3c4d5e6f7
Revises: d0e1f2a3b4c5
Create Date: 2026-09-02 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("generation_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "execution_deadline_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "dead_lettered_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_index(
            op.f("ix_generation_runs_execution_deadline_at"),
            ["execution_deadline_at"],
            unique=False,
        )
        batch_op.create_index(
            op.f("ix_generation_runs_dead_lettered_at"),
            ["dead_lettered_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_runs") as batch_op:
        batch_op.drop_index(op.f("ix_generation_runs_dead_lettered_at"))
        batch_op.drop_index(op.f("ix_generation_runs_execution_deadline_at"))
        batch_op.drop_column("dead_lettered_at")
        batch_op.drop_column("execution_deadline_at")
