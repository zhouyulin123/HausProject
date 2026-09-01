from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import Base, get_db
from app.main import app
from app.services import auth_service


def test_login_sets_http_only_cookie_and_cookie_authenticates_me():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)()

    def override_db():
        yield testing_session

    app.dependency_overrides[get_db] = override_db
    try:
        auth_service.send_sms_code(testing_session, "13800000009")
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/login",
                json={"phone": "13800000009", "code": settings.sms_mock_code},
            )

            assert response.status_code == 200
            assert "token" not in response.json()
            cookie_header = response.headers["set-cookie"].lower()
            assert "httponly" in cookie_header
            assert "samesite=strict" in cookie_header
            assert client.get("/api/auth/me").status_code == 200

            logout_response = client.post("/api/auth/logout")
            assert logout_response.status_code == 200
            assert "max-age=0" in logout_response.headers["set-cookie"].lower()
            assert client.get("/api/auth/me").status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)
        testing_session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
