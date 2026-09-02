"""冻结真实模型确认前预测证据。

Revision ID: bf2a3b4c5d6e
Revises: ae1f2a3b4c5d
Create Date: 2026-09-02 23:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "bf2a3b4c5d6e"
down_revision: Union[str, Sequence[str], None] = "ae1f2a3b4c5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("uploaded_images") as batch_op:
        batch_op.add_column(sa.Column("original_prediction_json", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("original_prediction_source", sa.String(length=30), nullable=True)
        )
        batch_op.add_column(
            sa.Column("original_prediction_digest", sa.String(length=71), nullable=True)
        )

    with op.batch_alter_table("evaluation_run_bindings") as batch_op:
        batch_op.add_column(
            sa.Column("requirement_parse_result_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(sa.Column("uploaded_image_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("prediction_snapshot_json", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("prediction_digest", sa.String(length=71), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_eval_binding_requirement_parse_result",
            "requirement_parse_results",
            ["requirement_parse_result_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_eval_binding_uploaded_image",
            "uploaded_images",
            ["uploaded_image_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            op.f("ix_evaluation_run_bindings_requirement_parse_result_id"),
            ["requirement_parse_result_id"],
        )
        batch_op.create_index(
            op.f("ix_evaluation_run_bindings_uploaded_image_id"),
            ["uploaded_image_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("evaluation_run_bindings") as batch_op:
        batch_op.drop_index(op.f("ix_evaluation_run_bindings_uploaded_image_id"))
        batch_op.drop_index(
            op.f("ix_evaluation_run_bindings_requirement_parse_result_id")
        )
        batch_op.drop_constraint("fk_eval_binding_uploaded_image", type_="foreignkey")
        batch_op.drop_constraint(
            "fk_eval_binding_requirement_parse_result", type_="foreignkey"
        )
        batch_op.drop_column("prediction_digest")
        batch_op.drop_column("prediction_snapshot_json")
        batch_op.drop_column("uploaded_image_id")
        batch_op.drop_column("requirement_parse_result_id")

    with op.batch_alter_table("uploaded_images") as batch_op:
        batch_op.drop_column("original_prediction_digest")
        batch_op.drop_column("original_prediction_source")
        batch_op.drop_column("original_prediction_json")
