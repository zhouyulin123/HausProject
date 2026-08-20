"""RoomModel → SceneDocument 的确定性转换。

RoomModel 是归一化（0~1）的空间事实，SceneDocument 是米制的可编辑场景。
转换只做几何映射，不引入家具（家具布局由 M2 布局智能体负责）。
真实尺寸优先由用户校准给出；缺省时按房间类型默认尺寸兜底，供预览。
"""

from __future__ import annotations

from math import hypot

from app.schemas.room_model import RoomModel
from app.schemas.scenes import (
    Opening,
    RoomGeometry,
    SceneCamera,
    SceneDocument,
    Vector2XZ,
    Vector3,
)

# 房间类型默认尺寸（米）：与前端 roomLayout.ts 的 ROOM_SIZE 对齐，作为无校准兜底
_DEFAULT_ROOM_SIZE: dict[str, tuple[float, float]] = {
    "客厅": (4.6, 5.6),
    "卧室": (3.6, 4.2),
    "餐厅": (3.6, 3.8),
    "书房": (3.0, 3.6),
    "厨房": (2.8, 3.6),
    "儿童房": (3.2, 3.8),
}
_DEFAULT_SIZE = (4.4, 5.2)
_DEFAULT_CEILING = 2.8

_OPENING_DEFAULTS = {
    "door": (2.1, 0.0),
    "passage": (2.1, 0.0),
    "window": (1.5, 0.9),
}


def room_model_from_analysis(analysis_json: dict) -> RoomModel | None:
    """从 uploaded_images.analysis_json 里解析 RoomModel；缺失或非法返回 None。"""
    data = (analysis_json or {}).get("room_model")
    if not isinstance(data, dict):
        return None
    try:
        return RoomModel.model_validate(data)
    except Exception:
        return None


def _default_size_for(room_name: str) -> tuple[float, float]:
    for key, size in _DEFAULT_ROOM_SIZE.items():
        if key in room_name:
            return size
    return _DEFAULT_SIZE


def room_model_to_scene(
    room_model: RoomModel,
    *,
    room_id: str | None = None,
    dimensions: tuple[float, float] | None = None,
    ceiling_height: float | None = None,
) -> SceneDocument:
    """把 RoomModel 的单个房间转成 SceneDocument。

    参数：
    - room_id：目标房间；缺省取第一个房间。
    - dimensions：(width_m, depth_m) 用户校准后的真实宽深；缺省按房间类型兜底。
    - ceiling_height：用户校准后的层高；缺省 2.8。

    只输出房间结构（墙、门窗、相机），items 为空——家具由布局智能体填充。
    """
    if not room_model.rooms:
        raise ValueError("RoomModel 没有任何房间")

    room = next(
        (r for r in room_model.rooms if r.id == room_id),
        room_model.rooms[0],
    ) if room_id else room_model.rooms[0]

    points = [(p.x, p.z) for p in room.floor_polygon]
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_z = min(p[1] for p in points)
    max_z = max(p[1] for p in points)
    bbox_w = max_x - min_x
    bbox_d = max_z - min_z
    if bbox_w <= 1e-9 or bbox_d <= 1e-9:
        raise ValueError("房间多边形包围盒退化，无法换算米制尺寸")

    if room.width_m and room.depth_m:
        width_m, depth_m = room.width_m, room.depth_m
    elif dimensions:
        width_m, depth_m = dimensions
    else:
        width_m, depth_m = _default_size_for(room.name)

    def to_world(x: float, z: float) -> tuple[float, float]:
        nx = (x - min_x) / bbox_w
        nz = (z - min_z) / bbox_d
        return (nx - 0.5) * width_m, (nz - 0.5) * depth_m

    floor_polygon = [
        Vector2XZ(x=wx, z=wz) for wx, wz in (to_world(x, z) for x, z in points)
    ]
    world_points = [(p.x, p.z) for p in floor_polygon]

    geometry = RoomGeometry(
        id=room.id,
        name=room.name,
        floor_polygon=floor_polygon,
        ceiling_height=ceiling_height or room.ceiling_height or _DEFAULT_CEILING,
        wall_thickness=0.12,
    )

    openings: list[Opening] = []
    for opening in [*room_model.doors, *room_model.windows]:
        if opening.room_id != room.id:
            continue
        wall_index = opening.wall_index
        if wall_index >= len(world_points):
            continue
        start = world_points[wall_index]
        end = world_points[(wall_index + 1) % len(world_points)]
        wall_length = hypot(end[0] - start[0], end[1] - start[1])
        if wall_length <= 1e-9:
            continue
        default_height, default_sill = _OPENING_DEFAULTS[opening.type]
        openings.append(
            Opening(
                id=opening.id,
                type=opening.type,
                wall_index=wall_index,
                offset=opening.offset * wall_length,
                width=opening.width * wall_length,
                height=opening.height or default_height,
                sill_height=(
                    opening.sill_height if opening.sill_height > 0 else default_sill
                ),
            )
        )

    camera = SceneCamera(
        position=Vector3(
            x=width_m * 1.15,
            y=geometry.ceiling_height * 2.2,
            z=depth_m * 1.35,
        ),
        target=Vector3(x=0, y=0.5, z=0),
        fov=45,
    )

    return SceneDocument(
        schema_version="1.0",
        unit="m",
        coordinate_system="right-handed-y-up",
        room=geometry,
        openings=openings,
        items=[],
        camera=camera,
    )


_DIMENSION_CONFIRMATION_KEYS = {
    "roomDimensions",
    "roomWidth",
    "roomDepth",
    "roomArea",
    "ceilingHeight",
}


def apply_calibration(
    room_model: RoomModel,
    *,
    room_id: str | None = None,
    width_m: float,
    depth_m: float,
    ceiling_height: float | None = None,
) -> RoomModel:
    """把用户校准的真实尺寸写进 RoomModel 对应房间，scale 标记为 user。

    房间尺寸一旦由用户确认，就从 requires_confirmation 中移除相关项；
    门窗宽度等仍保留待确认。
    """
    room = (
        next((r for r in room_model.rooms if r.id == room_id), room_model.rooms[0])
        if room_id
        else room_model.rooms[0]
    )
    room.width_m = width_m
    room.depth_m = depth_m
    if ceiling_height is not None:
        room.ceiling_height = ceiling_height
    room_model.scale.source = "user"
    room_model.scale.confidence = 1.0
    room_model.requires_confirmation = [
        item
        for item in room_model.requires_confirmation
        if item not in _DIMENSION_CONFIRMATION_KEYS
    ]
    return room_model
