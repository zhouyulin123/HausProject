from dataclasses import dataclass
from pathlib import Path


class UploadValidationError(ValueError):
    """用户上传的图片不满足安全或格式要求。"""


@dataclass(frozen=True)
class ValidatedImage:
    image_format: str
    extension: str


_CONTENT_TYPE_TO_FORMAT = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/webp": "webp",
}


def _detect_image_format(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if (
        len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    ):
        return "webp"
    return None


def validate_image_upload(
    *,
    content: bytes,
    content_type: str,
    filename: str,
    max_bytes: int,
) -> ValidatedImage:
    """校验图片大小、MIME 和文件签名，并返回可信的存储扩展名。"""
    if not content:
        raise UploadValidationError("上传图片不能为空")
    if len(content) > max_bytes:
        max_mb = max_bytes / 1024 / 1024
        raise UploadValidationError(f"上传图片不能超过 {max_mb:g} MB")

    normalized_type = (content_type or "").lower().split(";", 1)[0].strip()
    declared_format = _CONTENT_TYPE_TO_FORMAT.get(normalized_type)
    if not declared_format:
        raise UploadValidationError("仅支持 PNG、JPEG 或 WebP 图片")

    detected_format = _detect_image_format(content)
    if detected_format != declared_format:
        raise UploadValidationError("图片内容与格式不匹配")

    suffix = Path(filename or "").suffix.lower()
    if suffix and suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise UploadValidationError("图片文件扩展名不受支持")

    extension = "jpg" if detected_format == "jpeg" else detected_format
    return ValidatedImage(image_format=detected_format, extension=extension)

