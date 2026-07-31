"""Blender 内部运行的可信静态脚本；仅消费声明式 JSON 清单。"""

from __future__ import annotations

import argparse
import json
from math import atan2, hypot
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def _arguments() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def _load_manifest(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("manifest 文件不存在或过大")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != "1.0":
        raise ValueError("不支持的 manifest 版本")
    if not isinstance(data.get("scene"), dict):
        raise ValueError("manifest 缺少 scene")
    return data


def _clear_scene() -> None:
    for object_ in list(bpy.data.objects):
        bpy.data.objects.remove(object_, do_unlink=True)


def _material(name: str, color: tuple[float, float, float, float]):
    material = bpy.data.materials.new(name=name)
    material.diffuse_color = color
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Roughness"].default_value = 0.58
    return material


def _cube(
    name: str,
    *,
    location: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    material,
    rotation_y: float = 0.0,
):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    object_ = bpy.context.object
    object_.name = name
    object_.dimensions = dimensions
    object_.rotation_euler[2] = -rotation_y
    object_.data.materials.append(material)
    bpy.context.view_layer.objects.active = object_
    object_.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    object_.select_set(False)
    return object_


def _floor(scene_data: dict, material) -> None:
    points = scene_data["room"]["floorPolygon"]
    mesh = bpy.data.meshes.new("RoomFloorMesh")
    vertices = [(point["x"], point["z"], 0.0) for point in points]
    mesh.from_pydata(vertices, [], [list(range(len(vertices)))])
    mesh.update()
    floor = bpy.data.objects.new("RoomFloor", mesh)
    bpy.context.collection.objects.link(floor)
    floor.data.materials.append(material)


def _walls(scene_data: dict, material) -> None:
    room = scene_data["room"]
    points = room["floorPolygon"]
    height = room["ceilingHeight"]
    thickness = room.get("wallThickness", 0.12)
    openings_by_wall: dict[int, list[dict]] = {}
    for opening in scene_data.get("openings", []):
        openings_by_wall.setdefault(opening["wallIndex"], []).append(opening)
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        delta_x = end["x"] - start["x"]
        delta_z = end["z"] - start["z"]
        length = hypot(delta_x, delta_z)
        if length <= 1e-6:
            continue
        tangent_x = delta_x / length
        tangent_z = delta_z / length
        wall_angle = -atan2(delta_z, delta_x)

        def add_piece(
            name: str,
            *,
            from_offset: float,
            to_offset: float,
            bottom: float,
            top: float,
        ) -> None:
            width = to_offset - from_offset
            piece_height = top - bottom
            if width <= 1e-5 or piece_height <= 1e-5:
                return
            center_offset = (from_offset + to_offset) / 2
            _cube(
                name,
                location=(
                    start["x"] + tangent_x * center_offset,
                    start["z"] + tangent_z * center_offset,
                    (bottom + top) / 2,
                ),
                dimensions=(width, thickness, piece_height),
                material=material,
                rotation_y=wall_angle,
            )

        cursor = 0.0
        wall_openings = sorted(
            openings_by_wall.get(index, []),
            key=lambda opening: opening["offset"],
        )
        for opening_index, opening in enumerate(wall_openings):
            opening_start = min(length, max(cursor, opening["offset"]))
            opening_end = min(
                length,
                max(opening_start, opening["offset"] + opening["width"]),
            )
            add_piece(
                f"Wall-{index}-side-{opening_index}",
                from_offset=cursor,
                to_offset=opening_start,
                bottom=0,
                top=height,
            )
            sill = min(height, max(0.0, opening.get("sillHeight", 0.0)))
            opening_top = min(height, sill + opening["height"])
            add_piece(
                f"Wall-{index}-below-{opening_index}",
                from_offset=opening_start,
                to_offset=opening_end,
                bottom=0,
                top=sill,
            )
            add_piece(
                f"Wall-{index}-above-{opening_index}",
                from_offset=opening_start,
                to_offset=opening_end,
                bottom=opening_top,
                top=height,
            )
            cursor = max(cursor, opening_end)
        add_piece(
            f"Wall-{index}-tail",
            from_offset=cursor,
            to_offset=length,
            bottom=0,
            top=height,
        )


def _import_glb(item: dict) -> bool:
    model_path = item.get("modelPath")
    if not model_path:
        return False
    path = Path(model_path)
    if path.suffix.lower() != ".glb" or not path.is_file():
        return False
    existing_names = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = [
        object_
        for name, object_ in bpy.data.objects.items()
        if name not in existing_names and object_.type in {"MESH", "EMPTY"}
    ]
    meshes = [object_ for object_ in imported if object_.type == "MESH"]
    if not meshes:
        return False

    corners = [
        object_.matrix_world @ Vector(corner)
        for object_ in meshes
        for corner in object_.bound_box
    ]
    minimum = Vector(
        (
            min(corner.x for corner in corners),
            min(corner.y for corner in corners),
            min(corner.z for corner in corners),
        )
    )
    maximum = Vector(
        (
            max(corner.x for corner in corners),
            max(corner.y for corner in corners),
            max(corner.z for corner in corners),
        )
    )
    size = maximum - minimum
    center = (minimum + maximum) / 2
    root = bpy.data.objects.new(f"Asset-{item['instanceId']}", None)
    root.location = center
    bpy.context.collection.objects.link(root)
    for object_ in imported:
        world = object_.matrix_world.copy()
        object_.parent = root
        object_.matrix_world = world

    dimensions = item["dimensions"]
    root.scale = (
        dimensions["x"] / max(size.x, 1e-6),
        dimensions["z"] / max(size.y, 1e-6),
        dimensions["y"] / max(size.z, 1e-6),
    )
    transform = item["transform"]
    position = transform["position"]
    rotation = transform["rotation"]
    root.location = (position["x"], position["z"], position["y"])
    root.rotation_euler[2] = -rotation["y"]
    return True


def _furniture(scene_data: dict, material) -> None:
    for item in scene_data.get("items", []):
        dimensions = item.get("dimensions")
        if not dimensions:
            continue
        if _import_glb(item):
            continue
        transform = item["transform"]
        position = transform["position"]
        rotation = transform["rotation"]
        scale = transform["scale"]
        _cube(
            f"Fallback-{item['instanceId']}",
            location=(position["x"], position["z"], position["y"]),
            dimensions=(
                dimensions["x"] * scale["x"],
                dimensions["z"] * scale["z"],
                dimensions["y"] * scale["y"],
            ),
            material=material,
            rotation_y=rotation["y"],
        )


def _look_at(object_, target: Vector) -> None:
    direction = target - object_.location
    object_.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _camera_and_lights(scene_data: dict) -> None:
    points = scene_data["room"]["floorPolygon"]
    center_x = sum(point["x"] for point in points) / len(points)
    center_z = sum(point["z"] for point in points) / len(points)
    span_x = max(point["x"] for point in points) - min(
        point["x"] for point in points
    )
    span_z = max(point["z"] for point in points) - min(
        point["z"] for point in points
    )
    minimum_x = min(point["x"] for point in points)
    minimum_z = min(point["z"] for point in points)
    camera_data = bpy.data.cameras.new("Camera")
    camera = bpy.data.objects.new("Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (
        minimum_x + span_x * 0.09,
        minimum_z + span_z * 0.89,
        min(2.35, scene_data["room"]["ceilingHeight"] * 0.84),
    )
    _look_at(camera, Vector((center_x, center_z, 0.65)))
    camera.data.lens = 18
    bpy.context.scene.camera = camera

    for index, (x_offset, z_offset, energy, size) in enumerate(
        ((-1.5, -1.0, 300, 3.0), (1.5, 1.0, 180, 2.0))
    ):
        light_data = bpy.data.lights.new(f"AreaLight-{index}", "AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = size
        light = bpy.data.objects.new(f"AreaLight-{index}", light_data)
        light.location = (
            center_x + x_offset,
            center_z + z_offset,
            scene_data["room"]["ceilingHeight"] - 0.25,
        )
        bpy.context.collection.objects.link(light)
        _look_at(light, Vector((center_x, center_z, 0)))


def _configure_render(profile: dict, output_path: Path) -> None:
    scene = bpy.context.scene
    scene.render.engine = profile["engine"]
    scene.render.resolution_x = profile["width"]
    scene.render.resolution_y = profile["height"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.filepath = str(output_path)
    scene.view_settings.exposure = -1.15
    selected_device = "CPU"
    if profile["engine"] == "CYCLES":
        scene.cycles.samples = profile["samples"]
        scene.cycles.use_denoising = bool(profile.get("denoise", True))
        for device_type in profile.get("devicePreference", []):
            if device_type == "CPU":
                scene.cycles.device = "CPU"
                selected_device = "CPU"
                break
            try:
                preferences = bpy.context.preferences.addons[
                    "cycles"
                ].preferences
                preferences.compute_device_type = device_type
                preferences.get_devices()
                enabled = False
                for device in preferences.devices:
                    device.use = device.type != "CPU"
                    enabled = enabled or device.use
                if enabled:
                    scene.cycles.device = "GPU"
                    selected_device = device_type
                    break
            except Exception:
                continue
    print(f"HAUS_RENDER_ENGINE={profile['engine']}")
    print(f"HAUS_RENDER_DEVICE={selected_device}")


def main() -> None:
    args = _arguments()
    manifest_path = Path(args.manifest).resolve()
    output_path = Path(args.output).resolve()
    if output_path.suffix.lower() != ".png":
        raise ValueError("输出必须是 PNG")
    manifest = _load_manifest(manifest_path)
    _clear_scene()
    floor_material = _material("Floor", (0.36, 0.24, 0.14, 1))
    wall_material = _material("Wall", (0.82, 0.78, 0.7, 1))
    furniture_material = _material("Furniture", (0.52, 0.32, 0.18, 1))
    scene_data = manifest["scene"]
    _floor(scene_data, floor_material)
    _walls(scene_data, wall_material)
    _furniture(scene_data, furniture_material)
    _camera_and_lights(scene_data)
    world = bpy.context.scene.world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.16, 0.14, 0.12, 1)
        background.inputs["Strength"].default_value = 0.22
    _configure_render(manifest["profile"], output_path)
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
