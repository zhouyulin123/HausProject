import hashlib
import json
from pathlib import Path
import shutil
import struct
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
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
        db.add_all(
            [
                User(
                    id=998,
                    phone="13800009998",
                    nickname="13800009998",
                    role="factory",
                    phone_verified=True,
                ),
                User(
                    id=997,
                    phone="13800009997",
                    nickname="13800009997",
                    role="customer",
                    phone_verified=True,
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))
    app = FastAPI()
    app.include_router(products.router, prefix="/api/products")

    def override_db():
        with factory() as db:
            yield db

    def override_current_user(request: Request):
        user_ids = {"admin": 999, "factory": 998, "customer": 997}
        user_id = user_ids.get(request.headers.get("X-Test-Role", "admin"), 999)
        with factory() as db:
            return db.get(User, user_id)

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
        json={"record_version": 1, "model_license": "", "model_source": ""},
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
            "data_origin": "merchant",
            "source_name": "供应商目录",
            "source_product_id": "TABLE-001",
            "source_retrieved_at": "2026-09-01T00:00:00Z",
            "price_observed_at": "2026-09-01T00:00:00Z",
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

    verified = client.post(
        f"/api/products/{body['id']}/commercial-review",
        headers={"Idempotency-Key": "table-001-approve"},
        json={
            "decision": "approve",
            "expected_record_version": body["record_version"],
        },
    )

    assert verified.status_code == 200
    assert verified.json()["resulting_status"] == "verified"
    assert verified.json()["resulting_record_version"] == 2
    managed = client.get("/api/products/admin/catalog").json()["products"]
    verified_product = next(item for item in managed if item["id"] == body["id"])
    assert verified_product["verified_by"] == "user:999"
    assert verified_product["verified_at"] is not None
    unchanged = client.patch(
        f"/api/products/{body['id']}",
        json={
            "record_version": verified_product["record_version"],
            "price": verified_product["price"],
            "region_codes": verified_product["region_codes"],
            "price_valid_from": verified_product["price_valid_from"],
            "price_valid_to": verified_product["price_valid_to"],
        },
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["record_version"] == 2
    assert unchanged.json()["verified_at"] == verified_product["verified_at"]


def _commercial_draft_payload(*, sku: str) -> dict:
    return {
        "sku": sku,
        "name": "待商业核验餐桌",
        "category": "餐桌",
        "room": "餐厅",
        "style": "现代简约",
        "price": 3200,
        "model_width_mm": 1600,
        "model_depth_mm": 850,
        "model_height_mm": 750,
        "data_origin": "merchant_draft",
        "source_name": "供应商目录",
        "source_product_id": sku,
        "source_retrieved_at": "2026-09-01T00:00:00Z",
        "price_observed_at": "2026-09-01T00:00:00Z",
        "availability_status": "in_stock",
        "stock_quantity": 8,
        "region_codes": ["CN-SH"],
        "price_valid_from": "2026-01-01T00:00:00Z",
        "price_valid_to": "2099-12-31T23:59:59Z",
        "data_version": "supplier-2026-q3",
    }


@pytest.mark.integration
def test_factory_cannot_create_or_patch_commercial_verification(product_api):
    client, _ = product_api
    factory_headers = {"X-Test-Role": "factory"}

    direct_verified = client.post(
        "/api/products",
        headers=factory_headers,
        json={
            **_commercial_draft_payload(sku="NO-DIRECT-VERIFY"),
            "verification_status": "verified",
        },
    )
    assert direct_verified.status_code == 422
    legacy_origin = client.post(
        "/api/products",
        headers=factory_headers,
        json={
            **_commercial_draft_payload(sku="NO-LEGACY-ORIGIN"),
            "data_origin": "verified",
        },
    )
    assert legacy_origin.status_code == 422

    created = client.post(
        "/api/products",
        headers=factory_headers,
        json=_commercial_draft_payload(sku="NO-PATCH-VERIFY"),
    ).json()
    direct_patch = client.patch(
        f"/api/products/{created['id']}",
        headers=factory_headers,
        json={
            "record_version": created["record_version"],
            "verification_status": "verified",
        },
    )
    assert direct_patch.status_code == 422


@pytest.mark.integration
def test_product_creation_starts_commercial_audit_trail(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        headers={"X-Test-Role": "factory", "X-Request-ID": "req-create-001"},
        json=_commercial_draft_payload(sku="CREATE-AUDIT-001"),
    ).json()

    audit = client.get(
        f"/api/products/{created['id']}/audit-events",
        headers={"X-Test-Role": "factory"},
    ).json()
    assert audit["count"] == 1
    assert audit["items"][0]["event_type"] == "commercial_created"
    assert audit["items"][0]["actor"] == "user:998"
    assert audit["items"][0]["request_id"] == "req-create-001"
    assert audit["items"][0]["resulting_status"] == "draft"
    assert audit["items"][0]["resulting_record_version"] == 1


@pytest.mark.integration
def test_admin_review_is_cas_idempotent_and_factory_cannot_approve(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        headers={"X-Test-Role": "factory"},
        json=_commercial_draft_payload(sku="REVIEW-001"),
    ).json()
    request = {
        "decision": "approve",
        "expected_record_version": created["record_version"],
        "note": "来源、库存和有效期已复核",
    }
    headers = {"Idempotency-Key": "review-001", "X-Request-ID": "req-review-001"}

    forbidden = client.post(
        f"/api/products/{created['id']}/commercial-review",
        headers={**headers, "X-Test-Role": "factory"},
        json=request,
    )
    assert forbidden.status_code == 403

    stale = client.post(
        f"/api/products/{created['id']}/commercial-review",
        headers={"Idempotency-Key": "review-001-stale"},
        json={**request, "expected_record_version": 99},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "record_version_conflict",
        "message": "商品版本冲突：期望 99，当前 1",
        "expected_record_version": 99,
        "current_record_version": 1,
    }

    approved = client.post(
        f"/api/products/{created['id']}/commercial-review",
        headers=headers,
        json=request,
    )
    assert approved.status_code == 200
    assert approved.json()["resulting_status"] == "verified"
    assert approved.json()["resulting_record_version"] == 2

    replay = client.post(
        f"/api/products/{created['id']}/commercial-review",
        headers=headers,
        json=request,
    )
    assert replay.status_code == 200
    assert replay.json() == approved.json()

    conflict = client.post(
        f"/api/products/{created['id']}/commercial-review",
        headers=headers,
        json={**request, "note": "不同审核内容"},
    )
    assert conflict.status_code == 409


@pytest.mark.integration
def test_commercial_patch_downgrades_and_appends_redacted_audit(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        headers={"X-Test-Role": "factory"},
        json=_commercial_draft_payload(sku="AUDIT-001"),
    ).json()
    approved = client.post(
        f"/api/products/{created['id']}/commercial-review",
        headers={"Idempotency-Key": "audit-approve-001"},
        json={
            "decision": "approve",
            "expected_record_version": created["record_version"],
            "note": "批准",
        },
    ).json()

    changed = client.patch(
        f"/api/products/{created['id']}",
        headers={"X-Test-Role": "factory", "X-Request-ID": "req-patch-001"},
        json={
            "record_version": approved["resulting_record_version"],
            "price": 3500,
            "source_metadata": {
                "api_key": "never-store-this-secret",
                "local_path": "D:\\private\\catalog.xlsx",
            },
        },
    )
    assert changed.status_code == 200
    assert changed.json()["verification_status"] == "draft"
    assert changed.json()["verified_at"] is None
    assert changed.json()["verified_by"] is None

    audit = client.get(
        f"/api/products/{created['id']}/audit-events",
        headers={"X-Test-Role": "factory"},
    )
    assert audit.status_code == 200
    patch_event = next(
        item for item in audit.json()["items"] if item["event_type"] == "commercial_patch"
    )
    assert patch_event["actor"] == "user:998"
    assert patch_event["request_id"] == "req-patch-001"
    assert set(patch_event["changed_fields"]) >= {
        "price",
        "source_metadata",
        "verification_status",
        "verified_at",
        "verified_by",
    }
    serialized = json.dumps(patch_event, ensure_ascii=False)
    assert "never-store-this-secret" not in serialized
    assert "private\\catalog.xlsx" not in serialized

    customer = client.get(
        f"/api/products/{created['id']}/audit-events",
        headers={"X-Test-Role": "customer"},
    )
    assert customer.status_code == 403


@pytest.mark.integration
def test_review_fails_closed_on_missing_evidence_without_mutation(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        headers={"X-Test-Role": "factory"},
        json={
            "sku": "REVIEW-INCOMPLETE-001",
            "name": "证据不完整商品",
            "category": "餐桌",
            "room": "餐厅",
            "style": "现代简约",
            "price": 3200,
        },
    ).json()

    rejected = client.post(
        f"/api/products/{created['id']}/commercial-review",
        headers={"Idempotency-Key": "review-incomplete-001"},
        json={
            "decision": "approve",
            "expected_record_version": created["record_version"],
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "commercial_evidence_incomplete"
    assert rejected.json()["detail"]["reason_codes"]

    managed = client.get("/api/products/admin/catalog?include_inactive=true").json()
    current = next(item for item in managed["products"] if item["id"] == created["id"])
    assert current["record_version"] == created["record_version"]
    assert current["verification_status"] == "draft"
    events = client.get(
        f"/api/products/{created['id']}/audit-events"
    ).json()["items"]
    assert [event["event_type"] for event in events] == ["commercial_created"]


@pytest.mark.integration
def test_rejection_note_is_audited_only_as_digest(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        json=_commercial_draft_payload(sku="REJECT-AUDIT-001"),
    ).json()
    secret_note = "供应商合同冲突，不可公开原文"

    rejected = client.post(
        f"/api/products/{created['id']}/commercial-review",
        headers={"Idempotency-Key": "reject-audit-001"},
        json={
            "decision": "reject",
            "expected_record_version": created["record_version"],
            "note": secret_note,
        },
    )
    assert rejected.status_code == 200
    body = rejected.json()
    assert body["changes"]["review_note"]["after"] == {
        "present": True,
        "char_count": len(secret_note),
        "sha256": hashlib.sha256(secret_note.encode("utf-8")).hexdigest(),
    }
    assert secret_note not in json.dumps(body, ensure_ascii=False)


@pytest.mark.integration
def test_deactivate_increments_version_and_appends_audit(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        headers={"X-Request-ID": "req-create-deactivate"},
        json=_commercial_draft_payload(sku="DEACTIVATE-AUDIT-001"),
    ).json()

    stale = client.delete(
        f"/api/products/{created['id']}?expected_record_version=99",
        headers={"Idempotency-Key": "deactivate-audit-stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "record_version_conflict"
    assert stale.json()["detail"]["expected_record_version"] == 99
    assert stale.json()["detail"]["current_record_version"] == 1

    url = f"/api/products/{created['id']}?expected_record_version=1"
    headers = {
        "Idempotency-Key": "deactivate-audit-001",
        "X-Request-ID": "req-deactivate-001",
    }
    response = client.delete(
        url,
        headers=headers,
    )
    assert response.status_code == 200
    replay = client.delete(url, headers=headers)
    assert replay.status_code == 200
    assert replay.json() == response.json()
    reused = client.delete(
        f"/api/products/{created['id']}?expected_record_version=2",
        headers=headers,
    )
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "idempotency_conflict"
    audit = client.get(
        f"/api/products/{created['id']}/audit-events"
    ).json()["items"]
    assert len(audit) == 2
    assert audit[0]["event_type"] == "commercial_deactivate"
    assert audit[0]["request_id"] == "req-deactivate-001"
    assert audit[0]["resulting_record_version"] == 2
    assert audit[0]["changes"]["is_active"] == {
        "before": True,
        "after": False,
    }


@pytest.mark.integration
def test_product_verification_rejects_incomplete_commercial_evidence(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        json={
            "sku": "VERIFY-INCOMPLETE-001",
            "name": "商业事实不完整商品",
            "category": "餐桌",
            "room": "餐厅",
            "style": "现代简约",
            "price": 3200,
            "model_width_mm": 1600,
            "model_depth_mm": 850,
            "model_height_mm": 750,
        },
    ).json()

    response = client.post(
        f"/api/products/{created['id']}/commercial-review",
        headers={"Idempotency-Key": "verify-incomplete-001"},
        json={
            "decision": "approve",
            "expected_record_version": created["record_version"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "commercial_evidence_incomplete"
    assert {
        "provenance_unverified",
        "source_name_missing",
        "source_reference_missing",
        "source_retrieved_at_missing",
        "price_observed_at_missing",
        "availability_unknown",
        "price_validity_unknown",
        "region_unknown",
        "data_version_unverified",
    } <= set(response.json()["detail"]["reason_codes"])


@pytest.mark.integration
def test_product_verification_rejects_draft_origin_and_missing_stock(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        json={
            "sku": "VERIFY-DRAFT-001",
            "name": "仍为草稿来源的商品",
            "category": "沙发",
            "room": "客厅",
            "style": "现代简约",
            "price": 4999,
            "data_origin": "merchant_draft",
            "source_name": "供应商目录",
            "source_product_id": "VERIFY-DRAFT-001",
            "source_retrieved_at": "2026-09-01T00:00:00Z",
            "price_observed_at": "2026-09-01T00:00:00Z",
            "availability_status": "in_stock",
            "region_codes": ["CN-SH"],
            "price_valid_from": "2026-09-01T00:00:00Z",
            "price_valid_to": "2026-12-31T23:59:59Z",
            "data_version": "supplier-2026-q3",
        },
    ).json()
    response = client.post(
        f"/api/products/{created['id']}/commercial-review",
        headers={"Idempotency-Key": "verify-draft-001"},
        json={
            "decision": "approve",
            "expected_record_version": created["record_version"],
        },
    )

    assert response.status_code == 422
    assert "out_of_stock" in response.json()["detail"]["reason_codes"]


@pytest.mark.integration
def test_product_management_list_exposes_pending_and_inactive_records(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        json={
            "sku": "MANAGE-DRAFT-001",
            "name": "待核验管理商品",
            "category": "沙发",
            "room": "客厅",
            "style": "现代简约",
            "price": 4200,
            "data_origin": "merchant_draft",
            "source_name": "供应商商品表",
            "source_url": "https://supplier.example/products/sofa-001",
            "source_product_id": "SOFA-001",
            "source_retrieved_at": "2026-09-08T08:00:00Z",
            "price_observed_at": "2026-09-08T08:00:00Z",
            "price_note": "待人工核验",
        },
    )
    assert created.status_code == 200
    product_id = created.json()["id"]
    assert client.delete(
        f"/api/products/{product_id}?expected_record_version=1",
        headers={"Idempotency-Key": "manage-draft-deactivate"},
    ).status_code == 200

    managed = client.get("/api/products/admin/catalog")

    assert managed.status_code == 200
    assert all(item["id"] != product_id for item in managed.json()["products"])
    managed = client.get("/api/products/admin/catalog?include_inactive=true")
    record = next(
        item for item in managed.json()["products"] if item["id"] == product_id
    )
    assert record["verification_status"] == "draft"
    assert record["source_url"] == "https://supplier.example/products/sofa-001"
    assert record["eligibility"]["reason_codes"]


@pytest.mark.integration
def test_product_source_fields_are_validated_and_reset_verification(product_api):
    client, _ = product_api
    created = client.post(
        "/api/products",
        json={
            "sku": "SOURCE-001",
            "name": "来源事实商品",
            "category": "餐桌",
            "room": "餐厅",
            "style": "原木风",
            "price": 3200,
            "model_width_mm": 1600,
            "model_depth_mm": 850,
            "model_height_mm": 750,
            "data_origin": "merchant",
            "source_name": "供应商目录",
            "source_url": "https://supplier.example/products/table-001",
            "source_product_id": "TABLE-001",
            "source_retrieved_at": "2026-09-08T08:00:00+08:00",
            "price_observed_at": "2026-09-08T08:00:00+08:00",
            "price_note": "含税报价，待确认库存",
            "availability_status": "in_stock",
            "stock_quantity": 8,
            "region_codes": ["CN-SH"],
            "price_valid_from": "2026-09-01T00:00:00Z",
            "price_valid_to": "2099-12-31T23:59:59Z",
            "data_version": "supplier-2026-q3",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["source_product_id"] == "TABLE-001"
    assert body["verification_status"] == "draft"
    approval_response = client.post(
        f"/api/products/{body['id']}/commercial-review",
        headers={"Idempotency-Key": "source-001-approve-1"},
        json={
            "decision": "approve",
            "expected_record_version": body["record_version"],
        },
    )
    assert approval_response.status_code == 200, approval_response.json()
    approved = approval_response.json()

    changed = client.patch(
        f"/api/products/{body['id']}",
        json={
            "record_version": approved["resulting_record_version"],
            "source_url": "https://supplier.example/products/table-002",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["verification_status"] == "draft"
    reapproved = client.post(
        f"/api/products/{body['id']}/commercial-review",
        headers={"Idempotency-Key": "source-001-approve-2"},
        json={
            "decision": "approve",
            "expected_record_version": changed.json()["record_version"],
        },
    ).json()
    downgraded = client.patch(
        f"/api/products/{body['id']}",
        json={"record_version": reapproved["resulting_record_version"], "price": 3300},
    )
    assert downgraded.status_code == 200
    assert downgraded.json()["verification_status"] == "draft"
    assert downgraded.json()["verified_at"] is None
    assert downgraded.json()["verified_by"] is None
    stale = client.patch(
        f"/api/products/{body['id']}",
        json={"record_version": body["record_version"], "price": 3300},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_record_version"] == 5

    rejected = client.post(
        f"/api/products/{body['id']}/commercial-review",
        headers={"Idempotency-Key": "source-001-reject"},
        json={
            "decision": "reject",
            "expected_record_version": downgraded.json()["record_version"],
            "note": "供应商价格证据不一致",
        },
    )
    assert rejected.status_code == 200
    assert rejected.json()["resulting_status"] == "rejected"

    cleared_url = client.patch(
        f"/api/products/{body['id']}",
        json={
            "record_version": rejected.json()["resulting_record_version"],
            "source_url": "",
            "source_product_id": "TABLE-OFFLINE-001",
        },
    )
    assert cleared_url.status_code == 200
    assert cleared_url.json()["source_url"] is None
    assert cleared_url.json()["source_product_id"] == "TABLE-OFFLINE-001"
    assert cleared_url.json()["verification_status"] == "draft"

    legacy_origin = client.patch(
        f"/api/products/{body['id']}",
        json={
            "record_version": cleared_url.json()["record_version"],
            "data_origin": "verified",
        },
    )
    assert legacy_origin.status_code == 422

    assert (
        client.post(
            "/api/products",
            json={
                "sku": "SOURCE-BAD-URL",
                "name": "非法来源地址",
                "category": "餐桌",
                "room": "餐厅",
                "style": "原木风",
                "price": 3200,
                "source_url": "not-a-url",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/products",
            json={
                "sku": "SOURCE-NAIVE-TIME",
                "name": "无时区来源时间",
                "category": "餐桌",
                "room": "餐厅",
                "style": "原木风",
                "price": 3200,
                "source_retrieved_at": "2026-09-08T08:00:00",
            },
        ).status_code
        == 422
    )


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
