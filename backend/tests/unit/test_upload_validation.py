import pytest

from app.services.upload_validation import (
    UploadValidationError,
    validate_image_upload,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"test-image"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("content", "content_type", "filename", "expected_format"),
    [
        (PNG_BYTES, "image/png", "room.png", "png"),
        (JPEG_BYTES, "image/jpeg", "room.jpg", "jpeg"),
    ],
)
def test_validate_image_upload_accepts_supported_images(
    content: bytes,
    content_type: str,
    filename: str,
    expected_format: str,
):
    result = validate_image_upload(
        content=content,
        content_type=content_type,
        filename=filename,
        max_bytes=1024,
    )

    assert result.image_format == expected_format


@pytest.mark.unit
def test_validate_image_upload_rejects_empty_file():
    with pytest.raises(UploadValidationError, match="不能为空"):
        validate_image_upload(
            content=b"",
            content_type="image/png",
            filename="empty.png",
            max_bytes=1024,
        )


@pytest.mark.unit
def test_validate_image_upload_rejects_oversized_file():
    with pytest.raises(UploadValidationError, match="不能超过"):
        validate_image_upload(
            content=PNG_BYTES,
            content_type="image/png",
            filename="large.png",
            max_bytes=8,
        )


@pytest.mark.unit
def test_validate_image_upload_rejects_unsupported_content_type():
    with pytest.raises(UploadValidationError, match="仅支持"):
        validate_image_upload(
            content=PNG_BYTES,
            content_type="application/octet-stream",
            filename="room.png",
            max_bytes=1024,
        )


@pytest.mark.unit
def test_validate_image_upload_rejects_mismatched_file_signature():
    with pytest.raises(UploadValidationError, match="内容与格式不匹配"):
        validate_image_upload(
            content=b"not-a-real-image",
            content_type="image/png",
            filename="room.png",
            max_bytes=1024,
        )
