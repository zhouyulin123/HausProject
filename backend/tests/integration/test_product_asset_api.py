from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.api.routes import products
from app.db.database import Base, get_db
from app.db.models import Product, ProductAsset, User


@pytest.fixture
def asset_api():
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
                id=1,
                sku="CHAIR-ASSET-001",
                name="资产审核椅",
                category="椅子",
                room="客厅",
                style="现代简约",
                price=1800,
                image_url="/uploads/products/legacy-unreviewed.png",
                model_width_mm=720,
                model_height_mm=810,
                model_depth_mm=760,
            )
        )
        db.add_all(
            [
                User(id=101, phone="13800000101", role="factory", phone_verified=True),
                User(id=102, phone="13800000102", role="admin", phone_verified=True),
                User(id=103, phone="13800000103", role="customer", phone_verified=True),
            ]
        )
        db.commit()

    current_user_id = {"value": 101}
    app = FastAPI()
    app.include_router(products.router, prefix="/api/products")

    def override_db():
        with factory() as db:
            yield db

    def override_current_user():
        with factory() as db:
            return db.get(User, current_user_id["value"])

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user
    try:
        with TestClient(app) as client:
            yield client, factory, current_user_id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _asset_payload(kind: str, url: str) -> dict[str, str]:
    return {
        "kind": kind,
        "url": url,
        "source": "supplier:CHAIR-ASSET-001",
        "authorization": "供应商书面商用授权 2026",
    }


@pytest.mark.integration
def test_public_products_expose_only_approved_assets(asset_api):
    client, _, current_user_id = asset_api

    initial = client.get("/api/products").json()["products"][0]
    assert initial["image_url"] is None
    assert initial["assets"] == []

    pending = client.post(
        "/api/products/1/assets",
        json=_asset_payload("image", "/uploads/products/reviewed-chair.png"),
    )
    assert pending.status_code == 201
    assert pending.json()["review_status"] == "pending_review"
    assert pending.json()["reviewed_by"] is None
    asset_id = pending.json()["id"]

    public_pending = client.get("/api/products").json()["products"][0]
    assert public_pending["image_url"] is None
    assert public_pending["assets"] == []

    denied = client.post(
        f"/api/products/1/assets/{asset_id}/review",
        json={"decision": "approve", "note": "来源和授权已核验"},
    )
    assert denied.status_code == 403

    current_user_id["value"] = 102
    approved = client.post(
        f"/api/products/1/assets/{asset_id}/review",
        json={"decision": "approve", "note": "来源和授权已核验"},
    )
    assert approved.status_code == 200
    assert approved.json()["review_status"] == "approved"
    assert approved.json()["reviewed_by"] == "user:102"
    assert approved.json()["reviewed_at"] is not None

    public = client.get("/api/products").json()["products"][0]
    assert public["image_url"] == "/uploads/products/reviewed-chair.png"
    assert public["assets"] == [
        {
            "id": asset_id,
            "kind": "image",
            "url": "/uploads/products/reviewed-chair.png",
            "source": "supplier:CHAIR-ASSET-001",
            "authorization": "供应商书面商用授权 2026",
            "reviewed_at": approved.json()["reviewed_at"],
        }
    ]
    assert "reviewed_by" not in public["assets"][0]
    assert "review_note" not in public["assets"][0]


@pytest.mark.integration
def test_asset_write_and_review_are_role_protected_and_fail_closed(asset_api):
    client, factory, current_user_id = asset_api
    current_user_id["value"] = 103
    assert client.post(
        "/api/products/1/assets",
        json=_asset_payload("cad", "/uploads/products/chair.step"),
    ).status_code == 403

    current_user_id["value"] = 101
    assert client.post(
        "/api/products/1/assets",
        json={
            **_asset_payload("cad", "/uploads/products/chair.step"),
            "authorization": "",
        },
    ).status_code == 422
    assert client.post(
        "/api/products/1/assets",
        json=_asset_payload("glb", "/uploads/models/unvalidated.glb"),
    ).status_code == 409

    cad = client.post(
        "/api/products/1/assets",
        json=_asset_payload("cad", "/uploads/products/chair.step"),
    )
    material = client.post(
        "/api/products/1/assets",
        json=_asset_payload("material", "/uploads/products/chair-material.pdf"),
    )
    assert cad.status_code == material.status_code == 201

    current_user_id["value"] = 102
    rejected = client.post(
        f"/api/products/1/assets/{cad.json()['id']}/review",
        json={"decision": "reject", "note": "CAD 版本不匹配"},
    )
    assert rejected.status_code == 200
    protected = client.get("/api/products/1/assets")
    assert protected.status_code == 200
    assert [item["review_status"] for item in protected.json()["assets"]] == [
        "rejected",
        "pending_review",
    ]
    assert client.get("/api/products").json()["products"][0]["assets"] == []

    with factory() as db:
        assert db.query(ProductAsset).count() == 2


@pytest.mark.integration
def test_approving_new_asset_supersedes_previous_approved_kind(asset_api):
    client, _, current_user_id = asset_api
    first = client.post(
        "/api/products/1/assets",
        json=_asset_payload("image", "/uploads/products/chair-v1.png"),
    ).json()
    second = client.post(
        "/api/products/1/assets",
        json=_asset_payload("image", "/uploads/products/chair-v2.png"),
    ).json()
    current_user_id["value"] = 102
    assert client.post(
        f"/api/products/1/assets/{first['id']}/review",
        json={"decision": "approve"},
    ).status_code == 200
    assert client.post(
        f"/api/products/1/assets/{second['id']}/review",
        json={"decision": "approve"},
    ).status_code == 200

    records = client.get("/api/products/1/assets").json()["assets"]
    assert [item["review_status"] for item in records] == [
        "superseded",
        "approved",
    ]
    public = client.get("/api/products").json()["products"][0]
    assert [item["url"] for item in public["assets"]] == [
        "/uploads/products/chair-v2.png"
    ]
    assert public["image_url"] == "/uploads/products/chair-v2.png"


@pytest.mark.integration
def test_public_glb_compatibility_fields_match_the_approved_asset(asset_api):
    client, factory, _ = asset_api
    with factory() as db:
        product = db.get(Product, 1)
        product.model_url = "/uploads/models/pending-v2.glb"
        product.model_status = "pending_review"
        product.model_source = "supplier:pending-v2"
        product.model_license = "待复核授权"
        db.add(
            ProductAsset(
                product_id=product.id,
                kind="glb",
                url="/uploads/models/approved-v1.glb",
                source="supplier:approved-v1",
                authorization="已核验商用授权",
                review_status="approved",
                reviewed_at=product.created_at,
                reviewed_by="user:102",
                created_by="user:101",
            )
        )
        db.commit()

    public = client.get("/api/products").json()["products"][0]

    assert public["model_url"] == "/uploads/models/approved-v1.glb"
    assert public["model_source"] == "supplier:approved-v1"
    assert public["model_license"] == "已核验商用授权"
    assert public["model_reviewed_by"] == "user:102"
