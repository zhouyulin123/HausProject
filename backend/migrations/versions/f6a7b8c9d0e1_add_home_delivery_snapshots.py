"""冻结整屋交付、审阅与受控公开投影。"""

from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    for table, unique, extra in (
        (
            "home_delivery_snapshots",
            "uq_home_delivery_mutation",
            [
                sa.Column("home_version", sa.Integer(), nullable=False),
                sa.Column("space_version", sa.Integer(), nullable=False),
                sa.Column(
                    "quote_id",
                    sa.Integer(),
                    sa.ForeignKey("home_design_quotes.id", ondelete="RESTRICT"),
                    nullable=True,
                ),
                sa.Column("snapshot_json", sa.JSON(), nullable=False),
                sa.Column("content_digest", sa.String(64), nullable=False),
            ],
        ),
        (
            "home_delivery_confirmations",
            "uq_home_confirmation_mutation",
            [
                sa.Column(
                    "delivery_id",
                    sa.Integer(),
                    sa.ForeignKey("home_delivery_snapshots.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column("snapshot_digest", sa.String(64), nullable=False),
                sa.Column("decision", sa.String(30), nullable=False),
                sa.Column("note", sa.Text(), nullable=False),
            ],
        ),
        (
            "home_delivery_shares",
            "uq_home_share_mutation",
            [
                sa.Column(
                    "delivery_id",
                    sa.Integer(),
                    sa.ForeignKey("home_delivery_snapshots.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column("token_digest", sa.String(64), nullable=False),
                sa.Column("snapshot_json", sa.JSON(), nullable=False),
                sa.Column("content_digest", sa.String(64), nullable=False),
                sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            ],
        ),
    ):
        if table == "home_delivery_confirmations":
            extra.append(sa.Column("actor_session_id", sa.String(36), nullable=False))
        if table == "home_delivery_shares":
            extra.append(sa.Column("consent_json", sa.JSON(), nullable=False))
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "task_id",
                sa.Integer(),
                sa.ForeignKey("design_tasks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("client_mutation_id", sa.String(100), nullable=False),
            sa.Column("request_digest", sa.String(64), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            *extra,
            sa.UniqueConstraint("task_id", "client_mutation_id", name=unique),
        )
        op.create_index(f"ix_{table}_task_id", table, ["task_id"])
        if table != "home_delivery_snapshots":
            op.create_index(f"ix_{table}_delivery_id", table, ["delivery_id"])
    op.create_index(
        "ix_home_delivery_shares_token_digest",
        "home_delivery_shares",
        ["token_digest"],
        unique=True,
    )


def downgrade():
    for table in (
        "home_delivery_shares",
        "home_delivery_confirmations",
        "home_delivery_snapshots",
    ):
        op.drop_table(table)
