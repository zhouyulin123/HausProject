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
                model_license="供应商书面商用授权",
                model_source="supplier:SOFA-3D-001",
            )
        )
        db.add(
            User(
                id=999,
                phone="13800009999",
                nickname="13800009999",
                role="admin",
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
    assert body["model_status"] == "pending_review"
    assert body["asset_mode"] == "parametric"
    assert body["fallback_reason"] == "glb_pending_review"
    assert body["model_url"].startswith("/uploads/models/")
    stored_name = body["model_url"].rsplit("/", 1)[-1]
    assert stored_name != "supplier sofa.glb"
    assert (upload_dir / "models" / stored_name).read_bytes() == _glb_bytes()

    public_pending = client.get("/api/products")
    assert public_pending.status_code == 200
    pending_product = public_pending.json()["products"][0]
    assert pending_product["model_url"] is None
    assert pending_product["approved_model_url"] is None

    approved = client.post(
        "/api/products/1/model-review",
        json={"decision": "approve", "note": "授权与尺寸已核验"},
    )
    assert approved.status_code == 200
    assert approved.json()["model_status"] == "ready"
    assert approved.json()["asset_mode"] == "approved_glb"
    assert approved.json()["fallback_reason"] is None
    assert approved.json()["model_reviewed_by"] == "user:999"
    assert approved.json()["model_reviewed_at"] is not None

    public_approved = client.get("/api/products")
    assert public_approved.status_code == 200
    approved_product = public_approved.json()["products"][0]
    assert approved_product["model_url"] == body["model_url"]
    assert approved_product["approved_model_url"] == body["model_url"]


@pytest.mark.integration
def test_upload_product_model_requires_license_and_source(product_api):
    client, upload_dir = product_api
    assert client.patch(
        "/api/products/1",
        json={"model_license": "", "model_source": ""},
    ).status_code == 200

    response = client.post(
        "/api/products/1/model",
        files={"file": ("sofa.glb", _glb_bytes(), "model/gltf-binary")},
    )

    assert response.status_code == 422
    assert not (upload_dir / "models").exists()


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
    assert body["eligibility"]["eligible"] is False
    assert "verification_required" in body["eligibility"]["reason_codes"]

    verified = client.patch(
        f"/api/products/{body['id']}",
        json={"verification_status": "verified", "verified_by": "spoofed-user"},
    )

    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"
    assert verified.json()["verified_by"] == "user:999"
    assert verified.json()["verified_at"] is not None
    assert verified.json()["record_version"] == 2


@pytest.mark.integration
def test_product_api_rejects_invalid_lifecycle_ranges(product_api):
    client, _ = product_api

    response = client.post(
        "/api/products",
        json={
            "sku": "TABLE-BAD-001",
            "name": "错误交期餐桌",
            "category": "餐桌",
            "room": "餐厅",
            "style": "现代简约",
            "price": 3200,
            "price_max": 3000,
            "lead_time_days_min": 8,
            "lead_time_days_max": 3,
        },
    )

    assert response.status_code == 422


@pytest.mark.integration
def test_quote_rule_cost_factors_round_trip_and_increment_version(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products/quote-rules",
        json={
            "project_name": "定制衣柜",
            "category": "柜类定制",
            "pricing_unit": "㎡",
            "material_grade": "E0 颗粒板",
            "unit_price": 680,
            "region_codes": ["cn-sh", "CN-SH"],
            "waste_rate_bps": 500,
            "minimum_quantity": 3,
            "installation_fee": 300,
            "shipping_fee": 200,
            "tax_rate_bps": 600,
            "data_version": "custom-price-2026-09",
        },
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]

    updated = client.patch(
        f"/api/products/quote-rules/{rule_id}",
        json={"installation_fee": 360},
    )
    assert updated.status_code == 200

    rules = client.get("/api/products/quote-rules").json()["rules"]
    rule = next(item for item in rules if item["id"] == rule_id)
    assert rule["region_codes"] == ["CN-SH"]
    assert rule["waste_rate_bps"] == 500
    assert rule["installation_fee"] == 360
    assert rule["data_version"] == "custom-price-2026-09"
    assert rule["record_version"] == 2
