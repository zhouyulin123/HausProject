from __future__ import annotations

from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql


REVISION = "9e0f1a2b3c4d"
PREVIOUS_REVISION = "8d9e0f1a2b3c"
TABLES = {
    "real_world_case_records",
    "real_world_case_imports",
    "real_world_consent_decisions",
    "real_world_annotation_revisions",
    "real_world_dataset_revisions",
    "real_world_governance_events",
}


@pytest.mark.integration
def test_real_world_governance_migration_upgrade_downgrade_upgrade():
    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    database_path = (
        backend_dir.parent / ".test_artifacts" / f"governance-{uuid4().hex}.db"
    )
    database_path.parent.mkdir(exist_ok=True)
    config = Config(str(backend_dir / "alembic.ini"))
    config.attributes["database_url"] = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = None
    try:
        command.upgrade(config, REVISION)
        engine = create_engine(config.attributes["database_url"])
        assert TABLES <= set(inspect(engine).get_table_names())
        engine.dispose()
        engine = None

        command.downgrade(config, PREVIOUS_REVISION)
        engine = create_engine(config.attributes["database_url"])
        assert not TABLES & set(inspect(engine).get_table_names())
        engine.dispose()
        engine = None

        command.upgrade(config, "head")
        engine = create_engine(config.attributes["database_url"])
        assert TABLES <= set(inspect(engine).get_table_names())
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)


def test_real_world_governance_migration_emits_mysql_offline_ddl():
    migration = __import__(
        "migrations.versions.9e0f1a2b3c4d_add_real_world_governance_inbox",
        fromlist=["upgrade"],
    )
    output = StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        migration.upgrade()

    ddl = output.getvalue().upper()
    assert "CREATE TABLE REAL_WORLD_CASE_RECORDS" in ddl
    assert "CREATE TABLE REAL_WORLD_DATASET_REVISIONS" in ddl
    assert "DROP TABLE" not in ddl
