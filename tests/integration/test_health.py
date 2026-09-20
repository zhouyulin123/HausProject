import logging

import pytest
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


class BrokenSession:
    def execute(self, _statement):
        raise RuntimeError("database unavailable")


def _override_schema_check(monkeypatch, *, is_current: bool) -> None:
    monkeypatch.setattr(
        "app.main.database_schema_is_current",
        lambda _db: is_current,
    )
    if is_current:
        monkeypatch.setattr(
            "app.main.worker_presence_service.readiness_snapshot",
            lambda *_args, **_kwargs: WorkerReadinessSnapshot(
                ready=True,
                checks={
                    worker_type: WorkerReadinessCheck(
                        status="ok",
                        active_workers=1,
                        last_heartbeat_at=None,
                        stale_after_seconds=45,
                    )
                    for worker_type in ("generation", "effect_render", "blender")
                },
            ),
        )


def test_ready_reports_database_health(monkeypatch):
    _override_schema_check(monkeypatch, is_current=True)
    app.dependency_overrides[get_db] = lambda: HealthySession()
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"
    assert response.json()["checks"]["database_schema"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]


def test_ready_does_not_report_model_ready_without_cost_configuration(monkeypatch):
    _override_schema_check(monkeypatch, is_current=True)
    monkeypatch.setattr("app.main.settings.llm_api_key", "configured-key")
    monkeypatch.setattr("app.main.settings.llm_input_price_per_mtok", None)
    monkeypatch.setattr("app.main.settings.llm_output_price_per_mtok", None)
    app.dependency_overrides[get_db] = lambda: HealthySession()
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.json()["checks"]["llm"] == "cost_guard_unconfigured"


def test_production_readiness_fails_closed_when_required_model_is_not_ready(
    monkeypatch,
):
    _override_schema_check(monkeypatch, is_current=True)
    monkeypatch.setattr("app.main.settings.app_env", "production")
    monkeypatch.setattr("app.main.settings.llm_api_key", "configured-key")
    monkeypatch.setattr("app.main.settings.llm_input_price_per_mtok", None)
    monkeypatch.setattr("app.main.settings.llm_output_price_per_mtok", None)
    app.dependency_overrides[get_db] = lambda: HealthySession()
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["checks"]["llm"] == "cost_guard_unconfigured"


def test_ready_returns_503_without_leaking_database_error(monkeypatch):
    _override_schema_check(monkeypatch, is_current=True)
    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"
    assert response.json()["checks"]["database_schema"] == "not_checked"
    assert "database unavailable" not in response.text


def test_ready_returns_503_when_database_schema_requires_migration(monkeypatch):
    _override_schema_check(monkeypatch, is_current=False)
    app.dependency_overrides[get_db] = lambda: HealthySession()
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "ok"
    assert response.json()["checks"]["database_schema"] == "migration_required"


def test_request_id_is_preserved_when_safe_and_replaced_when_invalid(monkeypatch):
    _override_schema_check(monkeypatch, is_current=True)
    app.dependency_overrides[get_db] = lambda: HealthySession()
    try:
        client = TestClient(app)
        preserved = client.get(
            "/ready",
            headers={"X-Request-ID": "customer-trace-001"},
        )
        replaced = client.get(
            "/ready",
            headers={"X-Request-ID": "bad request id"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert preserved.headers["x-request-id"] == "customer-trace-001"
    assert replaced.headers["x-request-id"] != "bad request id"
    assert len(replaced.headers["x-request-id"]) == 36


def test_controlled_deployment_exposes_configured_build_digest(monkeypatch):
    build_digest = "sha256:" + "a" * 64
    monkeypatch.setenv("APP_BUILD_DIGEST", build_digest)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.headers["x-app-build-digest"] == build_digest


def test_http_completion_log_keeps_request_correlation_and_dimensions(caplog):
    with caplog.at_level(logging.INFO, logger="app.http"):
        response = TestClient(app).get(
            "/health",
            headers={"X-Request-ID": "customer-trace-log-001"},
        )

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "http_request_completed"
    ]
    assert response.status_code == 200
    assert len(records) == 1
    record = records[0]
    assert record.request_id == "customer-trace-log-001"
    assert record.http_method == "GET"
    assert record.http_path == "/health"
    assert record.status_code == 200
    assert isinstance(record.duration_ms, float)
    assert record.duration_ms >= 0


@pytest.mark.parametrize(
    ("path", "expected_path"),
    (
        ("/api/home-shares/{token}", "/api/home-shares/[redacted]"),
        ("/api/shares/{token}", "/api/shares/[redacted]"),
        (
            "/api/design/shares/{token}/revoke",
            "/api/design/shares/[redacted]/revoke",
        ),
    ),
)
def test_public_share_middleware_preserves_privacy(
    monkeypatch, caplog, path, expected_path
):
    from app.services import home_delivery_snapshot_service

    def unavailable(*args):
        raise LookupError("分享不存在或已失效")

    monkeypatch.setattr(home_delivery_snapshot_service, "public_share", unavailable)
    token = "x" * 43
    with caplog.at_level(logging.INFO, logger="app.http"):
        response = TestClient(app).get(path.format(token=token))
    assert response.status_code in {404, 405}
    records = [r for r in caplog.records if getattr(r, "event", None) == "http_request_completed"]
    assert records[0].http_path == expected_path
    assert token not in records[0].http_path
