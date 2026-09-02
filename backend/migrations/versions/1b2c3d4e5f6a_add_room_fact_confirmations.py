"""增加空间事实确认审计记录。

Revision ID: 1b2c3d4e5f6a
Revises: 0a1b2c3d4e5f
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1b2c3d4e5f6a"
down_revision: Union[str, Sequence[str], None] = "0a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "room_fact_confirmations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("fact_path", sa.String(length=255), nullable=False),
        sa.Column("previous_value_json", sa.JSON(), nullable=True),
        sa.Column("confirmed_value_json", sa.JSON(), nullable=False),
        sa.Column("previous_confidence", sa.Float(), nullable=True),
        sa.Column("confirmed_by_type", sa.String(length=30), nullable=False),
        sa.Column("confirmed_by_id", sa.String(length=100), nullable=False),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["uploaded_images.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["design_tasks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "id",
        "image_id",
        "task_id",
        "fact_path",
        "confirmed_by_id",
        "confirmed_at",
    ):
        op.create_index(
            f"ix_room_fact_confirmations_{column}",
            "room_fact_confirmations",
            [column],
        )


def downgrade() -> None:
    for column in reversed(
        (
            "id",
            "image_id",
            "task_id",
            "fact_path",
            "confirmed_by_id",
            "confirmed_at",
        )
    ):
        op.drop_index(
            f"ix_room_fact_confirmations_{column}",
            table_name="room_fact_confirmations",
        )
    op.drop_table("room_fact_confirmations")
