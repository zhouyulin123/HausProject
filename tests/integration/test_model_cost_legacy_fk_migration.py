"""已有数据库的前向修复必须保留账本内容与账户外键。"""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_legacy_task_foreign_keys_removed_without_losing_ledger():
    path = Path(__file__).resolve().parents[2] / "backend/migrations/versions/e5a6b7c8d9e0_remove_legacy_model_cost_task_fks.py"
    spec = importlib.util.spec_from_file_location("legacy_cost_fk_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE design_tasks (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE model_call_cost_accounts (id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES design_tasks(id))"))
        connection.execute(text("CREATE TABLE model_call_ledgers (id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES design_tasks(id), account_id INTEGER REFERENCES model_call_cost_accounts(id))"))
        connection.execute(text("INSERT INTO design_tasks VALUES (1)"))
        connection.execute(text("INSERT INTO model_call_cost_accounts VALUES (2, 1)"))
        connection.execute(text("INSERT INTO model_call_ledgers VALUES (3, 1, 2)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()  # 新安装或已修复库保持幂等。
        assert inspect(connection).get_foreign_keys("model_call_cost_accounts") == []
        assert [fk["constrained_columns"] for fk in inspect(connection).get_foreign_keys("model_call_ledgers")] == [["account_id"]]
        assert connection.execute(text("SELECT * FROM model_call_ledgers")).all() == [(3, 1, 2)]
    engine.dispose()
