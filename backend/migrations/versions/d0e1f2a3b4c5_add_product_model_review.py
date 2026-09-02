"""增加商品模型授权审核记录。

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-02 10:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("model_reviewed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("model_reviewed_by", sa.String(length=100)))
        batch_op.add_column(sa.Column("model_review_note", sa.String(length=500)))
    op.execute(
        "UPDATE products SET model_status = 'pending_review' "
        "WHERE model_status = 'ready' AND ("
        "model_license IS NULL OR model_license = '' OR "
        "model_source IS NULL OR model_source = '')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE products SET model_status = 'missing' "
        "WHERE model_status IN ('pending_review', 'rejected')"
    )
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("model_review_note")
        batch_op.drop_column("model_reviewed_by")
        batch_op.drop_column("model_reviewed_at")
