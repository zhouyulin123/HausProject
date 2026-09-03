"""新增不可变方案安全分享快照。

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-03 11:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_version_id", sa.Integer(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=71), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["plan_version_id"],
            ["design_plan_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plan_shares_id"), "plan_shares", ["id"])
    op.create_index(
        op.f("ix_plan_shares_plan_version_id"),
        "plan_shares",
        ["plan_version_id"],
    )
    op.create_index(
        op.f("ix_plan_shares_token_digest"),
        "plan_shares",
        ["token_digest"],
        unique=True,
    )
    op.create_index(
        op.f("ix_plan_shares_expires_at"),
        "plan_shares",
        ["expires_at"],
    )
    op.create_index(
        op.f("ix_plan_shares_revoked_at"),
        "plan_shares",
        ["revoked_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_plan_shares_revoked_at"), table_name="plan_shares")
    op.drop_index(op.f("ix_plan_shares_expires_at"), table_name="plan_shares")
    op.drop_index(op.f("ix_plan_shares_token_digest"), table_name="plan_shares")
    op.drop_index(op.f("ix_plan_shares_plan_version_id"), table_name="plan_shares")
    op.drop_index(op.f("ix_plan_shares_id"), table_name="plan_shares")
    op.drop_table("plan_shares")
