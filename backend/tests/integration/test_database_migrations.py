from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


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
            "failure_clusters",
            "failure_triage_imports",
            "room_fact_confirmations",
            "model_provider_circuits",
        } <= tables
        room_confirmation_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns(
                "room_fact_confirmations"
            )
        }
        assert {
            "image_id",
            "task_id",
            "fact_path",
            "previous_value_json",
            "confirmed_value_json",
            "previous_confidence",
            "confirmed_by_type",
            "confirmed_by_id",
            "confirmed_at",
        } <= room_confirmation_columns

        provider_circuit_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns(
                "model_provider_circuits"
            )
        }
        assert {
            "provider_key",
            "state",
            "consecutive_failures",
            "opened_at",
            "cooldown_until",
            "probe_token",
            "probe_expires_at",
            "last_failure_code",
            "updated_at",
        } <= provider_circuit_columns
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
            "model_reviewed_at",
            "model_reviewed_by",
            "model_review_note",
            "model_spec_json",
            "verification_status",
            "availability_status",
            "region_codes",
            "stock_quantity",
            "lead_time_days_min",
            "lead_time_days_max",
            "price_valid_from",
            "price_valid_to",
            "verified_at",
            "verified_by",
            "data_version",
            "record_version",
            "alternative_skus",
        } <= product_columns
        quote_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("quote_snapshots")
        }
        assert {
            "catalog_version",
            "price_version",
            "rule_version",
            "sku_versions_json",
        } <= quote_columns
        custom_rule_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("custom_quote_rules")
        }
        assert {
            "region_codes",
            "waste_rate_bps",
            "minimum_quantity",
            "installation_fee",
            "shipping_fee",
            "tax_rate_bps",
            "data_version",
            "record_version",
        } <= custom_rule_columns
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
            "execution_deadline_at",
            "dead_lettered_at",
            "cost_reserved_cny",
            "cost_limit_cny",
            "request_id",
            "prompt_digest",
            "rules_digest",
            "data_digest",
        } <= generation_run_columns
        rendered_image_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("rendered_images")
        }
        assert "plan_version_id" in rendered_image_columns
        generation_run_constraints = {
            constraint["name"]: set(constraint["column_names"])
            for constraint in inspect(inspection_engine).get_unique_constraints(
                "generation_runs"
            )
        }
        assert generation_run_constraints[
            "uq_generation_runs_task_idempotency"
        ] == {"task_id", "idempotency_key"}
    finally:
        if inspection_engine is not None:
            inspection_engine.dispose()
        database_path.unlink(missing_ok=True)


@pytest.mark.integration
def test_catalog_migration_keeps_existing_merchant_draft_unverified():
    backend_dir = Path(__file__).resolve().parents[2]
    artifacts_dir = backend_dir / ".test_artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    database_path = artifacts_dir / "catalog_lifecycle_migration_test.db"
    database_path.unlink(missing_ok=True)
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = Config(str(backend_dir / "alembic.ini"))
    config.attributes["database_url"] = database_url
    engine = None
    try:
        command.upgrade(config, "e6f8a0b2c4d6")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO products "
                    "(sku, name, category, room, style, price, data_origin, is_active) "
                    "VALUES ('DRAFT-LEGACY', '历史草稿', '沙发', '客厅', "
                    "'现代简约', 3999, 'merchant_draft', 1)"
                )
            )
        engine.dispose()
        engine = None

        command.upgrade(config, "head")
        engine = create_engine(database_url)
        with engine.connect() as connection:
            migrated = connection.execute(
                text(
                    "SELECT verification_status, availability_status, record_version "
                    "FROM products WHERE sku = 'DRAFT-LEGACY'"
                )
            ).mappings().one()
        assert migrated == {
            "verification_status": "draft",
            "availability_status": "unknown",
            "record_version": 1,
        }
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)
