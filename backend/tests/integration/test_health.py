from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import app


class HealthySession:
    def execute(self, _statement):
        return object()


class BrokenSession:
    def execute(self, _statement):
        raise RuntimeError("database unavailable")


def test_ready_reports_database_health():
    app.dependency_overrides[get_db] = lambda: HealthySession()
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]


def test_ready_returns_503_without_leaking_database_error():
    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"
    assert "database unavailable" not in response.text
