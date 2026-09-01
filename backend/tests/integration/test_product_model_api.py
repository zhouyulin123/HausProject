import json
from pathlib import Path
import shutil
import struct
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.api.routes import products
from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import Product, User


def _glb_bytes() -> bytes:
    payload = json.dumps({"asset": {"version": "2.0"}}).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    chunk = struct.pack("<I4s", len(payload), b"JSON") + payload
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunk)) + chunk


@pytest.fixture
def product_api(monkeypatch):
    artifact_root = Path(__file__).resolve().parents[2] / ".test_artifacts"
    upload_dir = artifact_root / f"model-upload-{uuid4().hex}"
    upload_dir.mkdir(parents=True)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(
            Product(
                sku="SOFA-3D-001",
                name="测试沙发",
                category="沙发",
                room="客厅",
                style="现代简约",
                price=6800,
                model_width_mm=2200,
                model_height_mm=850,
                model_depth_mm=950,
            )
        )
        db.add(
            User(
                id=999,
                phone="13800009999",
                nickname="13800009999",
                role="factory",
                phone_verified=True,
            )
        )
        db.commit()

    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))
    app = FastAPI()
    app.include_router(products.router, prefix="/api/products")

    def override_db():
        with factory() as db:
            yield db

    def override_current_user():
        with factory() as db:
            return db.get(User, 999)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user
    try:
        with TestClient(app) as client:
            yield client, upload_dir
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


@pytest.mark.integration
def test_upload_product_model_validates_and_binds_randomized_glb(product_api):
    client, upload_dir = product_api

    response = client.post(
        "/api/products/1/model",
        files={"file": ("supplier sofa.glb", _glb_bytes(), "model/gltf-binary")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model_status"] == "ready"
    assert body["model_url"].startswith("/uploads/models/")
    stored_name = body["model_url"].rsplit("/", 1)[-1]
    assert stored_name != "supplier sofa.glb"
    assert (upload_dir / "models" / stored_name).read_bytes() == _glb_bytes()


@pytest.mark.integration
def test_upload_product_model_rejects_fake_glb(product_api):
    client, upload_dir = product_api

    response = client.post(
        "/api/products/1/model",
        files={"file": ("sofa.glb", b"not-a-model", "model/gltf-binary")},
    )

    assert response.status_code == 422
    assert not (upload_dir / "models").exists()


@pytest.mark.integration
def test_product_lifecycle_fields_round_trip_and_verifier_is_server_owned(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        json={
            "sku": "TABLE-001",
            "name": "可编辑餐桌草稿",
            "category": "餐桌",
            "room": "餐厅",
            "style": "现代简约",
            "price": 3200,
            "availability_status": "in_stock",
            "stock_quantity": 8,
            "region_codes": ["CN-SH"],
            "lead_time_days_min": 2,
            "lead_time_days_max": 5,
            "price_valid_from": "2026-09-01T00:00:00Z",
            "price_valid_to": "2026-12-31T23:59:59Z",
            "data_version": "catalog-q3",
            "alternative_skus": ["TABLE-002"],
            "model_width_mm": 1600,
            "model_depth_mm": 850,
            "model_height_mm": 750,
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["verification_status"] == "draft"
    assert body["availability_status"] == "in_stock"
    assert body["region_codes"] == ["CN-SH"]
    assert body["alternative_skus"] == ["TABLE-002"]
    assert body["record_version"] == 1

    verified = client.patch(
        f"/api/products/{body['id']}",
        json={"verification_status": "verified", "verified_by": "spoofed-user"},
    )

    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"
    assert verified.json()["verified_by"] == "user:999"
    assert verified.json()["verified_at"] is not None
    assert verified.json()["record_version"] == 2
