"""新增通用商品资产审核事实。

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-09-04 10:00:00.000000
"""

from typing import Sequence, Union
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_trusted_legacy_glb_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = unquote(value.strip())
    parsed = urlsplit(normalized)
    path = PurePosixPath(parsed.path)
    return (
        parsed.scheme == ""
        and parsed.netloc == ""
        and not parsed.query
        and not parsed.fragment
        and "\\" not in normalized
        and parsed.path.startswith("/uploads/models/")
        and ".." not in path.parts
        and path.suffix.lower() == ".glb"
    )


def upgrade() -> None:
    op.create_table(
        "product_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=True),
        sa.Column("authorization", sa.String(length=500), nullable=True),
        sa.Column(
            "review_status",
            sa.String(length=20),
            server_default="pending_review",
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=100), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('image', 'cad', 'glb', 'material')",
            name="ck_product_assets_kind",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending_review', 'approved', 'rejected', 'superseded')",
            name="ck_product_assets_review_status",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "kind",
            "url",
            name="uq_product_assets_product_kind_url",
        ),
    )
    op.create_index(
        op.f("ix_product_assets_product_id"),
        "product_assets",
        ["product_id"],
    )
    op.create_index(
        op.f("ix_product_assets_kind"),
        "product_assets",
        ["kind"],
    )
    op.create_index(
        op.f("ix_product_assets_review_status"),
        "product_assets",
        ["review_status"],
    )

    products = sa.table(
        "products",
        sa.column("id", sa.Integer()),
        sa.column("image_url", sa.String()),
        sa.column("model_url", sa.String()),
        sa.column("model_status", sa.String()),
        sa.column("model_license", sa.String()),
        sa.column("model_source", sa.String()),
        sa.column("model_reviewed_at", sa.DateTime(timezone=True)),
        sa.column("model_reviewed_by", sa.String()),
        sa.column("model_review_note", sa.String()),
    )
    assets = sa.table(
        "product_assets",
        sa.column("product_id", sa.Integer()),
        sa.column("kind", sa.String()),
        sa.column("url", sa.String()),
        sa.column("source", sa.String()),
        sa.column("authorization", sa.String()),
        sa.column("review_status", sa.String()),
        sa.column("reviewed_at", sa.DateTime(timezone=True)),
        sa.column("reviewed_by", sa.String()),
        sa.column("review_note", sa.String()),
        sa.column("created_by", sa.String()),
    )
    connection = op.get_bind()
    for row in connection.execute(sa.select(products)).mappings():
        records: list[dict[str, object]] = []
        if row["image_url"]:
            records.append(
                {
                    "product_id": row["id"],
                    "kind": "image",
                    "url": row["image_url"],
                    "source": None,
                    "authorization": None,
                    "review_status": "pending_review",
                    "reviewed_at": None,
                    "reviewed_by": None,
                    "review_note": None,
                    "created_by": "migration:legacy_product",
                }
            )
        if row["model_url"]:
            complete_review = (
                row["model_status"] == "ready"
                and _has_text(row["model_license"])
                and _has_text(row["model_source"])
                and row["model_reviewed_at"] is not None
                and _has_text(row["model_reviewed_by"])
                and _is_trusted_legacy_glb_url(row["model_url"])
            )
            records.append(
                {
                    "product_id": row["id"],
                    "kind": "glb",
                    "url": row["model_url"],
                    "source": row["model_source"],
                    "authorization": row["model_license"],
                    "review_status": (
                        "approved"
                        if complete_review
                        else "rejected"
                        if row["model_status"] == "rejected"
                        else "pending_review"
                    ),
                    "reviewed_at": row["model_reviewed_at"],
                    "reviewed_by": row["model_reviewed_by"],
                    "review_note": row["model_review_note"],
                    "created_by": "migration:legacy_product",
                }
            )
        if records:
            connection.execute(assets.insert(), records)


def downgrade() -> None:
    op.drop_index(
        op.f("ix_product_assets_review_status"),
        table_name="product_assets",
    )
    op.drop_index(op.f("ix_product_assets_kind"), table_name="product_assets")
    op.drop_index(
        op.f("ix_product_assets_product_id"),
        table_name="product_assets",
    )
    op.drop_table("product_assets")
