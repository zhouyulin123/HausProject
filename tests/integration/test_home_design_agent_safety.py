"""整屋建议失败关闭、独立计费与迁移检查。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db.models import (
    HomeDesign,
    HomeDesignVersion,
    HomeDesignAgentTurn,
    AnonymousSessionTask,
)
from app.services import llm_service
from tests.integration.test_home_design_agent_api import context, turn  # noqa: F401
from tests.integration.test_home_design_api import context as home_context  # noqa: F401
from tests.integration.test_spatial_api import context as spatial_context  # noqa: F401


def test_bad_geometry_never_returns_applicable_candidate(context, monkeypatch):  # noqa: F811
    client, url, headers, _, _, _, _, _ = context
    monkeypatch.setattr(
        llm_service,
        "plan_home_design",
        lambda **kw: {
            "outcome": "proposal",
            "message": "移出房间",
            "operations": [
                {
                    "type": "patch_object",
                    "id": "o1",
                    "changes": {"position": {"x": 999, "y": 0, "z": 0}},
                }
            ],
        },
    )
    result = client.post(url, headers=headers, json=turn())
    assert result.json()["outcome"] == "invalid"
    assert result.json()["candidate_document"] is None
    assert not result.json()["validation"]["valid"]


def test_rate_limit_no_model_and_changed_request_conflict(context, monkeypatch):  # noqa: F811
    from app.services.home_design_agent_service import open_geometry_rate_limiter

    client, url, headers, _, calls, _, _, _ = context
    monkeypatch.setattr(open_geometry_rate_limiter, "retry_after", lambda *a, **kw: 60)
    limited = client.post(url, headers=headers, json=turn())
    assert limited.status_code == 429
    assert not calls
    assert client.post(url, headers=headers, json=turn()).json() == limited.json()
    changed = turn()
    changed["message"] = "修改颜色"
    assert client.post(url, headers=headers, json=changed).status_code == 409


def test_ownership_revoked_during_model_call_discards_result(context, monkeypatch):  # noqa: F811
    client, url, headers, _, _, _, _, factory = context
    original = llm_service.plan_home_design

    def revoked(**kw):
        with factory() as db:
            db.execute(delete(AnonymousSessionTask))
            db.commit()
        return original(**kw)

    monkeypatch.setattr(llm_service, "plan_home_design", revoked)
    result = client.post(url, headers=headers, json=turn())
    assert result.status_code == 404
    assert "candidate_document" not in result.text


def test_abandoned_running_turn_expires_without_rebilling(context):  # noqa: F811
    client, url, headers, _, calls, _, _, factory = context
    assert client.post(url, headers=headers, json=turn()).status_code == 200
    with factory() as db:
        row = db.scalar(select(HomeDesignAgentTurn))
        row.status = "running"
        row.response_json = None
        row.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        db.commit()
    replay = client.post(url, headers=headers, json=turn())
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "home_agent_expired"
    assert len(calls) == 1


def test_no_saved_design_blocks_without_call(context):  # noqa: F811
    client, url, headers, _, calls, _, _, factory = context
    with factory() as db:
        db.execute(delete(HomeDesignVersion))
        db.execute(delete(HomeDesign))
        db.commit()
    response = client.post(url, headers=headers, json=turn())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "home_agent_design_required"
    assert not calls


def test_home_agent_migration_isolated_upgrade_downgrade(tmp_path):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect
    from app.db.database import Base
    from app.db.schema_readiness import expected_migration_heads

    path = (
        Path(__file__).resolve().parents[2]
        / "backend/migrations/versions/c3d4e5f6a7b8_add_home_design_agent_turns.py"
    )
    spec = importlib.util.spec_from_file_location("home_agent_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert expected_migration_heads() == ("f6a7b8c9d0e1",)
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE design_tasks (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert {
                c["name"]
                for c in inspect(connection).get_columns("home_design_agent_turns")
            } == set(Base.metadata.tables["home_design_agent_turns"].columns.keys())
            migration.downgrade()
            assert (
                "home_design_agent_turns" not in inspect(connection).get_table_names()
            )
    engine.dispose()


def test_cost_governance_isolated_and_replay_does_not_charge(context, monkeypatch):  # noqa: F811
    from app.db.models import ModelCallLedger
    from types import SimpleNamespace

    client, url, headers, _, _, _, _, factory = context
    original = llm_service.plan_home_design

    def metered(**kw):
        hooks = llm_service._model_call_governance_hooks.get()
        permit = hooks.before_call(
            provider_key="test-home-provider",
            model="test-model",
            modality="text",
            estimated_cost_cny=0.01,
        )
        llm_service._mark_model_call_attempted()
        llm_service._capture_model_usage(
            SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20)
        )
        hooks.record_success(
            permit,
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            actual_cost_cny=0.005,
        )
        return original(**kw)

    monkeypatch.setattr(llm_service, "plan_home_design", metered)
    result = client.post(url, headers=headers, json=turn())
    assert result.status_code == 200, result.text
    assert client.post(url, headers=headers, json=turn()).json() == result.json()
    with factory() as db:
        entries = db.scalars(select(ModelCallLedger)).all()
        assert len(entries) == 1
        assert entries[0].status == "succeeded"


def test_context_uses_only_recent_six_and_history_cursor(context, monkeypatch):  # noqa: F811
    from app.services.home_design_agent_service import open_geometry_rate_limiter

    client, url, headers, _, calls, _, _, _ = context
    monkeypatch.setattr(
        open_geometry_rate_limiter, "retry_after", lambda *a, **kw: None
    )
    for i in range(8):
        assert client.post(url, headers=headers, json=turn(str(i))).status_code == 200
    assert len(calls[-1]["context"]["history"]) == 6
    page = client.get(url + "?limit=3", headers=headers).json()
    next_page = client.get(
        url + f"?limit=3&before_id={page['next_before_id']}", headers=headers
    ).json()
    assert len(page["turns"]) == len(next_page["turns"]) == 3
    assert not (
        {t["turn_id"] for t in page["turns"]}
        & {t["turn_id"] for t in next_page["turns"]}
    )


def test_corrupt_saved_version_blocks_model(context):  # noqa: F811
    client, url, headers, _, calls, _, _, factory = context
    with factory() as db:
        db.execute(delete(HomeDesignVersion))
        db.commit()
    response = client.post(url, headers=headers, json=turn())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "home_agent_state_invalid"
    assert not calls


def test_late_completion_and_readonly_expired_history(context, monkeypatch):  # noqa: F811
    client, url, headers, _, _, _, _, factory = context
    original = llm_service.plan_home_design

    def late(**kw):
        with factory() as db:
            row = db.scalar(select(HomeDesignAgentTurn))
            row.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
            db.commit()
        history = client.get(url, headers=headers).json()["turns"][0]
        assert history["status"] == "failed"
        assert history["error_code"] == "home_agent_expired"
        with factory() as db:
            assert db.scalar(select(HomeDesignAgentTurn)).status == "running"
        return original(**kw)

    monkeypatch.setattr(llm_service, "plan_home_design", late)
    result = client.post(url, headers=headers, json=turn())
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "home_agent_expired"


def test_no_store_and_actual_retry_after(context, monkeypatch):  # noqa: F811
    from app.services.home_design_agent_service import open_geometry_rate_limiter

    client, url, headers, _, _, _, _, _ = context
    monkeypatch.setattr(open_geometry_rate_limiter, "retry_after", lambda *a, **kw: 37)
    response = client.post(url, headers=headers, json=turn())
    assert response.headers["Retry-After"] == "37"
    assert response.headers["Cache-Control"] == "no-store"
    replay = client.post(url, headers=headers, json=turn())
    assert replay.headers["Retry-After"] == "37"
    assert client.get(url, headers=headers).headers["Cache-Control"] == "no-store"


def test_corrupt_space_and_completed_response_fail_closed(context):  # noqa: F811
    from app.db.models import DesignSpaceVersion

    client, url, headers, _, calls, _, _, factory = context
    assert client.post(url, headers=headers, json=turn()).status_code == 200
    with factory() as db:
        row = db.scalar(select(HomeDesignAgentTurn))
        row.response_json = {**row.response_json, "space_version": 999}
        db.commit()
    assert client.get(url, headers=headers).status_code == 409
    assert client.post(url, headers=headers, json=turn()).status_code == 409
    with factory() as db:
        space = db.scalar(
            select(DesignSpaceVersion).where(DesignSpaceVersion.version == 2)
        )
        space.document_json = {"broken": True}
        db.commit()
    assert client.post(url, headers=headers, json=turn("new")).status_code == 409
    assert len(calls) == 1
