from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import User
from app.main import app
from app.services import auth_service
from app.services.failure_triage_signature import sign_failure_triage_payload


_SIGNING_KEY = "test-report-signing-key-at-least-32-bytes"


def _report():
    payload = {
        "schema_version": "1.0",
        "report_id": "failure-triage-001",
        "taxonomy_version": "taxonomy-1",
        "data_version": "data-1",
        "candidate_version": "candidate-1",
        "signature_algorithm": "hmac-sha256",
        "signature_key_id": "eval-key-v1",
        "generated_at": "2026-09-02T08:00:00Z",
        "failures": [
            {
                "failure_type": "quote",
                "code": "quote_mismatch",
                "severity": "critical",
                "occurrence_count": 4,
                "affected_count": 3,
            }
        ],
    }
    payload["signature"] = sign_failure_triage_payload(
        payload,
        signing_key=_SIGNING_KEY,
    )
    return payload


def test_failure_triage_api_is_admin_only_strict_and_private(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        customer = User(id=1101, phone="13800001101", role="customer", phone_verified=True)
        admin = User(id=1102, phone="13800001102", role="admin", phone_verified=True)
        db.add_all([customer, admin])
        db.commit()
        customer_token = auth_service.issue_token(customer)
        admin_token = auth_service.issue_token(admin)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(settings, "eval_report_signing_key", _SIGNING_KEY)
    try:
        with TestClient(app) as client:
            url = "/api/admin/quality/failure-clusters/sync"
            assert client.post(url, json=_report()).status_code == 401
            client.cookies.set(settings.auth_cookie_name, customer_token)
            assert client.post(url, json=_report()).status_code == 403

            client.cookies.set(settings.auth_cookie_name, admin_token)
            invalid = _report()
            invalid["failures"][0]["case_id"] = "private-case-001"
            assert client.post(url, json=invalid).status_code == 422

            forged = _report()
            forged["failures"][0]["occurrence_count"] = 99
            assert client.post(url, json=forged).status_code == 422

            created = client.post(url, json=_report())
            duplicate = client.post(url, json=_report())
            assert created.status_code == duplicate.status_code == 200
            assert created.json()["imported"] is True
            assert duplicate.json()["imported"] is False

            listing = client.get("/api/admin/quality/failure-clusters")
            assert listing.status_code == 200
            body = listing.json()
            assert body["summary"]["by_severity"] == {"critical": 1}
            assert body["summary"]["by_status"] == {"open": 1}
            assert body["items"][0]["code"] == "quote_mismatch"
            cluster_id = body["items"][0]["id"]
            cluster_url = f"/api/admin/quality/failure-clusters/{cluster_id}"
            assert client.patch(
                cluster_url,
                json={"status": "in_progress", "owner": "admin", "case_id": "x"},
            ).status_code == 422
            assert client.patch(
                cluster_url,
                json={"status": "resolved", "fixed_version": "rules-2"},
            ).status_code == 409
            assert client.patch(
                cluster_url,
                json={"status": "in_progress", "owner": "quality-admin"},
            ).status_code == 200
            assert client.patch(
                cluster_url,
                json={"status": "resolved", "fixed_version": "rules-2"},
            ).status_code == 200
            verified = client.patch(
                cluster_url,
                json={"status": "verified", "verified_version": "eval-2"},
            )
            assert verified.status_code == 200
            assert verified.json()["status"] == "verified"
            assert verified.json()["fixed_version"] == "rules-2"
            assert verified.json()["verified_version"] == "eval-2"
            serialized = str(body).lower()
            assert "case_id" not in serialized
            assert "private-case" not in serialized
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_failure_triage_sync_requires_server_signing_key(monkeypatch):
    monkeypatch.setattr(settings, "eval_report_signing_key", "")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        admin = User(id=1201, phone="13800001201", role="admin", phone_verified=True)
        db.add(admin)
        db.commit()
        token = auth_service.issue_token(admin)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            client.cookies.set(settings.auth_cookie_name, token)
            response = client.post(
                "/api/admin/quality/failure-clusters/sync",
                json=_report(),
            )
            assert response.status_code == 503
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()
