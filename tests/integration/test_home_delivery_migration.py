"""交付迁移与 ORM 列及索引保持一致。"""

import importlib.util
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from app.db.database import Base
from app.db.schema_readiness import expected_migration_heads


def test_home_delivery_migration_matches_models(tmp_path):
    path = (
        Path(__file__).resolve().parents[2]
        / "backend/migrations/versions/f6a7b8c9d0e1_add_home_delivery_snapshots.py"
    )
    spec = importlib.util.spec_from_file_location("home_delivery_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "e5f6a7b8c9d0"
    assert expected_migration_heads() == ("f6a7b8c9d0e1",)
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE design_tasks (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE home_design_quotes (id INTEGER PRIMARY KEY)"
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            tables = (
                "home_delivery_snapshots",
                "home_delivery_confirmations",
                "home_delivery_shares",
            )
            for table in tables:
                assert {
                    c["name"] for c in inspect(connection).get_columns(table)
                } == set(Base.metadata.tables[table].columns.keys())
                assert {
                    (tuple(i["column_names"]), bool(i["unique"]))
                    for i in inspect(connection).get_indexes(table)
                } == {
                    (tuple(c.name for c in i.columns), bool(i.unique))
                    for i in Base.metadata.tables[table].indexes
                }
            migration.downgrade()
            assert not set(tables).intersection(inspect(connection).get_table_names())
    engine.dispose()
