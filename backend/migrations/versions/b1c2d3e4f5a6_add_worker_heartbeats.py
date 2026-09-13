"""增加异步 Worker 进程心跳。

Revision ID: b1c2d3e4f5a6
Revises: a0f1b2c3d4e5
Create Date: 2026-09-11 11:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a0f1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_type", sa.String(length=30), nullable=False),
        sa.Column("worker_id", sa.String(length=200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "worker_type",
            "worker_id",
            name="uq_worker_heartbeats_type_identity",
        ),
    )
    op.create_index(
        "ix_worker_heartbeats_worker_type",
        "worker_heartbeats",
        ["worker_type"],
    )
    op.create_index(
        "ix_worker_heartbeats_heartbeat_at",
        "worker_heartbeats",
        ["heartbeat_at"],
    )
    op.create_index(
        "ix_worker_heartbeats_stopped_at",
        "worker_heartbeats",
        ["stopped_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_worker_heartbeats_stopped_at",
        table_name="worker_heartbeats",
    )
    op.drop_index(
        "ix_worker_heartbeats_heartbeat_at",
        table_name="worker_heartbeats",
    )
    op.drop_index(
        "ix_worker_heartbeats_worker_type",
        table_name="worker_heartbeats",
    )
    op.drop_table("worker_heartbeats")
