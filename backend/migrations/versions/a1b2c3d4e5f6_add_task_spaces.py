"""新增任务级整屋空间及不可变版本。"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "e5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "design_spaces",
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("design_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("current_version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "design_space_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("design_spaces.task_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document_json", sa.JSON(), nullable=False),
        sa.Column("client_mutation_id", sa.String(100), nullable=False),
        sa.Column("mutation_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("task_id", "version", name="uq_space_task_version"),
        sa.UniqueConstraint(
            "task_id", "client_mutation_id", name="uq_space_task_mutation"
        ),
    )
    op.create_index(
        "ix_design_space_versions_task_id", "design_space_versions", ["task_id"]
    )


def downgrade():
    op.drop_index(
        "ix_design_space_versions_task_id", table_name="design_space_versions"
    )
    op.drop_table("design_space_versions")
    op.drop_table("design_spaces")
