import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import open_geometry
from app.db.database import Base, get_db
from app.db.models import DesignTask, TaskExecutionEvent
from app.schemas.open_geometry import OpenGeometryOperation
from app.services import open_geometry_service
from app.services.anonymous_session_service import attach_task, create_anonymous_session


OPERATION = TypeAdapter(OpenGeometryOperation)


def _design():
    return {
        "schema_version": "furniture-open-geometry/1.0",
        "name": "弧形椅",
        "description": "",
        "materials": [
            {"id": "frame", "name": "框架", "base_color": "#304038", "roughness": 0.4, "metallic": 0.7}
        ],
        "parts": [
            {"id": "arc", "name": "连续弧形主体", "material_id": "frame", "parent_id": None,
             "position_mm": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0],
             "geometry": {"type": "sweep", "path_mm": [[-400.0, 30.0, 0.0], [0.0, 500.0, -200.0], [400.0, 30.0, 0.0]], "radius_mm": 30.0, "tubular_segments": 24, "radial_segments": 8, "closed": False}}
        ],
    }


@pytest.fixture
def api_context(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = create_anonymous_session(db)
        stranger = create_anonymous_session(db)
        task = DesignTask(status="waiting_input", active_mode="custom_furniture", agent_state_json={})
        db.add(task)
        db.commit()
        attach_task(db, owner.id, task.id)
        values = owner.id, stranger.id, task.id

    monkeypatch.setattr(
        open_geometry_service,
        "_plan_operation",
        lambda _instruction, _current, _history, _feedback: OPERATION.validate_python({"operation": "create", "design": _design()}),
    )
    app = FastAPI()
    app.include_router(open_geometry.router, prefix="/api/design/tasks")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, *values, factory


@pytest.mark.integration
def test_open_geometry_api_create_refresh_undo_and_idempotency(api_context):
    client, owner_id, _, task_id, _ = api_context
    headers = {"X-Session-ID": owner_id}
    body = {"client_mutation_id": "open-create", "base_version": 0, "instruction": "创建弧形椅"}
    created = client.post(f"/api/design/tasks/{task_id}/open-geometry/commands", headers=headers, json=body)
    repeated = client.post(f"/api/design/tasks/{task_id}/open-geometry/commands", headers=headers, json=body)
    refreshed = client.get(f"/api/design/tasks/{task_id}/open-geometry", headers=headers)

    assert created.status_code == repeated.status_code == refreshed.status_code == 200
    assert created.json() == repeated.json()
    assert refreshed.json()["current_version"] == 1
    assert refreshed.json()["current"]["model_spec"]["确定性建模规则"]["部件"]


@pytest.mark.integration
def test_open_geometry_api_hides_foreign_task(api_context):
    client, _, stranger_id, task_id, _ = api_context
    response = client.get(
        f"/api/design/tasks/{task_id}/open-geometry",
        headers={"X-Session-ID": stranger_id},
    )
    assert response.status_code == 404


@pytest.mark.integration
def test_open_geometry_get_fails_closed_for_corrupted_persisted_state(api_context):
    client, owner_id, _, task_id, factory = api_context
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.agent_state_json = {
            "open_geometry_furniture": {
                "current_version": 1,
                "current": None,
                "history": [],
            }
        }
        db.commit()

    response = client.get(
        f"/api/design/tasks/{task_id}/open-geometry",
        headers={"X-Session-ID": owner_id},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "invalid_state"


@pytest.mark.integration
def test_invalid_model_output_returns_structured_error_and_preserves_empty_state(api_context, monkeypatch):
    client, owner_id, _, task_id, factory = api_context
    monkeypatch.setattr(
        open_geometry_service,
        "_plan_operation",
        lambda *_: OPERATION.validate_python({"operation": "unsupported", "reason": "需要 NURBS 曲面"}),
    )
    response = client.post(
        f"/api/design/tasks/{task_id}/open-geometry/commands",
        headers={"X-Session-ID": owner_id},
        json={"client_mutation_id": "unsupported", "base_version": 0, "instruction": "创建 NURBS 自由曲面"},
    )
    state = client.get(f"/api/design/tasks/{task_id}/open-geometry", headers={"X-Session-ID": owner_id})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_geometry"
    assert state.json()["current"] is None
    with factory() as db:
        event = db.query(TaskExecutionEvent).filter_by(task_id=task_id).one()
        assert event.event_code == "agent.open_geometry.failed"


@pytest.mark.integration
def test_open_geometry_command_rate_limit_has_retry_after(api_context, monkeypatch):
    from app.services.scene_agent_rate_limit import SceneAgentRateLimiter

    client, owner_id, _, task_id, _ = api_context
    monkeypatch.setattr(open_geometry, "open_geometry_rate_limiter", SceneAgentRateLimiter(max_requests=1, window_seconds=60))
    headers = {"X-Session-ID": owner_id}
    first = client.post(
        f"/api/design/tasks/{task_id}/open-geometry/commands",
        headers=headers,
        json={"client_mutation_id": "limit-1", "base_version": 0, "instruction": "创建弧形椅"},
    )
    limited = client.post(
        f"/api/design/tasks/{task_id}/open-geometry/commands",
        headers=headers,
        json={"client_mutation_id": "limit-2", "base_version": 1, "instruction": "靠背更弯"},
    )
    assert first.status_code == 200
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


@pytest.mark.integration
def test_failed_open_geometry_command_cannot_bypass_limit_by_reusing_id(
    api_context,
    monkeypatch,
):
    from app.services.scene_agent_rate_limit import SceneAgentRateLimiter

    client, owner_id, _, task_id, _ = api_context
    monkeypatch.setattr(
        open_geometry,
        "open_geometry_rate_limiter",
        SceneAgentRateLimiter(max_requests=1, window_seconds=60),
    )
    calls = []
    monkeypatch.setattr(
        open_geometry_service,
        "_plan_operation",
        lambda *_: calls.append(True)
        or OPERATION.validate_python(
            {"operation": "unsupported", "reason": "需要 NURBS 曲面"}
        ),
    )
    body = {
        "client_mutation_id": "same-failed-command",
        "base_version": 0,
        "instruction": "创建 NURBS 自由曲面",
    }

    failed = client.post(
        f"/api/design/tasks/{task_id}/open-geometry/commands",
        headers={"X-Session-ID": owner_id},
        json=body,
    )
    limited = client.post(
        f"/api/design/tasks/{task_id}/open-geometry/commands",
        headers={"X-Session-ID": owner_id},
        json=body,
    )

    assert failed.status_code == 422
    assert limited.status_code == 429
    assert calls == [True]
