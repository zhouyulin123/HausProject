from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


@pytest.mark.integration
def test_open_geometry_rate_limit_migration_round_trip():
    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    artifacts_dir = backend_dir.parent / ".test_artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    database_path = artifacts_dir / f"open_geometry_rate_limit_{uuid4().hex}.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = Config(str(backend_dir / "alembic.ini"))
    config.attributes["database_url"] = database_url
    engine = None

    try:
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        assert "open_geometry_rate_limit_buckets" in inspect(
            engine
        ).get_table_names()
        engine.dispose()
        engine = None

        command.downgrade(config, "d3e4f5a6b7c8")
        engine = create_engine(database_url)
        assert "open_geometry_rate_limit_buckets" not in inspect(
            engine
        ).get_table_names()
        engine.dispose()
        engine = None

        command.upgrade(config, "head")
        engine = create_engine(database_url)
        assert "open_geometry_rate_limit_buckets" in inspect(
            engine
        ).get_table_names()
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)
