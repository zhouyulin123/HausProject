"""新增商品 3D 模型资产字段。

Revision ID: b7d9e1f3a5c8
Revises: a2b4c6d8e0f1
Create Date: 2026-07-31 16:40:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d9e1f3a5c8"
down_revision: Union[str, Sequence[str], None] = "a2b4c6d8e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("model_url", sa.String(255), nullable=True))
    op.add_column(
        "products",
        sa.Column(
            "model_status",
            sa.String(20),
            nullable=False,
            server_default="missing",
        ),
    )
    op.add_column("products", sa.Column("model_width_mm", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("model_height_mm", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("model_depth_mm", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("model_license", sa.String(100), nullable=True))
    op.add_column("products", sa.Column("model_source", sa.String(255), nullable=True))
    demo_assets = [
        ("SF-001", "/models/demo/sofa.glb", 2400, 850, 1050),
        ("SF-002", "/models/demo/sofa.glb", 2800, 850, 1700),
        ("SF-003", "/models/demo/chair.glb", 780, 900, 780),
        ("CJ-001", "/models/demo/coffee-table.glb", 900, 420, 900),
        ("CJ-002", "/models/demo/coffee-table.glb", 900, 420, 900),
        ("DG-001", "/models/demo/lamp.glb", 400, 1500, 400),
        ("DG-002", "/models/demo/lamp.glb", 300, 600, 300),
        ("DG-003", "/models/demo/lamp.glb", 500, 700, 500),
        ("DT-001", "/models/demo/rug.glb", 2000, 25, 2900),
        ("DT-002", "/models/demo/rug.glb", 1600, 25, 2300),
        ("CH-001", "/models/demo/bed.glb", 1800, 900, 2000),
        ("CH-002", "/models/demo/bed.glb", 1800, 1000, 2000),
        ("CT-001", "/models/demo/cabinet.glb", 450, 550, 400),
        ("ZY-001", "/models/demo/dining-table.glb", 1350, 750, 1350),
        ("ZY-002", "/models/demo/dining-table.glb", 1600, 750, 850),
        ("CY-001", "/models/demo/chair.glb", 520, 900, 520),
        ("SZ-001", "/models/demo/desk.glb", 1400, 750, 700),
        ("YZ-001", "/models/demo/chair.glb", 650, 1050, 650),
        ("SJ-001", "/models/demo/cabinet.glb", 800, 1800, 350),
    ]
    statement = sa.text(
        """
        UPDATE products
        SET model_url = :model_url,
            model_status = 'ready',
            model_width_mm = :width,
            model_height_mm = :height,
            model_depth_mm = :depth,
            model_license = '项目自有演示',
            model_source = '内置参数化模型'
        WHERE sku = :sku AND model_url IS NULL
        """
    )
    connection = op.get_bind()
    for sku, model_url, width, height, depth in demo_assets:
        connection.execute(
            statement,
            {
                "sku": sku,
                "model_url": model_url,
                "width": width,
                "height": height,
                "depth": depth,
            },
        )


def downgrade() -> None:
    op.drop_column("products", "model_source")
    op.drop_column("products", "model_license")
    op.drop_column("products", "model_depth_mm")
    op.drop_column("products", "model_height_mm")
    op.drop_column("products", "model_width_mm")
    op.drop_column("products", "model_status")
    op.drop_column("products", "model_url")
