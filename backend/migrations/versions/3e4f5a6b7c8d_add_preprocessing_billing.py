"""为需求解析与视觉分析增加可审计计费字段。

Revision ID: 3e4f5a6b7c8d
Revises: 2d3e4f5a6b7c
Create Date: 2026-09-08 20:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3e4f5a6b7c8d"
down_revision: Union[str, Sequence[str], None] = "2d3e4f5a6b7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "uploaded_images",
        sa.Column(
            "analysis_model_call_attempted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "uploaded_images",
        sa.Column(
            "analysis_billing_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_billable",
        ),
    )
    op.add_column(
        "uploaded_images",
        sa.Column("analysis_cost_cny", sa.Float(), nullable=True),
    )
    op.add_column(
        "requirement_parse_results",
        sa.Column(
            "model_call_attempted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "requirement_parse_results",
        sa.Column(
            "billing_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_billable",
        ),
    )
    op.add_column(
        "requirement_parse_results",
        sa.Column("cost_cny", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("requirement_parse_results", "cost_cny")
    op.drop_column("requirement_parse_results", "billing_status")
    op.drop_column("requirement_parse_results", "model_call_attempted")
    op.drop_column("uploaded_images", "analysis_cost_cny")
    op.drop_column("uploaded_images", "analysis_billing_status")
    op.drop_column("uploaded_images", "analysis_model_call_attempted")
