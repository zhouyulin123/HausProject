"""整屋受控建议的持久化调用预留。"""

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "home_design_agent_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("design_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_turn_id", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "task_id", "client_turn_id", name="uq_home_agent_task_turn"
        ),
    )
    op.create_index(
        "ix_home_design_agent_turns_task_id", "home_design_agent_turns", ["task_id"]
    )


def downgrade():
    op.drop_index(
        "ix_home_design_agent_turns_task_id", table_name="home_design_agent_turns"
    )
    op.drop_table("home_design_agent_turns")
