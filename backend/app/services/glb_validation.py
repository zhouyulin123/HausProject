"""GLB 2.0 商品模型上传校验。"""

from dataclasses import dataclass
import json
from pathlib import Path
import struct


class GlbValidationError(ValueError):
    """上传内容不是可安全接收的 GLB 2.0 文件。"""


@dataclass(frozen=True)
class ValidatedGlb:
    version: int
    extension: str = "glb"


_ALLOWED_CONTENT_TYPES = {
    "model/gltf-binary",
    "application/octet-stream",
}


def validate_glb_upload(
    *,
    content: bytes,
    content_type: str,
    filename: str,
    max_bytes: int,
) -> ValidatedGlb:
    """校验大小、声明类型、扩展名与 GLB 2.0 容器头和 JSON 块。"""
    if not content:
        raise GlbValidationError("上传模型不能为空")
    if len(content) > max_bytes:
        max_mb = max_bytes / 1024 / 1024
        raise GlbValidationError(f"上传模型不能超过 {max_mb:g} MB")

    normalized_type = (content_type or "").lower().split(";", 1)[0].strip()
    if normalized_type not in _ALLOWED_CONTENT_TYPES:
        raise GlbValidationError("GLB 文件类型不受支持")
    if Path(filename or "").suffix.lower() != ".glb":
        raise GlbValidationError("模型文件扩展名必须为 .glb")
    if len(content) < 20:
        raise GlbValidationError("GLB 文件结构不完整")

    magic, version, declared_length = struct.unpack_from("<4sII", content, 0)
    if magic != b"glTF":
        raise GlbValidationError("GLB 文件签名无效")
    if version != 2:
        raise GlbValidationError("仅支持 glTF 2.0 模型")
    if declared_length != len(content):
        raise GlbValidationError("GLB 声明长度与文件长度不一致")

    json_length, chunk_type = struct.unpack_from("<I4s", content, 12)
    json_end = 20 + json_length
    if chunk_type != b"JSON" or json_length == 0 or json_end > len(content):
        raise GlbValidationError("GLB JSON 块无效")
    try:
        document = json.loads(content[20:json_end].decode("utf-8").rstrip(" \t\r\n\x00"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GlbValidationError("GLB JSON 块无法解析") from exc
    asset_version = str((document.get("asset") or {}).get("version", ""))
    if not asset_version.startswith("2."):
        raise GlbValidationError("GLB 资产版本必须为 2.0")
    return ValidatedGlb(version=version)
