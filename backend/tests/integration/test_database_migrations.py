import logging
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateColumn


@pytest.mark.parametrize(
    "module_name",
    [
        "migrations.versions.a7b8c9d0e1f2_add_catalog_lifecycle",
        "migrations.versions.c9d0e1f2a3b4_add_custom_quote_cost_factors",
    ],
)
def test_json_list_columns_have_no_mysql_server_default(module_name):
    migration = __import__(module_name, fromlist=["_json_list_column"])
    ddl = str(
        CreateColumn(migration._json_list_column("region_codes")).compile(
            dialect=mysql.dialect()
        )
    )

    assert "DEFAULT" not in ddl.upper()
    assert "JSON" in ddl.upper()


@pytest.mark.integration
def test_langgraph_checkpoint_migration_round_trip_from_empty_database():
    backend_dir = Path(__file__).resolve().parents[2]
    artifacts_dir = backend_dir / ".test_artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    database_path = artifacts_dir / (f"langgraph_checkpoint_migration_{uuid4().hex}.db")
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = Config(str(backend_dir / "alembic.ini"))
    config.attributes["database_url"] = database_url
    engine = None
    app_logger = logging.getLogger("app.http")
    app_logger.disabled = False

    try:
        command.upgrade(config, "e3f4a5b6c7d8")
        assert app_logger.disabled is False
        engine = create_engine(database_url)
        assert {
            "langgraph_checkpoints",
            "langgraph_checkpoint_writes",
        } <= set(inspect(engine).get_table_names())
        engine.dispose()
        engine = None

        command.downgrade(config, "d2e3f4a5b6c7")
        engine = create_engine(database_url)
        assert not {
            "langgraph_checkpoints",
            "langgraph_checkpoint_writes",
        } & set(inspect(engine).get_table_names())
        engine.dispose()
        engine = None

        command.upgrade(config, "head")
        engine = create_engine(database_url)
        assert {
            "langgraph_checkpoints",
            "langgraph_checkpoint_writes",
        } <= set(inspect(engine).get_table_names())
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)


@pytest.mark.integration
def test_product_asset_migration_backfills_only_trusted_legacy_glb_as_approved():
    backend_dir = Path(__file__).resolve().parents[2]
    artifacts_dir = backend_dir / ".test_artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    database_path = artifacts_dir / f"product_assets_{uuid4().hex}.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    config = Config(str(backend_dir / "alembic.ini"))
    config.attributes["database_url"] = database_url
    engine = None
    try:
        command.upgrade(config, "e3f4a5b6c7d8")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO products "
                    "(id, name, price, model_url, model_status, model_width_mm, "
                    "model_height_mm, model_depth_mm, model_license, model_source, "
                    "model_reviewed_at, model_reviewed_by, image_url, region_codes, "
                    "alternative_skus, is_active) "
                    "VALUES (9001, '可信旧商品', 1000, '/uploads/models/legacy.glb', "
                    "'ready', 100, 100, 100, '商用授权', 'supplier:legacy', "
                    "'2026-09-01 00:00:00', 'user:1', '/uploads/products/legacy.png', "
                    "'[]', '[]', 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO products "
                    "(id, name, price, model_url, model_status, model_width_mm, "
                    "model_height_mm, model_depth_mm, model_license, model_source, "
                    "model_reviewed_at, model_reviewed_by, region_codes, "
                    "alternative_skus, is_active) "
                    "VALUES (9002, '空白证据旧商品', 1000, "
                    "'/uploads/models/blank.glb', 'ready', 100, 100, 100, '   ', "
                    "'supplier:blank', '2026-09-01 00:00:00', 'user:1', "
                    "'[]', '[]', 1)"
                )
            )
        engine.dispose()
        engine = None

        command.upgrade(config, "head")
        engine = create_engine(database_url)
        columns = {
            column["name"] for column in inspect(engine).get_columns("product_assets")
        }
        assert {
            "product_id",
            "kind",
            "url",
            "source",
            "authorization",
            "review_status",
            "reviewed_at",
            "reviewed_by",
            "review_note",
        } <= columns
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT kind, review_status FROM product_assets "
                    "WHERE product_id = 9001 ORDER BY kind"
                )
            ).all()
        assert rows == [("glb", "approved"), ("image", "pending_review")]
        with engine.connect() as connection:
            blank_evidence_status = connection.execute(
                text(
                    "SELECT review_status FROM product_assets "
                    "WHERE product_id = 9002 AND kind = 'glb'"
                )
            ).scalar_one()
        assert blank_evidence_status == "pending_review"
        engine.dispose()
        engine = None

        command.downgrade(config, "e3f4a5b6c7d8")
        engine = create_engine(database_url)
        assert "product_assets" not in inspect(engine).get_table_names()
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)


