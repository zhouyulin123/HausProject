from pathlib import Path

import pytest

from app.schemas.scenes import SceneDocument
from app.services.blender_render_service import (
    BlenderOutputError,
    build_blender_command,
    build_render_manifest,
    publish_render_output,
)


def _scene() -> SceneDocument:
    return SceneDocument.model_validate(
        {
            "room": {
                "id": "living-room",
                "name": "客厅",
                "floorPolygon": [
                    {"x": 0, "z": 0},
                    {"x": 5, "z": 0},
                    {"x": 5, "z": 4},
                    {"x": 0, "z": 4},
                ],
                "ceilingHeight": 2.8,
                "wallThickness": 0.12,
            },
            "items": [
                {
                    "instanceId": "sofa-main",
                    "sku": "SOFA-001",
                    "category": "沙发",
                    "dimensions": {"x": 2.4, "y": 0.85, "z": 1.05},
                    "transform": {
                        "position": {"x": 2.5, "y": 0.425, "z": 2.8},
                    },
                },
                {
                    "instanceId": "lamp-main",
                    "sku": "LAMP-001",
                    "dimensions": {"x": 0.4, "y": 1.5, "z": 0.4},
                    "transform": {
                        "position": {"x": 1, "y": 0.75, "z": 1},
                    },
                },
            ],
        }
    )


def test_manifest_resolves_only_allowlisted_local_model_assets(tmp_path):
    upload_root = tmp_path / "uploads"
    public_root = tmp_path / "public"
    uploaded_model = upload_root / "models" / "sofa.glb"
    uploaded_model.parent.mkdir(parents=True)
    uploaded_model.write_bytes(b"glTF")

    manifest = build_render_manifest(
        scene=_scene(),
        product_model_urls={
            "SOFA-001": "/uploads/models/sofa.glb",
            "LAMP-001": "https://attacker.example/payload.glb",
        },
        upload_root=upload_root,
        frontend_public_root=public_root,
        profile="preview",
    )

    assert manifest["schemaVersion"] == "1.0"
    assert manifest["profile"]["engine"] == "BLENDER_EEVEE_NEXT"
    assert manifest["scene"]["items"][0]["modelPath"] == str(
        uploaded_model.resolve()
    )
    assert manifest["scene"]["items"][1]["modelPath"] is None
    assert "instruction" not in str(manifest).lower()


def test_manifest_rejects_path_traversal_even_when_target_exists(tmp_path):
    upload_root = tmp_path / "uploads"
    public_root = tmp_path / "public"
    upload_root.mkdir()
    outside = tmp_path / "outside.glb"
    outside.write_bytes(b"glTF")

    manifest = build_render_manifest(
        scene=_scene(),
        product_model_urls={
            "SOFA-001": "/uploads/../outside.glb",
        },
        upload_root=upload_root,
        frontend_public_root=public_root,
        profile="final",
    )

    assert manifest["profile"]["engine"] == "CYCLES"
    assert manifest["scene"]["items"][0]["modelPath"] is None


def test_blender_command_uses_static_script_without_shell_or_customer_text(
    tmp_path,
):
    command = build_blender_command(
        executable=Path("C:/Program Files/Blender/blender.exe"),
        script_path=tmp_path / "trusted_renderer.py",
        manifest_path=tmp_path / "manifest.json",
        output_path=tmp_path / "render.png",
    )

    assert command[:3] == [
        "C:\\Program Files\\Blender\\blender.exe",
        "--background",
        "--factory-startup",
    ]
    assert command[-4:] == [
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--output",
        str(tmp_path / "render.png"),
    ]
    assert all("删除" not in argument for argument in command)


def test_publish_render_output_validates_png_and_uses_final_directory(tmp_path):
    temporary = tmp_path / "job" / "render.png"
    final = tmp_path / "uploads" / "blender_renders" / "scene-1.png"
    temporary.parent.mkdir(parents=True)
    temporary.write_bytes(b"\x89PNG\r\n\x1a\n" + b"rendered")

    published = publish_render_output(
        temporary,
        final,
        max_bytes=1024,
    )

    assert published == final
    assert final.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert not temporary.exists()


def test_publish_render_output_rejects_non_png(tmp_path):
    temporary = tmp_path / "render.png"
    temporary.write_text("not an image", encoding="utf-8")

    with pytest.raises(BlenderOutputError, match="PNG"):
        publish_render_output(
            temporary,
            tmp_path / "final.png",
            max_bytes=1024,
        )
