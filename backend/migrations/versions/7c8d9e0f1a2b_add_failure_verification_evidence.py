"""增加失败簇签名复测证明。

Revision ID: 7c8d9e0f1a2b
Revises: 6b7c8d9e0f1a
Create Date: 2026-09-08 23:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c8d9e0f1a2b"
down_revision: Union[str, Sequence[str], None] = "6b7c8d9e0f1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "failure_verification_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.String(length=100), nullable=False),
        sa.Column("report_digest", sa.String(length=71), nullable=False),
        sa.Column("semantic_digest", sa.String(length=71), nullable=False),
        sa.Column("coverage_digest", sa.String(length=71), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id"),
        sa.UniqueConstraint("semantic_digest"),
    )
    op.create_index(
        "ix_failure_verification_imports_id",
        "failure_verification_imports",
        ["id"],
    )
    op.create_index(
        "ix_failure_verification_imports_report_id",
        "failure_verification_imports",
        ["report_id"],
    )
    op.create_index(
        "ix_failure_verification_imports_semantic_digest",
        "failure_verification_imports",
        ["semantic_digest"],
    )
    with op.batch_alter_table("failure_clusters") as batch_op:
        batch_op.add_column(sa.Column("verification_report_id", sa.String(100)))
        batch_op.add_column(sa.Column("report_digest", sa.String(71)))
        batch_op.add_column(sa.Column("coverage_digest", sa.String(71)))
        batch_op.create_foreign_key(
            "fk_failure_clusters_verification_report_id",
            "failure_verification_imports",
            ["verification_report_id"],
            ["report_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_failure_clusters_verification_report_id",
            ["verification_report_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("failure_clusters") as batch_op:
        batch_op.drop_index("ix_failure_clusters_verification_report_id")
        batch_op.drop_constraint(
            "fk_failure_clusters_verification_report_id",
            type_="foreignkey",
        )
        batch_op.drop_column("coverage_digest")
        batch_op.drop_column("report_digest")
        batch_op.drop_column("verification_report_id")
    op.drop_index(
        "ix_failure_verification_imports_semantic_digest",
        table_name="failure_verification_imports",
    )
    op.drop_index(
        "ix_failure_verification_imports_report_id",
        table_name="failure_verification_imports",
    )
    op.drop_index(
        "ix_failure_verification_imports_id",
        table_name="failure_verification_imports",
    )
    op.drop_table("failure_verification_imports")
