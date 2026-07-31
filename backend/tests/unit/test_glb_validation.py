import json
import struct

import pytest

from app.services.glb_validation import (
    GlbValidationError,
    validate_glb_upload,
)


def make_glb(document: dict | None = None) -> bytes:
    payload = json.dumps(
        document or {"asset": {"version": "2.0"}, "scenes": [{"nodes": []}]},
        separators=(",", ":"),
    ).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    chunk = struct.pack("<I4s", len(payload), b"JSON") + payload
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunk)) + chunk


@pytest.mark.unit
def test_validate_glb_upload_accepts_well_formed_glb_2():
    result = validate_glb_upload(
        content=make_glb(),
        content_type="model/gltf-binary",
        filename="sofa.glb",
        max_bytes=1024,
    )

    assert result.version == 2
    assert result.extension == "glb"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("content", "content_type", "filename", "message"),
    [
        (b"", "model/gltf-binary", "empty.glb", "不能为空"),
        (b"not-glb", "model/gltf-binary", "fake.glb", "GLB"),
        (make_glb(), "text/plain", "sofa.glb", "文件类型"),
        (make_glb(), "model/gltf-binary", "sofa.zip", "扩展名"),
    ],
)
def test_validate_glb_upload_rejects_invalid_uploads(
    content: bytes,
    content_type: str,
    filename: str,
    message: str,
):
    with pytest.raises(GlbValidationError, match=message):
        validate_glb_upload(
            content=content,
            content_type=content_type,
            filename=filename,
            max_bytes=1024,
        )


@pytest.mark.unit
def test_validate_glb_upload_rejects_declared_length_mismatch():
    content = bytearray(make_glb())
    struct.pack_into("<I", content, 8, len(content) + 4)

    with pytest.raises(GlbValidationError, match="长度"):
        validate_glb_upload(
            content=bytes(content),
            content_type="application/octet-stream",
            filename="sofa.glb",
            max_bytes=1024,
        )


@pytest.mark.unit
def test_validate_glb_upload_rejects_non_gltf_2_asset():
    with pytest.raises(GlbValidationError, match="2.0"):
        validate_glb_upload(
            content=make_glb({"asset": {"version": "1.0"}}),
            content_type="model/gltf-binary",
            filename="legacy.glb",
            max_bytes=1024,
        )
