"""整屋家装文档与不可变历史。"""

from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "home_designs",
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("design_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("current_version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "home_design_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("home_designs.task_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("client_mutation_id", sa.String(100), nullable=False),
        sa.Column("mutation_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("task_id", "version", name="uq_home_design_task_version"),
        sa.UniqueConstraint(
            "task_id", "client_mutation_id", name="uq_home_design_task_mutation"
        ),
    )
    op.create_index(
        "ix_home_design_versions_task_id", "home_design_versions", ["task_id"]
    )


def downgrade():
    op.drop_index("ix_home_design_versions_task_id", table_name="home_design_versions")
    op.drop_table("home_design_versions")
    op.drop_table("home_designs")
