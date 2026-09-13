"""增加统一模型调用成本账户和逐次账本。

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-11 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_call_cost_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_kind", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=100), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("cost_limit_cny", sa.Float(), nullable=False),
        sa.Column(
            "allocated_cost_cny",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "actual_cost_cny",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "unknown_cost_call_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "scope_kind IN ('task', 'session')",
            name="ck_model_call_cost_account_scope_kind",
        ),
        sa.CheckConstraint(
            "cost_limit_cny > 0",
            name="ck_model_call_cost_account_limit",
        ),
        sa.CheckConstraint(
            "allocated_cost_cny >= 0 AND actual_cost_cny >= 0",
            name="ck_model_call_cost_account_costs",
        ),
        sa.CheckConstraint(
            "unknown_cost_call_count >= 0",
            name="ck_model_call_cost_account_unknown_count",
        ),
        sa.UniqueConstraint(
            "scope_kind",
            "scope_id",
            name="uq_model_call_cost_accounts_scope",
        ),
    )
    op.create_index(
        "ix_model_call_cost_accounts_scope_kind",
        "model_call_cost_accounts",
        ["scope_kind"],
    )
    op.create_index(
        "ix_model_call_cost_accounts_scope_id",
        "model_call_cost_accounts",
        ["scope_id"],
    )
    op.create_index(
        "ix_model_call_cost_accounts_task_id",
        "model_call_cost_accounts",
        ["task_id"],
    )

    op.create_table(
        "model_call_ledgers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("operation_key", sa.String(length=150), nullable=False),
        sa.Column("call_index", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("modality", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "estimated_cost_cny",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "actual_cost_cny",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "billing_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_billable",
        ),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("failure_code", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('reserved', 'succeeded', 'failed', 'blocked')",
            name="ck_model_call_ledger_status",
        ),
        sa.CheckConstraint(
            "modality IN ('text', 'vision')",
            name="ck_model_call_ledger_modality",
        ),
        sa.CheckConstraint(
            "estimated_cost_cny IS NULL OR estimated_cost_cny >= 0",
            name="ck_model_call_ledger_estimated_cost",
        ),
        sa.CheckConstraint(
            "actual_cost_cny IS NULL OR actual_cost_cny >= 0",
            name="ck_model_call_ledger_actual_cost",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["model_call_cost_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "account_id",
            "operation_key",
            "call_index",
            name="uq_model_call_ledgers_operation_call",
        ),
    )
    for column in ("account_id", "task_id", "request_id", "provider_key", "status", "failure_code"):
        op.create_index(
            f"ix_model_call_ledgers_{column}",
            "model_call_ledgers",
            [column],
        )


def downgrade() -> None:
    op.drop_table("model_call_ledgers")
    op.drop_table("model_call_cost_accounts")
