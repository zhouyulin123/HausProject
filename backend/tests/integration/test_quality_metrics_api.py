from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import DesignFeedbackEvent, DesignTask, User
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
        task = DesignTask(status="completed", progress=100)
        db.add(task)
        db.flush()
        db.add(
            DesignFeedbackEvent(
                task_id=task.id,
                client_event_id="private-feedback-api-001",
                action_type="replace",
                payload_hash="private-payload-hash",
                room_id="private-room-api",
                instance_id="private-instance-api",
                source_sku="PRIVATE-OLD-SKU",
                target_sku="PRIVATE-NEW-SKU",
                created_at=datetime.now(timezone.utc),
            )
        )
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
            assert body["feedback"] == {
                "total": 1,
                "action_counts": {
                    "adopt": 0,
                    "remove": 0,
                    "replace": 1,
                    "move": 0,
                    "final_select": 0,
                },
                "modification_total": 1,
                "modification_rate": 1.0,
                "final_select_total": 0,
                "satisfaction_count": 0,
                "satisfaction_mean": None,
            }
            assert "message" not in str(body).lower()
            assert "phone" not in str(body).lower()
            assert "private-feedback" not in str(body)
            assert "private-room" not in str(body)
            assert "PRIVATE-OLD-SKU" not in str(body)

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
