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

from app.api.routes import products
from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import Product


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
        db.commit()

    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))
    app = FastAPI()
    app.include_router(products.router, prefix="/api/products")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
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
