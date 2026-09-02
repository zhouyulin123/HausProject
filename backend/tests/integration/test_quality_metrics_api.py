from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import User
from app.main import app
from app.services import auth_service


def _build_user(*, user_id: int, role: str) -> User:
    return User(
        id=user_id,
        phone=f"1380000{user_id:04d}",
        nickname=f"quality-{role}",
        role=role,
        phone_verified=True,
    )


def test_quality_summary_requires_admin_and_validates_window():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        customer = _build_user(user_id=1001, role=auth_service.ROLE_CUSTOMER)
        admin = _build_user(user_id=1002, role=auth_service.ROLE_ADMIN)
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
            assert client.get("/api/admin/quality/summary").status_code == 401

            client.cookies.set(settings.auth_cookie_name, customer_token)
            assert client.get("/api/admin/quality/summary").status_code == 403

            client.cookies.set(settings.auth_cookie_name, admin_token)
            response = client.get(
                "/api/admin/quality/summary",
                params={"window_days": 7},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["window_days"] == 7
            assert body["generation"]["total"] == 0
            assert body["agent"]["turn_total"] == 0
            assert body["layout"]["total"] == 0
            assert "message" not in str(body).lower()
            assert "phone" not in str(body).lower()

            assert client.get(
                "/api/admin/quality/summary",
                params={"window_days": 0},
            ).status_code == 422
            assert client.get(
                "/api/admin/quality/summary",
                params={"window_days": 366},
            ).status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()