@pytest.mark.integration
def test_alembic_upgrades_empty_database_to_current_schema():
    backend_dir = Path(__file__).resolve().parents[2]
    artifacts_dir = backend_dir / ".test_artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    database_path = artifacts_dir / f"haus_migration_test_{uuid4().hex}.db"
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
            "product_assets",
            "agent_approvals",
            "langgraph_checkpoints",
            "langgraph_checkpoint_writes",
            "failure_clusters",
            "failure_triage_imports",
            "room_fact_confirmations",
            "model_provider_circuits",
            "evaluation_run_bindings",
        } <= tables
        approval_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("agent_approvals")
        }
        assert {
            "task_id",
            "turn_id",
            "approval_type",
            "status",
            "request_reason",
            "reason_code",
            "request_context_json",
            "requested_at",
            "client_decision_id",
            "decision",
            "conclusion",
            "decided_by_type",
            "decided_by_id",
            "decided_at",
        } <= approval_columns
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
            for column in inspect(inspection_engine).get_columns("blender_render_jobs")
        }
        assert {
            "request_id",
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
            "error_code",
            "max_attempts",
            "heartbeat_at",
            "execution_deadline_at",
            "next_retry_at",
            "cancel_requested_at",
            "dead_lettered_at",
        } <= render_job_columns
        effect_render_job_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("effect_render_jobs")
        }
        assert {
            "scene_id",
            "scene_version_id",
            "scene_version",
            "scene_snapshot_json",
            "scene_digest",
        } <= effect_render_job_columns
        timeline_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns(
                "task_execution_events"
            )
        }
        assert {
            "task_id",
            "source_type",
            "source_id",
            "attempt",
            "event_code",
            "billing_status",
            "cost_cny",
            "event_key",
            "occurred_at",
        } <= timeline_columns
        uploaded_image_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("uploaded_images")
        }
        assert {
            "analysis_model_call_attempted",
            "analysis_billing_status",
            "analysis_cost_cny",
        } <= uploaded_image_columns
        requirement_parse_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns(
                "requirement_parse_results"
            )
        }
        assert {
            "model_call_attempted",
            "billing_status",
            "cost_cny",
        } <= requirement_parse_columns
        effect_render_job_foreign_keys = {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_table"]
            for foreign_key in inspect(inspection_engine).get_foreign_keys(
                "effect_render_jobs"
            )
        }
        assert effect_render_job_foreign_keys[("scene_id",)] == "design_scenes"
        assert (
            effect_render_job_foreign_keys[("scene_version_id",)]
            == "design_scene_versions"
        )
        rendered_image_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("rendered_images")
        }
        assert "scene_version_id" in rendered_image_columns
        rendered_image_foreign_keys = {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_table"]
            for foreign_key in inspect(inspection_engine).get_foreign_keys(
                "rendered_images"
            )
        }
        assert (
            rendered_image_foreign_keys[("scene_version_id",)]
            == "design_scene_versions"
        )
        generation_run_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("generation_runs")
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
            "request_digest",
            "input_digest",
            "provenance_schema_version",
            "result_revision_id",
            "output_digest",
        } <= generation_run_columns
        uploaded_image_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns("uploaded_images")
        }
        assert {
            "content_digest",
            "original_prediction_json",
            "original_prediction_source",
            "original_prediction_model",
            "original_prediction_digest",
        } <= uploaded_image_columns
        requirement_parse_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns(
                "requirement_parse_results"
            )
        }
        assert "parser_model" in requirement_parse_columns
        evaluation_binding_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns(
                "evaluation_run_bindings"
            )
        }
        assert {
            "generation_run_id",
            "task_id",
            "case_fingerprint",
            "asset_digest",
            "task_input_digest",
            "dataset_split",
            "model",
            "prompt_digest",
            "rules_digest",
            "data_digest",
            "input_digest",
            "provenance_schema_version",
            "prediction_snapshot_json",
            "prediction_digest",
            "requirement_parse_result_id",
            "uploaded_image_id",
            "created_at",
        } <= evaluation_binding_columns
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
        assert generation_run_constraints["uq_generation_runs_task_idempotency"] == {
            "task_id",
            "idempotency_key",
        }
        assert generation_run_constraints["uq_generation_runs_result_revision"] == {
            "result_revision_id"
        }
        generation_foreign_keys = {
            tuple(foreign_key["constrained_columns"]): foreign_key
            for foreign_key in inspect(inspection_engine).get_foreign_keys(
                "generation_runs"
            )
        }
        assert (
            generation_foreign_keys[("result_revision_id",)]["referred_table"]
            == "design_revisions"
        )
        scene_evidence_columns = {
            column["name"]
            for column in inspect(inspection_engine).get_columns(
                "generation_run_scene_evidence"
            )
        }
        assert {
            "generation_run_id",
            "plan_version_id",
            "scene_id",
            "scene_version_id",
            "scene_version",
            "scene_digest",
            "created_at",
        } <= scene_evidence_columns
        scene_evidence_constraints = {
            constraint["name"]: set(constraint["column_names"])
            for constraint in inspect(inspection_engine).get_unique_constraints(
                "generation_run_scene_evidence"
            )
        }
        assert scene_evidence_constraints["uq_generation_run_scene_plan"] == {
            "generation_run_id",
            "plan_version_id",
        }
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
            migrated = (
                connection.execute(
                    text(
                        "SELECT verification_status, availability_status, record_version "
                        "FROM products WHERE sku = 'DRAFT-LEGACY'"
                    )
                )
                .mappings()
                .one()
            )
        assert migrated == {
            "verification_status": "draft",
            "availability_status": "unknown",
            "record_version": 1,
        }
    finally:
        if engine is not None:
            engine.dispose()
        database_path.unlink(missing_ok=True)
