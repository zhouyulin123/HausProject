"""为图片上传增加会话隔离的幂等键。

Revision ID: 4f5a6b7c8d9e
Revises: 3e4f5a6b7c8d
Create Date: 2026-09-08 20:35:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f5a6b7c8d9e"
down_revision: Union[str, Sequence[str], None] = "3e4f5a6b7c8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "uploaded_images",
        sa.Column("upload_operation_key", sa.String(length=71), nullable=True),
    )
    op.add_column(
        "uploaded_images",
        sa.Column("upload_request_digest", sa.String(length=71), nullable=True),
    )
    op.create_index(
        op.f("ix_uploaded_images_upload_operation_key"),
        "uploaded_images",
        ["upload_operation_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_uploaded_images_upload_operation_key"),
        table_name="uploaded_images",
    )
    op.drop_column("uploaded_images", "upload_request_digest")
    op.drop_column("uploaded_images", "upload_operation_key")
