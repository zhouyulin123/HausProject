"""确定性布局候选生成器：按家具类别生成多组候选布局，用评分器选优。

不靠 LLM 猜坐标：沙发靠后墙、电视柜对面、茶几在前、床靠侧墙等规则，
结合房间真实尺寸、门窗位置与商品真实三维尺寸，输出可计算的候选布局。
当前聚焦矩形客厅，其余类别沿墙兜底排布（M2 后半段再扩展其他空间）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.schemas.scenes import (
    Opening,
    PositiveVector3,
    RoomGeometry,
    SceneCamera,
    SceneDocument,
    SceneItem,
    Transform,
    Vector3,
)
from app.services.layout_evaluator import LayoutScore, evaluate_layout
from app.services.layout_repair import repair_layout

# 贴墙安全边距（米）
WALL_MARGIN = 0.15
# 沙发与茶几的前后间距（米）
TABLE_GAP = 0.4
# 沿墙排布的相邻家具间距（米）
ROW_GAP = 0.3

_SOFA_CATEGORIES = {"沙发"}
_TV_CATEGORIES = {"柜子", "电视柜"}
_RUG_CATEGORIES = {"地毯", "地垫"}
_LAMP_CATEGORIES = {"灯具", "落地灯"}
_CHAIR_CATEGORIES = {"休闲椅", "单人椅", "单椅"}
_BED_CATEGORIES = {"床"}
_BEDSIDE_TABLE_CATEGORIES = {"床头柜"}
_CABINET_CATEGORIES = {"柜子", "衣柜"}
_DINING_TABLE_CATEGORIES = {"餐桌"}
_DINING_CHAIR_CATEGORIES = {"餐椅"}
_DESK_CATEGORIES = {"书桌"}
_OFFICE_CHAIR_CATEGORIES = {"书椅", "工作椅"}


@dataclass
class LayoutFurniture:
    sku: str
    name: str
    category: str
    width_m: float
    depth_m: float
    height_m: float


def _safe_stem(sku: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", sku).strip("-")
    return stem or "item"


def _scene_item(
    furniture: LayoutFurniture,
    index: int,
    x: float,
    z: float,
    rotation_y: float,
) -> SceneItem:
    return SceneItem(
        instance_id=f"item-{_safe_stem(furniture.sku)}-{index + 1}",
        sku=furniture.sku,
        category=furniture.category,
        dimensions=PositiveVector3(
            x=furniture.width_m,
            y=furniture.height_m,
            z=furniture.depth_m,
        ),
        transform=Transform(
            position=Vector3(x=x, y=furniture.height_m / 2, z=z),
            rotation=Vector3(x=0, y=rotation_y, z=0),
            scale=PositiveVector3(x=1, y=1, z=1),
        ),
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _layout_items(
    furniture: list[LayoutFurniture],
    room_w: float,
    room_d: float,
    variant: str,
) -> list[SceneItem]:
    """按变体生成一组家具摆放（矩形房间，中心在原点）。"""
    half_w = room_w / 2
    half_d = room_d / 2
    items: list[SceneItem] = []
    index = 0

    def place(
        f: LayoutFurniture,
        x: float,
        z: float,
        rotation_y: float = 0.0,
    ) -> None:
        nonlocal index
        items.append(_scene_item(f, index, x, z, rotation_y))
        index += 1

    sofa = next((f for f in furniture if f.category in _SOFA_CATEGORIES), None)
    tv = next(
        (
            f
            for f in furniture
            if f.category in _TV_CATEGORIES
            and ("电视" in f.name or "TV" in f.sku.upper())
        ),
        next((f for f in furniture if f.category in _TV_CATEGORIES), None),
    )
    tea_table = next((f for f in furniture if f.category == "茶几"), None)
    rug = next((f for f in furniture if f.category in _RUG_CATEGORIES), None)
    lamp = next((f for f in furniture if f.category in _LAMP_CATEGORIES), None)
    armchair = next(
        (f for f in furniture if f.category in _CHAIR_CATEGORIES), None
    )
    bed = next((f for f in furniture if f.category in _BED_CATEGORIES), None)
    dining_table = next(
        (f for f in furniture if f.category in _DINING_TABLE_CATEGORIES), None
    )
    desk = next((f for f in furniture if f.category in _DESK_CATEGORIES), None)

    used: set[int] = set()
    sofa_x = 0.0
    sofa_z = 0.0

    # ---- 沙发：靠后墙，变体控制左右偏移
    if sofa:
        offset = 0.0
        if variant == "left":
            offset = -max(0.25 * half_w, 0.5)
        elif variant == "right":
            offset = max(0.25 * half_w, 0.5)
        offset = _clamp(
            offset,
            -half_w + sofa.width_m / 2 + WALL_MARGIN,
            half_w - sofa.width_m / 2 - WALL_MARGIN,
        )
        sofa_x = offset
        sofa_z = -half_d + sofa.depth_m / 2 + WALL_MARGIN
        place(sofa, sofa_x, sofa_z)
        used.add(id(sofa))

    # ---- 电视柜：与沙发正对靠前墙（仅在客厅有沙发时；卧室衣柜走衣柜分支）
    if tv and sofa:
        tv_x = _clamp(
            sofa_x,
            -half_w + tv.width_m / 2 + WALL_MARGIN,
            half_w - tv.width_m / 2 - WALL_MARGIN,
        )
        tv_z = half_d - tv.depth_m / 2 - WALL_MARGIN
        place(tv, tv_x, tv_z, rotation_y=math.pi)
        used.add(id(tv))

    # ---- 茶几：沙发正前方
    if tea_table and sofa:
        tea_z = (
            sofa_z
            + sofa.depth_m / 2
            + TABLE_GAP
            + tea_table.depth_m / 2
        )
        tea_z = min(tea_z, half_d - tea_table.depth_m / 2 - WALL_MARGIN)
        place(tea_table, sofa_x, tea_z)
        used.add(id(tea_table))

    # ---- 地毯：沙发前平铺
    if rug and sofa:
        rug_z = sofa_z + sofa.depth_m / 2 + rug.depth_m / 2
        place(rug, sofa_x, min(rug_z, half_d - rug.depth_m / 2 - WALL_MARGIN))
        used.add(id(rug))

    # ---- 落地灯：右后角
    if lamp:
        lamp_x = half_w - lamp.width_m / 2 - 0.35
        lamp_z = -half_d + lamp.depth_m / 2 + 0.35
        place(lamp, lamp_x, lamp_z)
        used.add(id(lamp))

    # ---- 休闲椅：沙发左侧
    if armchair:
        chair_x = -half_w + armchair.width_m / 2 + 0.3
        place(armchair, chair_x, sofa_z if sofa else 0)
        used.add(id(armchair))

    # ---- 卧室：床（靠后墙居中 / 靠侧墙变体）+ 床头柜 + 衣柜
    if bed:
        if variant == "left":
            bed_x = -half_w + bed.depth_m / 2 + WALL_MARGIN
            place(bed, bed_x, 0, rotation_y=math.pi / 2)
            bed_rot_y = math.pi / 2
        elif variant == "right":
            bed_x = half_w - bed.depth_m / 2 - WALL_MARGIN
            place(bed, bed_x, 0, rotation_y=math.pi / 2)
            bed_rot_y = math.pi / 2
        else:
            bed_z = -half_d + bed.depth_m / 2 + WALL_MARGIN
            place(bed, 0, bed_z)
            bed_rot_y = 0.0
        used.add(id(bed))

        # 床头柜：贴着床的短边两侧
        bedside_tables = [
            f for f in furniture if f.category in _BEDSIDE_TABLE_CATEGORIES
        ]
        for table_index, table in enumerate(bedside_tables):
            side = 1 if table_index % 2 == 0 else -1
            if bed_rot_y == 0:
                table_x = side * (bed.width_m / 2 + table.width_m / 2 + 0.05)
                place(table, table_x, bed_z)
            else:
                table_z = side * (bed.width_m / 2 + table.depth_m / 2 + 0.05)
                place(table, bed_x, table_z)
            used.add(id(table))

        # 衣柜：床对面墙（前墙）依次排布，面向床
        cabinets = [
            f for f in furniture if f.category in _CABINET_CATEGORIES
        ]
        cabinet_count = len(cabinets)
        for cabinet_index, cabinet in enumerate(cabinets):
            cabinet_x = (cabinet_index - (cabinet_count - 1) / 2) * (
                cabinet.width_m + 0.3
            )
            cabinet_x = _clamp(
                cabinet_x,
                -half_w + cabinet.width_m / 2 + WALL_MARGIN,
                half_w - cabinet.width_m / 2 - WALL_MARGIN,
            )
            place(
                cabinet,
                cabinet_x,
                half_d - cabinet.depth_m / 2 - WALL_MARGIN,
                rotation_y=math.pi,
            )
            used.add(id(cabinet))

    # ---- 餐厅：餐桌居中 + 餐椅围绕
    if dining_table:
        place(dining_table, 0, 0)
        used.add(id(dining_table))
        dining_chairs = [
            f for f in furniture if f.category in _DINING_CHAIR_CATEGORIES
        ]
        if dining_chairs:
            chair_depth = dining_chairs[0].depth_m
            chair_width = dining_chairs[0].width_m
            gap = 0.05
            top_z = dining_table.depth_m / 2 + chair_depth / 2 + gap
            right_x = dining_table.width_m / 2 + chair_width / 2 + gap
            positions = [
                (0.0, top_z, math.pi),
                (0.0, -top_z, 0.0),
                (right_x, 0.0, -math.pi / 2),
                (-right_x, 0.0, math.pi / 2),
                (0.0, top_z + chair_depth + gap, math.pi),
                (0.0, -(top_z + chair_depth + gap), 0.0),
            ]
            for chair_index, chair in enumerate(dining_chairs):
                if chair_index >= len(positions):
                    break
                x, z, rotation_y = positions[chair_index]
                place(chair, x, z, rotation_y=rotation_y)
                used.add(id(chair))

    # ---- 书房：书桌靠后墙 + 书椅在前（卧室里的梳妆台走沿墙排布，避免与床重叠）
    if desk and not bed:
        desk_z = -half_d + desk.depth_m / 2 + WALL_MARGIN
        place(desk, 0, desk_z)
        used.add(id(desk))
        office_chair = next(
            (f for f in furniture if f.category in _OFFICE_CHAIR_CATEGORIES),
            None,
        )
        if office_chair is not None:
            chair_z = (
                desk_z
                + desk.depth_m / 2
                + office_chair.depth_m / 2
                + 0.15
            )
            place(office_chair, 0, chair_z, rotation_y=math.pi)
            used.add(id(office_chair))

    # ---- 其余沿左墙依次排布
    cursor = -half_d + 0.5
    for f in furniture:
        if id(f) in used:
            continue
        z = _clamp(
            cursor + f.depth_m / 2,
            -half_d + f.depth_m / 2 + WALL_MARGIN,
            half_d - f.depth_m / 2 - WALL_MARGIN,
        )
        place(f, -half_w + f.width_m / 2 + 0.2, z)
        cursor += f.depth_m + ROW_GAP

    return items


def _room_extent(room: RoomGeometry) -> tuple[float, float]:
    xs = [p.x for p in room.floor_polygon]
    zs = [p.z for p in room.floor_polygon]
    return max(xs) - min(xs), max(zs) - min(zs)


def _build_camera(room_w: float, room_d: float, ceiling_height: float) -> SceneCamera:
    return SceneCamera(
        position=Vector3(
            x=room_w * 1.15,
            y=ceiling_height * 2.2,
            z=room_d * 1.35,
        ),
        target=Vector3(x=0, y=0.5, z=0),
        fov=45,
    )


def generate_layouts(
    room: RoomGeometry,
    openings: list[Opening],
    furniture: list[LayoutFurniture],
    *,
    variants: tuple[str, ...] = ("center", "left", "right"),
) -> list[tuple[SceneDocument, LayoutScore]]:
    """生成多组候选布局并按评分降序返回。

    返回 [(SceneDocument, LayoutScore), ...]，每组都是可编辑的完整场景。
    """
    if not furniture:
        return []

    room_w, room_d = _room_extent(room)
    results: list[tuple[SceneDocument, LayoutScore]] = []
    for variant in variants:
        items = _layout_items(furniture, room_w, room_d, variant)
        scene = SceneDocument(
            schema_version="1.0",
            unit="m",
            coordinate_system="right-handed-y-up",
            room=room,
            openings=openings,
            items=items,
            camera=_build_camera(room_w, room_d, room.ceiling_height),
        )
        # 确定性修复后再评分（generate → evaluate → repair → re-evaluate）
        repaired, score = repair_layout(scene)
        results.append((repaired, score))
    results.sort(key=lambda pair: pair[1].total, reverse=True)
    return results
