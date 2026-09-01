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
            "sms_codes",
            "orders",
            "order_quotes",
            "design_agent_turns",
            "design_agent_events",
        } <= tables
        task_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("design_tasks")
        }
        assert {
            "agent_state_json",
            "agent_state_version",
            "active_mode",
        } <= task_columns
        chat_columns = {
            column["name"]: column
            for column in inspect(inspection_engine).get_columns("chat_logs")
        }
        # 保留历史孤立记录兼容性；应用层的新写入由契约保证绑定。
        assert chat_columns["task_id"]["nullable"] is True
        user_columns = {
            column["name"] for column in inspect(inspection_engine).get_columns("users")
        }
        assert {"role", "phone_verified", "last_login_at"} <= user_columns
        product_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("products")
        }
        assert {
            "data_origin",
            "source_name",
            "source_url",
            "source_product_id",
            "source_retrieved_at",
            "price_observed_at",
            "price_note",
            "source_metadata",
            "model_url",
            "model_status",
            "model_width_mm",
            "model_height_mm",
            "model_depth_mm",
            "model_license",
            "model_source",
            "model_spec_json",
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
        generation_run_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns(
                "generation_runs"
            )
        }
        assert {
            "model",
            "prompt_snapshot",
            "input_snapshot",
            "output_snapshot",
            "usage_json",
            "cost_cny",
            "worker_id",
            "lease_expires_at",
            "heartbeat_at",
            "next_retry_at",
            "attempt_count",
            "max_attempts",
            "cancel_requested_at",
            "idempotency_key",
        } <= generation_run_columns
    finally:
        if inspection_engine is not None:
            inspection_engine.dispose()
        database_path.unlink(missing_ok=True)
