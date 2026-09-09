from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import Product, User
from app.main import app
from app.services import auth_service


def _user(*, user_id: int, role: str) -> User:
    return User(
        id=user_id,
        phone=f"1380000{user_id:04d}",
        nickname=f"catalog-{role}",
        role=role,
        phone_verified=True,
    )


def test_catalog_readiness_requires_factory_and_accepts_region():
    now = datetime.now(timezone.utc)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        customer = _user(user_id=1101, role=auth_service.ROLE_CUSTOMER)
        factory_user = _user(user_id=1102, role=auth_service.ROLE_FACTORY)
        admin = _user(user_id=1103, role=auth_service.ROLE_ADMIN)
        db.add_all(
            [
                customer,
                factory_user,
                admin,
                Product(
                    sku="CATALOG-READY-001",
                    name="已核验沙发",
                    category="沙发",
                    room="客厅",
                    style="现代简约",
                    material="布艺",
                    price=5000,
                    is_active=True,
                    data_origin="merchant",
                    verification_status="verified",
                    availability_status="in_stock",
                    stock_quantity=5,
                    region_codes=["CN-SH"],
                    price_valid_from=now - timedelta(days=1),
                    price_valid_to=now + timedelta(days=1),
                    model_width_mm=2200,
                    model_height_mm=800,
                    model_depth_mm=950,
                ),
            ]
        )
        db.commit()
        customer_token = auth_service.issue_token(customer)
        factory_token = auth_service.issue_token(factory_user)
        admin_token = auth_service.issue_token(admin)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            url = "/api/products/admin/readiness"
            assert client.get(url, params={"region": "CN-SH"}).status_code == 401

            client.cookies.set(settings.auth_cookie_name, customer_token)
            assert client.get(url, params={"region": "CN-SH"}).status_code == 403

            client.cookies.set(settings.auth_cookie_name, factory_token)
            response = client.get(url, params={"region": "cn-sh"})
            assert response.status_code == 200
            body = response.json()
            assert body["region"] == "CN-SH"
            assert body["total"] == 1
            assert body["eligible_total"] == 1
            assert "verification_required" in body["reason_code_counts"]

            client.cookies.set(settings.auth_cookie_name, admin_token)
            assert client.get(url, params={"region": "CN-SH"}).status_code == 200

            assert client.get(url, params={"region": ""}).status_code == 422
            assert client.get(url, params={"region": "CN SH"}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()
