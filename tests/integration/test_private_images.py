"""原图鉴权与旧静态地址隔离；仅使用临时 SQLite 和文件。"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy import select
from PIL import Image

from app.api.routes import upload
from app.core.config import settings
from app.db.database import get_db
from app.db.models import (
    AnonymousSession,
    AnonymousSessionImage,
    AnonymousSessionTask,
    UploadedImage,
)
from app.services.private_image_service import ProtectedUploadFiles
from tests.integration.test_spatial_api import context as spatial_context  # noqa: F401


@pytest.fixture
def private_context(spatial_context, tmp_path, monkeypatch):  # noqa: F811
    _, factory, _, headers, stranger = spatial_context
    root = tmp_path / "uploads"
    root.mkdir()
    (root / "private.png").write_bytes(b"private-image")
    (root / "public.png").write_bytes(b"public-product")
    monkeypatch.setattr(settings, "upload_dir", str(root))
    with factory() as db:
        bound = UploadedImage(
            task_id=1, file_url="/uploads/private.png", file_name="住宅.png"
        )
        loose = UploadedImage(file_url="/uploads/loose.png", file_name="独立.png")
        db.add_all([bound, loose])
        db.flush()
        db.add_all(
            [
                AnonymousSessionImage(
                    session_id=headers["X-Session-Id"], image_id=item.id
                )
                for item in (bound, loose)
            ]
        )
        db.commit()
        ids = bound.id, loose.id
    (root / "loose.png").write_bytes(b"loose-private")
    app = FastAPI()
    app.include_router(upload.router, prefix="/api/upload")

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    app.mount(
        "/uploads", ProtectedUploadFiles(directory=str(root), session_factory=factory)
    )
    with TestClient(app) as client:
        yield client, factory, headers, stranger, ids, root


def test_content_owner_only_and_public_products_preserved(private_context):
    client, _, headers, stranger, ids, _ = private_context
    for identifier in ids:
        url = f"/api/upload/images/{identifier}/content"
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert client.get(url, headers={"X-Session-Id": stranger}).status_code == 404
        assert client.get(url).status_code == 422
    assert client.get("/uploads/public.png").content == b"public-product"
    for path in (
        "/uploads/private.png",
        "/uploads/%70rivate.png",
        "/uploads/a/../private.png",
        "/uploads/loose.png",
    ):
        assert client.get(path).status_code == 404


def test_task_revocation_wins_over_old_image_ownership(private_context):
    client, factory, headers, _, ids, _ = private_context
    with factory() as db:
        db.execute(delete(AnonymousSessionTask))
        db.commit()
    assert (
        client.get(f"/api/upload/images/{ids[0]}/content", headers=headers).status_code
        == 404
    )
    assert (
        client.get(f"/api/upload/images/{ids[1]}/content", headers=headers).status_code
        == 200
    )


def test_expired_session_and_path_escape_fail_closed(private_context, tmp_path):
    client, factory, headers, _, ids, root = private_context
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"secret")
    with factory() as db:
        db.get(UploadedImage, ids[0]).file_url = "/uploads/../secret.png"
        db.commit()
    assert (
        client.get(f"/api/upload/images/{ids[0]}/content", headers=headers).status_code
        == 404
    )
    with factory() as db:
        db.get(AnonymousSession, headers["X-Session-Id"]).expires_at = datetime.now(
            timezone.utc
        ) - timedelta(days=1)
        db.commit()
    assert (
        client.get(f"/api/upload/images/{ids[1]}/content", headers=headers).status_code
        == 404
    )


def test_static_database_failure_never_falls_back_to_file(private_context, monkeypatch):
    from app.services import private_image_service

    client, _, _, _, _, _ = private_context

    def unavailable(*args, **kwargs):
        raise RuntimeError("database credentials should not leak")

    monkeypatch.setattr(private_image_service, "is_private_upload", unavailable)
    result = client.get("/uploads/private.png")
    assert result.status_code == 503
    assert "credentials" not in result.text


def test_hardlink_alias_does_not_expose_registered_image(private_context):
    client, _, _, _, _, root = private_context
    os.link(root / "private.png", root / "alias.png")
    assert client.get("/uploads/alias.png").status_code == 404


def test_symlink_escape_is_not_readable(private_context, tmp_path):
    client, factory, headers, _, ids, root = private_context
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside-private")
    try:
        (root / "escape.png").symlink_to(outside)
    except OSError:
        pytest.skip("当前 Windows 账户不允许创建符号链接")
    with factory() as db:
        db.get(UploadedImage, ids[0]).file_url = "/uploads/escape.png"
        db.commit()
    assert (
        client.get(f"/api/upload/images/{ids[0]}/content", headers=headers).status_code
        == 404
    )
    assert client.get("/uploads/escape.png").status_code in (404, 503)


def test_upload_is_registered_and_private_before_model_and_replay_repairs_ownership(
    private_context, monkeypatch
):
    from app.services import llm_service

    client, factory, headers, _, _, _ = private_context
    data = BytesIO()
    Image.new("RGB", (20, 20), "white").save(data, format="PNG")
    calls = []

    def analyze(*args):
        from app.services.private_image_service import is_private_upload

        with factory() as db:
            item = db.scalar(select(UploadedImage).order_by(UploadedImage.id.desc()))
            assert item.file_name == "原图.png"
            assert item.file_url
            assert (
                db.get(AnonymousSessionImage, (headers["X-Session-Id"], item.id))
                is not None
            )
            assert is_private_upload(
                settings.upload_dir, item.file_url.removeprefix("/uploads/"), factory
            )
        calls.append(True)
        return None

    monkeypatch.setattr(llm_service, "analyze_room_model", analyze)
    request_headers = {**headers, "Idempotency-Key": "private-upload-1234"}
    response = client.post(
        "/api/upload/image",
        headers=request_headers,
        files={"file": ("原图.png", data.getvalue(), "image/png")},
    )
    assert response.status_code == 200, response.text
    image_id = response.json()["image_id"]
    with factory() as db:
        db.execute(
            delete(AnonymousSessionImage).where(
                AnonymousSessionImage.image_id == image_id
            )
        )
        db.commit()
    replay = client.post(
        "/api/upload/image",
        headers=request_headers,
        files={"file": ("原图.png", data.getvalue(), "image/png")},
    )
    assert replay.json() == response.json()
    assert calls == [True]
    assert (
        client.get(
            f"/api/upload/images/{image_id}/content", headers=headers
        ).status_code
        == 200
    )


def test_pending_upload_replay_is_not_reported_as_completed(private_context):
    from fastapi import HTTPException

    _, factory, _, _, ids, _ = private_context
    with factory() as db:
        image = db.get(UploadedImage, ids[0])
        assert image.analysis_json is None
        with pytest.raises(HTTPException) as result:
            upload._upload_response(image)
        assert result.value.status_code == 409
