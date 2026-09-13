from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import app
from app.services.worker_presence_service import (
    WorkerReadinessCheck,
    WorkerReadinessSnapshot,
)


class HealthySession:
    def execute(self, _statement):
        return object()


def _check(status: str, active_workers: int) -> WorkerReadinessCheck:
    return WorkerReadinessCheck(
        status=status,
        active_workers=active_workers,
        last_heartbeat_at=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc),
        stale_after_seconds=45,
    )


def test_ready_reports_each_required_worker_without_exposing_worker_ids(monkeypatch):
    monkeypatch.setattr("app.main.database_schema_is_current", lambda _db: True)
    monkeypatch.setattr(
        "app.main.worker_presence_service.readiness_snapshot",
        lambda *_args, **_kwargs: WorkerReadinessSnapshot(
            ready=True,
            checks={
                "generation": _check("ok", 2),
                "effect_render": _check("ok", 1),
                "blender": _check("ok", 1),
            },
        ),
    )
    app.dependency_overrides[get_db] = lambda: HealthySession()
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["checks"]["workers"]["status"] == "ok"
    assert payload["checks"]["workers"]["required"] == {
        "generation": {
            "status": "ok",
            "activeWorkers": 2,
            "lastHeartbeatAt": "2026-09-11T10:00:00Z",
            "staleAfterSeconds": 45,
        },
        "effect_render": {
            "status": "ok",
            "activeWorkers": 1,
            "lastHeartbeatAt": "2026-09-11T10:00:00Z",
            "staleAfterSeconds": 45,
        },
        "blender": {
            "status": "ok",
            "activeWorkers": 1,
            "lastHeartbeatAt": "2026-09-11T10:00:00Z",
            "staleAfterSeconds": 45,
        },
    }
    assert "worker-" not in response.text


def test_ready_returns_503_when_any_required_worker_is_not_fresh(monkeypatch):
    monkeypatch.setattr("app.main.database_schema_is_current", lambda _db: True)
    monkeypatch.setattr(
        "app.main.worker_presence_service.readiness_snapshot",
        lambda *_args, **_kwargs: WorkerReadinessSnapshot(
            ready=False,
            checks={
                "generation": _check("ok", 1),
                "effect_render": _check("stale", 0),
                "blender": _check("missing", 0),
            },
        ),
    )
    app.dependency_overrides[get_db] = lambda: HealthySession()
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["checks"]["workers"]["status"] == "unavailable"
    assert payload["checks"]["workers"]["required"]["effect_render"]["status"] == (
        "stale"
    )


def test_ready_fails_closed_when_worker_heartbeat_query_fails(monkeypatch):
    monkeypatch.setattr("app.main.database_schema_is_current", lambda _db: True)

    def raise_query_error(*_args, **_kwargs):
        raise RuntimeError("sensitive database detail")

    monkeypatch.setattr(
        "app.main.worker_presence_service.readiness_snapshot",
        raise_query_error,
    )
    app.dependency_overrides[get_db] = lambda: HealthySession()
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["checks"]["workers"] == {
        "status": "unavailable",
        "required": {},
    }
    assert "sensitive database detail" not in response.text
