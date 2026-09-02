"""add failure triage clusters

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "failure_clusters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=100), nullable=False),
        sa.Column("data_version", sa.String(length=100), nullable=False),
        sa.Column("failure_type", sa.String(length=50), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("affected_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_version", sa.String(length=100), nullable=False),
        sa.Column("fixed_version", sa.String(length=100), nullable=True),
        sa.Column("verified_version", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint"),
    )
    op.create_index("ix_failure_clusters_id", "failure_clusters", ["id"])
    op.create_index("ix_failure_clusters_fingerprint", "failure_clusters", ["fingerprint"])
    op.create_index("ix_failure_clusters_failure_type", "failure_clusters", ["failure_type"])
    op.create_index("ix_failure_clusters_code", "failure_clusters", ["code"])
    op.create_index("ix_failure_clusters_severity", "failure_clusters", ["severity"])
    op.create_index("ix_failure_clusters_status", "failure_clusters", ["status"])
    op.create_index("ix_failure_clusters_owner", "failure_clusters", ["owner"])
    op.create_index("ix_failure_clusters_last_seen_at", "failure_clusters", ["last_seen_at"])
    op.create_table(
        "failure_triage_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.String(length=100), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id"),
    )
    op.create_index("ix_failure_triage_imports_id", "failure_triage_imports", ["id"])
    op.create_index("ix_failure_triage_imports_report_id", "failure_triage_imports", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_failure_triage_imports_report_id", table_name="failure_triage_imports")
    op.drop_index("ix_failure_triage_imports_id", table_name="failure_triage_imports")
    op.drop_table("failure_triage_imports")
    op.drop_index("ix_failure_clusters_last_seen_at", table_name="failure_clusters")
    op.drop_index("ix_failure_clusters_owner", table_name="failure_clusters")
    op.drop_index("ix_failure_clusters_status", table_name="failure_clusters")
    op.drop_index("ix_failure_clusters_severity", table_name="failure_clusters")
    op.drop_index("ix_failure_clusters_code", table_name="failure_clusters")
    op.drop_index("ix_failure_clusters_failure_type", table_name="failure_clusters")
    op.drop_index("ix_failure_clusters_fingerprint", table_name="failure_clusters")
    op.drop_index("ix_failure_clusters_id", table_name="failure_clusters")
    op.drop_table("failure_clusters")
