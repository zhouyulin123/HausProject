from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import User
from app.main import app
from app.services import auth_service


def _report():
    return {
        "schema_version": "1.0",
        "report_id": "failure-triage-001",
        "verification_status": "verified",
        "taxonomy_version": "taxonomy-1",
        "data_version": "data-1",
        "candidate_version": "candidate-1",
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


def test_failure_triage_api_is_admin_only_strict_and_private():
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
            serialized = str(body).lower()
            assert "case_id" not in serialized
            assert "private-case" not in serialized
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()

