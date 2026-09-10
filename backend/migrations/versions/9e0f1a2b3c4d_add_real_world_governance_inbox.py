"""增加真实案例治理收件箱。

Revision ID: 9e0f1a2b3c4d
Revises: 8d9e0f1a2b3c
Create Date: 2026-09-10 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9e0f1a2b3c4d"
down_revision: Union[str, Sequence[str], None] = "8d9e0f1a2b3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "real_world_case_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_ref", sa.String(length=40), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_image_id", sa.Integer(), nullable=False),
        sa.Column(
            "origin",
            sa.String(length=20),
            nullable=False,
            server_default="private_real",
        ),
        sa.Column("asset_digest", sa.String(length=71), nullable=False),
        sa.Column("task_input_json", sa.JSON(), nullable=False),
        sa.Column("task_input_digest", sa.String(length=71), nullable=False),
        sa.Column(
            "split",
            sa.String(length=20),
            nullable=False,
            server_default="unassigned",
        ),
        sa.Column(
            "redaction_review",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "record_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "origin = 'private_real'", name="ck_real_world_case_origin_private"
        ),
        sa.CheckConstraint(
            "split IN ('unassigned', 'development', 'regression', 'blind')",
            name="ck_real_world_case_split",
        ),
        sa.CheckConstraint(
            "redaction_review IN ('pending', 'reviewed', 'rejected')",
            name="ck_real_world_case_redaction",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["design_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["uploaded_image_id"], ["uploaded_images.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("case_ref", name="uq_real_world_case_ref"),
        sa.UniqueConstraint("uploaded_image_id", name="uq_real_world_case_image"),
        sa.UniqueConstraint("asset_digest", name="uq_real_world_case_asset_digest"),
    )
    op.create_index("ix_rwc_task", "real_world_case_records", ["task_id"])

    op.create_table(
        "real_world_case_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_import_id", sa.String(length=100), nullable=False),
        sa.Column("request_digest", sa.String(length=71), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["real_world_case_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("client_import_id", name="uq_real_world_import_client_id"),
        sa.UniqueConstraint("case_id", name="uq_real_world_import_case"),
    )

    op.create_table(
        "real_world_consent_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("legal_basis", sa.String(length=30), nullable=False),
        sa.Column("allowed_purposes_json", sa.JSON(), nullable=False),
        sa.Column("evidence_digest", sa.String(length=71), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "decision IN ('granted', 'denied', 'revoked')",
            name="ck_real_world_consent_decision",
        ),
        sa.CheckConstraint(
            "legal_basis IN ('explicit_consent', 'contract', 'withdrawal_request')",
            name="ck_real_world_consent_legal_basis",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["real_world_case_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_rwc_consent_case", "real_world_consent_decisions", ["case_id"])

    op.create_table(
        "real_world_annotation_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("label_version", sa.String(length=100), nullable=False),
        sa.Column("annotation_json", sa.JSON(), nullable=False),
        sa.Column("annotation_digest", sa.String(length=71), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["real_world_case_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "case_id", "annotation_digest", name="uq_real_world_annotation_case_digest"
        ),
    )
    op.create_index(
        "ix_rwc_annotation_case", "real_world_annotation_revisions", ["case_id"]
    )

    op.create_table(
        "real_world_dataset_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_ref", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=10), nullable=False),
        sa.Column("dataset_version", sa.String(length=100), nullable=False),
        sa.Column("manifest_digest", sa.String(length=71), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("revision_ref", name="uq_real_world_dataset_ref"),
        sa.UniqueConstraint("dataset_version", name="uq_real_world_dataset_version"),
        sa.UniqueConstraint("manifest_digest", name="uq_real_world_dataset_digest"),
    )

    op.create_table(
        "real_world_governance_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("before_digest", sa.String(length=71), nullable=False),
        sa.Column("after_digest", sa.String(length=71), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["real_world_case_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_rwc_event_case", "real_world_governance_events", ["case_id"])
    op.create_index("ix_rwc_event_request", "real_world_governance_events", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_rwc_event_request", table_name="real_world_governance_events")
    op.drop_index("ix_rwc_event_case", table_name="real_world_governance_events")
    op.drop_table("real_world_governance_events")
    op.drop_table("real_world_dataset_revisions")
    op.drop_index("ix_rwc_annotation_case", table_name="real_world_annotation_revisions")
    op.drop_table("real_world_annotation_revisions")
    op.drop_index("ix_rwc_consent_case", table_name="real_world_consent_decisions")
    op.drop_table("real_world_consent_decisions")
    op.drop_table("real_world_case_imports")
    op.drop_index("ix_rwc_task", table_name="real_world_case_records")
    op.drop_table("real_world_case_records")
