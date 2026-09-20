"""整屋不可变估价快照。"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "home_design_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("design_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("home_version", sa.Integer(), nullable=False),
        sa.Column("client_mutation_id", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "task_id", "client_mutation_id", name="uq_home_quote_task_mutation"
        ),
    )
    op.create_index("ix_home_design_quotes_task_id", "home_design_quotes", ["task_id"])


def downgrade():
    op.drop_index("ix_home_design_quotes_task_id", table_name="home_design_quotes")
    op.drop_table("home_design_quotes")
