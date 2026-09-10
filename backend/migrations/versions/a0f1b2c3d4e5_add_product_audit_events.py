"""增加商品商业核验追加式审计事件。

Revision ID: a0f1b2c3d4e5
Revises: 9e0f1a2b3c4d
Create Date: 2026-09-10 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a0f1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "9e0f1a2b3c4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=True),
        sa.Column("resulting_status", sa.String(length=20), nullable=False),
        sa.Column("resulting_record_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ('commercial_created', 'commercial_patch', "
            "'commercial_deactivate', 'commercial_excel_created', "
            "'commercial_excel_updated', 'commercial_review_approve', "
            "'commercial_review_reject')",
            name="ck_product_audit_event_type",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('approve', 'reject')",
            name="ck_product_audit_decision",
        ),
        sa.CheckConstraint(
            "resulting_status IN ('draft', 'verified', 'rejected', 'expired')",
            name="ck_product_audit_resulting_status",
        ),
        sa.CheckConstraint(
            "resulting_record_version >= 1",
            name="ck_product_audit_record_version",
        ),
        sa.CheckConstraint(
            "(idempotency_key IS NULL AND payload_hash IS NULL) OR "
            "(idempotency_key IS NOT NULL AND payload_hash IS NOT NULL)",
            name="ck_product_audit_idempotency_pair",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "product_id",
            "idempotency_key",
            name="uq_product_audit_product_idempotency",
        ),
    )
    op.create_index(
        "ix_product_audit_events_product_id",
        "product_audit_events",
        ["product_id"],
    )
    op.create_index(
        "ix_product_audit_events_event_type",
        "product_audit_events",
        ["event_type"],
    )
    op.create_index(
        "ix_product_audit_events_actor",
        "product_audit_events",
        ["actor"],
    )
    op.create_index(
        "ix_product_audit_events_request_id",
        "product_audit_events",
        ["request_id"],
    )
    op.create_index(
        "ix_product_audit_events_decision",
        "product_audit_events",
        ["decision"],
    )
    op.create_index(
        "ix_product_audit_events_resulting_status",
        "product_audit_events",
        ["resulting_status"],
    )
    op.create_index(
        "ix_product_audit_events_created_at",
        "product_audit_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_audit_events_created_at",
        table_name="product_audit_events",
    )
    op.drop_index(
        "ix_product_audit_events_resulting_status",
        table_name="product_audit_events",
    )
    op.drop_index(
        "ix_product_audit_events_decision",
        table_name="product_audit_events",
    )
    op.drop_index(
        "ix_product_audit_events_request_id",
        table_name="product_audit_events",
    )
    op.drop_index(
        "ix_product_audit_events_actor",
        table_name="product_audit_events",
    )
    op.drop_index(
        "ix_product_audit_events_event_type",
        table_name="product_audit_events",
    )
    op.drop_index(
        "ix_product_audit_events_product_id",
        table_name="product_audit_events",
    )
    op.drop_table("product_audit_events")
