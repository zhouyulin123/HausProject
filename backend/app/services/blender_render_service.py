"""把受验证的 SceneDocument 转换为 Blender Worker 清单与静态命令。"""

from copy import deepcopy
import os
from pathlib import Path
from typing import Literal

from app.schemas.scenes import SceneDocument


RenderProfile = Literal["preview", "final"]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_RENDER_PROFILES = {
    "preview": {
        "engine": "BLENDER_EEVEE",
        "width": 960,
        "height": 540,
        "samples": 32,
        "denoise": True,
        "devicePreference": ["OPTIX", "CUDA", "CPU"],
    },
    "final": {
        "engine": "CYCLES",
        "width": 1600,
        "height": 900,
        "samples": 128,
        "denoise": True,
        "devicePreference": ["OPTIX", "CUDA", "CPU"],
    },
}


class BlenderOutputError(ValueError):
    """Blender 子进程产物不符合发布约束。"""


def _resolve_allowlisted_model(
    model_url: str | None,
    *,
    upload_root: Path,
    frontend_public_root: Path,
) -> Path | None:
    if not model_url or "://" in model_url or "\\" in model_url:
        return None
    routes = (
        ("/uploads/", upload_root, model_url.removeprefix("/uploads/")),
        ("/models/", frontend_public_root, model_url.removeprefix("/")),
    )
    for prefix, root, relative in routes:
        if not model_url.startswith(prefix):
            continue
        resolved_root = root.resolve()
        candidate = (resolved_root / relative).resolve()
        if (
            candidate.is_relative_to(resolved_root)
            and candidate.suffix.lower() == ".glb"
            and candidate.is_file()
        ):
            return candidate
    return None


def build_render_manifest(
    *,
    scene: SceneDocument,
    product_model_urls: dict[str, str | None],
    upload_root: Path,
    frontend_public_root: Path,
    profile: RenderProfile,
) -> dict:
    """生成只含声明式场景数据的 Worker 清单，不接受 Python 或 operator。"""
    scene_payload = deepcopy(scene.model_dump(by_alias=True, mode="json"))
    for item in scene_payload["items"]:
        model_path = _resolve_allowlisted_model(
            product_model_urls.get(item["sku"]),
            upload_root=upload_root,
            frontend_public_root=frontend_public_root,
        )
        item["modelPath"] = str(model_path) if model_path else None
    return {
        "schemaVersion": "1.0",
        "profile": deepcopy(_RENDER_PROFILES[profile]),
        "scene": scene_payload,
    }


def build_blender_command(
    *,
    executable: Path,
    script_path: Path,
    manifest_path: Path,
    output_path: Path,
) -> list[str]:
    """构造 shell=False 使用的固定参数列表；所有路径都由 Worker 生成。"""
    return [
        str(executable),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--offline-mode",
        "--python-exit-code",
        "70",
        "--python",
        str(script_path),
        "--",
        "--manifest",
        str(manifest_path),
        "--output",
        str(output_path),
    ]


def publish_render_output(
    temporary_path: Path,
    final_path: Path,
    *,
    max_bytes: int,
) -> Path:
    """校验单张 PNG，并在同一文件系统内原子发布。"""
    if not temporary_path.is_file():
        raise BlenderOutputError("Blender 未生成输出文件")
    size = temporary_path.stat().st_size
    if size < len(PNG_SIGNATURE) or size > max_bytes:
        raise BlenderOutputError("Blender 输出文件大小不合法")
    with temporary_path.open("rb") as handle:
        if handle.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
            raise BlenderOutputError("Blender 输出不是有效 PNG")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary_path, final_path)
    return final_path
