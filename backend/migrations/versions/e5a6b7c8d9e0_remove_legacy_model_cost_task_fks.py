"""清理旧数据库残留的模型账本任务外键，避免独立计费事务自阻塞。

Revision ID: e5a6b7c8d9e0
Revises: d4f5a6b7c8d9
"""

from alembic import op
import sqlalchemy as sa

revision = "e5a6b7c8d9e0"
down_revision = "d4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("model_call_cost_accounts", "model_call_ledgers"):
        for foreign_key in inspector.get_foreign_keys(table):
            if (foreign_key["constrained_columns"] != ["task_id"]
                    or foreign_key["referred_table"] != "design_tasks"
                    or foreign_key["referred_columns"] != ["id"]):
                continue
            # SQLite 的旧无名约束在批量重建时获得稳定名称；其他数据库沿用实际名称。
            convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
            name = foreign_key["name"] or f"fk_{table}_task_id_design_tasks"
            with op.batch_alter_table(table, naming_convention=convention) as batch:
                batch.drop_constraint(name, type_="foreignkey")


def downgrade() -> None:
    # 上一版迁移源码已经没有这两条外键；回退时不重新引入已知自阻塞。
    pass
