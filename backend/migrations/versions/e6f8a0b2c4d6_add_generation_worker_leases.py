"""给方案生成任务增加 Worker 租约、重试、取消与幂等字段。

Revision ID: e6f8a0b2c4d6
Revises: f1a2b3c4d5e6
Create Date: 2026-09-01 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f8a0b2c4d6"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("generation_runs") as batch_op:
        batch_op.add_column(sa.Column("worker_id", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "attempt_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "max_attempts",
                sa.Integer(),
                server_default="3",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("idempotency_key", sa.String(length=100), nullable=True)
        )
        batch_op.create_index(
            op.f("ix_generation_runs_worker_id"), ["worker_id"], unique=False
        )
        batch_op.create_index(
            op.f("ix_generation_runs_lease_expires_at"),
            ["lease_expires_at"],
            unique=False,
        )
        batch_op.create_index(
            op.f("ix_generation_runs_next_retry_at"),
            ["next_retry_at"],
            unique=False,
        )
        batch_op.create_unique_constraint(
            "uq_generation_runs_task_idempotency", ["task_id", "idempotency_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_runs") as batch_op:
        batch_op.drop_constraint(
            "uq_generation_runs_task_idempotency", type_="unique"
        )
        batch_op.drop_index(op.f("ix_generation_runs_next_retry_at"))
        batch_op.drop_index(op.f("ix_generation_runs_lease_expires_at"))
        batch_op.drop_index(op.f("ix_generation_runs_worker_id"))
        for column in (
            "idempotency_key",
            "cancel_requested_at",
            "max_attempts",
            "attempt_count",
            "next_retry_at",
            "heartbeat_at",
            "lease_expires_at",
            "worker_id",
        ):
            batch_op.drop_column(column)
