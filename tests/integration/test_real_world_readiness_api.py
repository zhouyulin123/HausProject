import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.routes import admin
from app.db.models import User
from app.main import app
from app.services import auth_service
from app.services.real_world_readiness_service import RealWorldReadinessError


def _user(user_id: int, role: str) -> User:
    return User(
        id=user_id,
        phone=f"1390000{user_id:04d}",
        nickname=f"readiness-{role}",
        role=role,
        phone_verified=True,
    )


def test_real_world_readiness_requires_admin_and_hides_case_content(monkeypatch):
    customer = _user(9201, auth_service.ROLE_CUSTOMER)
    factory = _user(9202, auth_service.ROLE_FACTORY)
    admin_user = _user(9204, auth_service.ROLE_ADMIN)

    app.dependency_overrides[get_current_user] = lambda: customer
    try:
        with TestClient(app) as client:
            assert client.get("/api/admin/quality/real-world-readiness").status_code == 403

        app.dependency_overrides[get_current_user] = lambda: factory
        with TestClient(app) as client:
            assert client.get("/api/admin/quality/real-world-readiness").status_code == 403

        app.dependency_overrides[get_current_user] = lambda: admin_user
        checked_at = datetime(2026, 9, 8, tzinfo=timezone.utc)
        monkeypatch.setattr(
            admin,
            "build_real_world_readiness",
            lambda: {
                "manifest_version": "2.0",
                "dataset_id": "dataset-1",
                "total": 2,
                "eligible_total": 1,
                "private_real_eligible_total": 1,
                "blocked_total": 1,
                "split_counts": {
                    "development": {"total": 1, "eligible": 1},
                    "regression": {"total": 1, "eligible": 0},
                    "blind": {"total": 0, "eligible": 0},
                },
                "consent_status_counts": {"granted": 1, "pending": 1},
                "annotation_status_counts": {"ready": 1, "pending": 1},
                "blocker_counts": {"consent_not_granted": 1},
                "minimum_required": 20,
                "minimum_met": False,
                "checked_at": checked_at,
            },
        )
        with TestClient(app) as client:
            response = client.get("/api/admin/quality/real-world-readiness")
            assert response.status_code == 200
            body = response.json()
            assert body["dataset_id"] == "dataset-1"
            assert body["split_counts"]["regression"] == {"total": 1, "eligible": 0}
            assert "case_id" not in json.dumps(body)
            assert "asset_path" not in json.dumps(body)
            assert "task_input" not in json.dumps(body)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_real_world_readiness_returns_service_unavailable_on_manifest_error(monkeypatch):
    admin_user = _user(9203, auth_service.ROLE_ADMIN)
    app.dependency_overrides[get_current_user] = lambda: admin_user
    monkeypatch.setattr(
        admin,
        "build_real_world_readiness",
        lambda: (_ for _ in ()).throw(
            RealWorldReadinessError("真实案例清单不可用")
        ),
    )
    try:
        with TestClient(app) as client:
            response = client.get("/api/admin/quality/real-world-readiness")
            assert response.status_code == 503
            assert response.json()["detail"] == "真实案例清单不可用"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
