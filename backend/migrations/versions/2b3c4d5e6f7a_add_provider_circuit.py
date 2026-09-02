"""增加模型供应商持久化熔断状态。

Revision ID: 2b3c4d5e6f7a
Revises: 4e5f6a7b8c9d
Create Date: 2026-09-02 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2b3c4d5e6f7a"
down_revision: Union[str, Sequence[str], None] = "4e5f6a7b8c9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_provider_circuits",
        sa.Column("provider_key", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("probe_token", sa.String(length=36), nullable=True),
        sa.Column("probe_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_code", sa.String(length=50), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("provider_key"),
        sa.UniqueConstraint("probe_token"),
    )
    op.create_index(
        "ix_model_provider_circuits_state",
        "model_provider_circuits",
        ["state"],
    )
    op.create_index(
        "ix_model_provider_circuits_cooldown_until",
        "model_provider_circuits",
        ["cooldown_until"],
    )
    op.create_index(
        "ix_model_provider_circuits_probe_expires_at",
        "model_provider_circuits",
        ["probe_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_provider_circuits_probe_expires_at",
        table_name="model_provider_circuits",
    )
    op.drop_index(
        "ix_model_provider_circuits_cooldown_until",
        table_name="model_provider_circuits",
    )
    op.drop_index(
        "ix_model_provider_circuits_state",
        table_name="model_provider_circuits",
    )
    op.drop_table("model_provider_circuits")
