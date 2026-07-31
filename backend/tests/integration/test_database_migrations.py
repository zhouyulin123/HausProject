from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


@pytest.mark.integration
def test_alembic_upgrades_empty_database_to_current_schema():
    backend_dir = Path(__file__).resolve().parents[2]
    artifacts_dir = backend_dir / ".test_artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    database_path = artifacts_dir / "haus_migration_test.db"
    database_path.unlink(missing_ok=True)
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = Config(str(backend_dir / "alembic.ini"))
    config.attributes["database_url"] = database_url
    inspection_engine = None

    try:
        command.upgrade(config, "head")

        inspection_engine = create_engine(database_url)
        tables = set(inspect(inspection_engine).get_table_names())
        assert {
            "alembic_version",
            "anonymous_sessions",
            "anonymous_session_images",
            "anonymous_session_tasks",
            "design_tasks",
            "design_results",
            "design_revisions",
            "design_plan_versions",
            "design_scenes",
            "design_scene_versions",
            "blender_render_jobs",
            "quote_snapshots",
            "uploaded_images",
            "products",
            "custom_quote_rules",
        } <= tables
        product_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("products")
        }
        assert {
            "model_url",
            "model_status",
            "model_width_mm",
            "model_height_mm",
            "model_depth_mm",
            "model_license",
            "model_source",
        } <= product_columns
        render_job_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns(
                "blender_render_jobs"
            )
        }
        assert {
            "scene_id",
            "scene_version_id",
            "profile",
            "status",
            "progress",
            "attempt",
            "worker_id",
            "lease_expires_at",
            "output_url",
            "error_message",
        } <= render_job_columns
    finally:
        if inspection_engine is not None:
            inspection_engine.dispose()
        database_path.unlink(missing_ok=True)
