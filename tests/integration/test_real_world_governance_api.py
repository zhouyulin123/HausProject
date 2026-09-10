from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import DesignTask, UploadedImage, User
from app.main import app
from app.services import auth_service


@pytest.fixture
def governance_api(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    (upload_root / "case.png").write_bytes(b"private-case-image")
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    with factory() as db:
        users = [
            User(id=8101, phone="13800008101", role="customer", phone_verified=True),
            User(id=8102, phone="13800008102", role="factory", phone_verified=True),
            User(id=8103, phone="13800008103", role="admin", phone_verified=True),
        ]
        task = DesignTask(
            id=8201,
            status="confirmed",
            raw_user_input="已脱敏需求",
            confirmed_requirement_json={"space_type": "客厅"},
            space_type="客厅",
        )
        content = b"private-case-image"
        image = UploadedImage(
            id=8301,
            task_id=task.id,
            file_url="/uploads/case.png",
            content_digest="sha256:"
            + __import__("hashlib").sha256(content).hexdigest(),
            analysis_json={"findings": ["已脱敏空间事实"]},
        )
        db.add_all([*users, task, image])
        db.commit()
        tokens = {user.role: auth_service.issue_token(user) for user in users}

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), tokens
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _authenticate(client: TestClient, token: str) -> None:
    client.cookies.set(settings.auth_cookie_name, token)


def test_governance_endpoints_require_admin_for_customer_and_factory(governance_api):
    client, tokens = governance_api
    url = "/api/admin/quality/real-world-cases"

    assert client.get(url).status_code == 401
    for role in ("customer", "factory"):
        _authenticate(client, tokens[role])
        assert client.get(url).status_code == 403


def test_admin_can_preview_import_and_list_only_anonymous_governance(governance_api):
    client, tokens = governance_api
    _authenticate(client, tokens["admin"])
    payload = {
        "client_import_id": "api-import-001",
        "task_id": 8201,
        "uploaded_image_id": 8301,
    }

    preview = client.post(
        "/api/admin/quality/real-world-case-imports/preview",
        json=payload,
        headers={"X-Request-ID": "api-preview-001"},
    )
    assert preview.status_code == 200
    assert preview.json() == {
        "task_input_ready": True,
        "asset_available": True,
        "duplicate_asset": False,
    }

    created = client.post(
        "/api/admin/quality/real-world-case-imports",
        json=payload,
        headers={"X-Request-ID": "api-import-001"},
    )
    assert created.status_code == 201
    assert created.json()["created"] is True
    case_ref = created.json()["case"]["case_ref"]

    duplicate = client.post(
        "/api/admin/quality/real-world-case-imports",
        json=payload,
        headers={"X-Request-ID": "api-import-replay"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False
    assert duplicate.json()["case"]["case_ref"] == case_ref

    listed = client.get("/api/admin/quality/real-world-cases")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["case_ref"] == case_ref
    serialized = json.dumps(body, ensure_ascii=False)
    for private_value in (
        "private-case-image",
        "已脱敏需求",
        "已脱敏空间事实",
        "/uploads/case.png",
        "8201",
        "8301",
    ):
        assert private_value not in serialized


def test_import_contract_rejects_client_paths_digests_task_input_and_actor(governance_api):
    client, tokens = governance_api
    _authenticate(client, tokens["admin"])
    base = {
        "client_import_id": "api-import-strict",
        "task_id": 8201,
        "uploaded_image_id": 8301,
    }
    for forbidden in (
        {"asset_path": "C:/private/room.png"},
        {"asset_digest": "sha256:" + "a" * 64},
        {"task_input": {"raw_user_input": "伪造输入"}},
        {"actor_user_id": 9999},
    ):
        response = client.post(
            "/api/admin/quality/real-world-case-imports/preview",
            json=base | forbidden,
        )
        assert response.status_code == 422


def test_blind_case_mutation_response_stays_anonymous(governance_api):
    client, tokens = governance_api
    _authenticate(client, tokens["admin"])
    created = client.post(
        "/api/admin/quality/real-world-case-imports",
        json={
            "client_import_id": "api-import-blind",
            "task_id": 8201,
            "uploaded_image_id": 8301,
        },
    ).json()["case"]

    updated = client.patch(
        f"/api/admin/quality/real-world-cases/{created['case_ref']}",
        json={"expected_version": created["record_version"], "split": "blind"},
        headers={"X-Request-ID": "api-blind-001"},
    )
    assert updated.status_code == 200
    assert updated.json()["split"] == "blind"
    assert "task_input" not in updated.json()
    assert "asset_digest" not in updated.json()
