"""把家具参数目录编译为可直接渲染的确定性结构族规则。"""

from __future__ import annotations

from copy import deepcopy
from math import cos, pi, sin
from typing import Any, Callable


class FurnitureFamilyRuleError(ValueError):
    """家具族缺少生成确定性结构所需的源参数。"""


def _number(mapping: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    raise FurnitureFamilyRuleError(f"缺少数值字段：{' / '.join(keys)}")


def _number_or(mapping: dict[str, Any], default: float, *keys: str) -> float:
    try:
        return _number(mapping, *keys)
    except FurnitureFamilyRuleError:
        return default


def _pair(mapping: dict[str, Any], *keys: str) -> list[float]:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, list) and len(value) == 2 and all(
            isinstance(item, (int, float)) for item in value
        ):
            return value
    raise FurnitureFamilyRuleError(f"缺少双值字段：{' / '.join(keys)}")


def _part(
    part_id: str,
    geometry: str,
    size: list[float],
    position: list[float],
    material: str,
    rotation: list[float] | None = None,
    **details: Any,
) -> dict[str, Any]:
    return {
        "部件ID": part_id,
        "几何": geometry,
        "尺寸_mm": [round(value, 4) for value in size],
        "位置_mm": [round(value, 4) for value in position],
        "旋转_deg": rotation or [0, 0, 0],
        "材质槽": material,
        **details,
    }


def _surface_type(material: dict[str, Any]) -> str:
    text = f"{material.get('部位', '')}{material.get('材质', '')}"
    taxonomy = (
        ("glass", ("玻璃",)),
        ("metal", ("钢", "金属", "黄铜", "铝合金", "PVD")),
        ("stone", ("岩板", "洞石", "陶瓷", "微水泥")),
        ("paper", ("纸", "和纸")),
        ("rattan", ("藤",)),
        ("wood", ("木", "木皮")),
        ("mesh", ("网",)),
        ("fabric", ("布", "绒", "皮", "羊毛", "聚酯", "丙纶", "亚麻")),
    )
    for surface, words in taxonomy:
        if any(word in text for word in words):
            return surface
    return "generic"


def _material_slots(spec: dict[str, Any]) -> list[dict[str, Any]]:
    materials = spec.get("材质参数")
    if not isinstance(materials, list) or not materials:
        raise FurnitureFamilyRuleError(f"{spec.get('家具名称')} 缺少材质参数")
    slots = []
    for index, source in enumerate(materials):
        if not isinstance(source, dict):
            raise FurnitureFamilyRuleError("材质参数必须为对象")
        slot = deepcopy(source)
        slot["槽位ID"] = f"material_{index}"
        slot["表面类型"] = _surface_type(slot)
        slots.append(slot)
    return slots


def _appearance(slots: list[dict[str, Any]]) -> dict[str, Any]:
    appearance: dict[str, Any] = {
        "表面": {
            slot["槽位ID"]: {
                "类型": slot["表面类型"],
                "法线强度": slot.get("normal_strength", 0.12),
            }
            for slot in slots
        }
    }
    wood = next((slot for slot in slots if slot["表面类型"] == "wood"), None)
    if wood:
        appearance["木材"] = {
            "树种": wood.get("材质", "实木"),
            "纹理周期_mm": 48,
            "法线强度": wood.get("normal_strength", 0.14),
            "透明面漆": {"强度": 0.1, "粗糙度": 0.68},
            "榫卯节点": {
                "启用": True,
                "榫肩线宽_mm": 1,
                "距构件端部_mm": 16,
            },
        }
    fabric = next(
        (slot for slot in slots if slot["表面类型"] in {"fabric", "rattan"}),
        None,
    )
    if fabric:
        appearance["软包"] = {
            "滚边": {"启用": True, "直径_mm": 6},
            "缝线": {"启用": True, "线径_mm": 1.2, "内缩_mm": 9},
            "绒面": {
                "方向性": fabric["表面类型"] == "fabric",
                "法线强度": fabric.get("normal_strength", 0.16),
                "纹理周期_mm": 4,
            },
            "坐垫形变": {"前缘压缩": 0.04, "中心隆起_mm": 8},
            "靠背曲面": {"横向弧度半径_mm": 1000},
        }
    return appearance


def _material_slot_for(
    spec: dict[str, Any],
    *,
    surfaces: tuple[str, ...] = (),
    part_words: tuple[str, ...] = (),
    fallback: int = 0,
) -> str:
    materials = spec["材质参数"]
    for index, material in enumerate(materials):
        part = str(material.get("部位", ""))
        if part_words and any(word in part for word in part_words):
            return f"material_{index}"
    for index, material in enumerate(materials):
        if surfaces and _surface_type(material) in surfaces:
            return f"material_{index}"
    return f"material_{min(fallback, len(materials) - 1)}"


def _base_rule(
    spec: dict[str, Any],
    model_id: str,
    generator: str,
    bounds: tuple[float, float, float],
    parts: list[dict[str, Any]],
    frozen: dict[str, Any],
    installation: str = "floor",
    extra_materials: list[dict[str, Any]] | None = None,
    preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    slots = _material_slots(spec)
    for source in extra_materials or []:
        slot = deepcopy(source)
        slot["槽位ID"] = f"material_{len(slots)}"
        slot["表面类型"] = _surface_type(slot)
        slots.append(slot)
    mesh = spec.get("网格与贴图") or {}
    rule = {
        "规则版本": "2.0.0",
        "规则状态": "ready",
        "模型ID": model_id,
        "家具名称": spec["家具名称"],
        "家具类型": spec["家具类型"],
        "生成器": generator,
        "坐标系统": {"单位": "mm", "上轴": "Y", "前向": "+Z", "原点": "floor_center"},
        "安装规则": {"基准": installation, "偏移_mm": 0},
        "包围尺寸_mm": {"宽": bounds[0], "高": bounds[1], "深": bounds[2]},
        "几何规则": {"显式部件数": len(parts), "结构族": generator},
        "外观规则": _appearance(slots),
        "材质槽": slots,
        "部件": parts,
        "质量规则": {
            "目标三角面": mesh.get("目标三角面", 32000),
            "需要UV": mesh.get("UV", True),
            "贴图分辨率": mesh.get("贴图分辨率", "2K"),
            "LOD": deepcopy(mesh.get("LOD", [32000, 16000, 6000])),
        },
        "设计冻结": {
            **frozen,
            "说明": "源参数未给出的加工尺寸在结构族规则 2.0 中显式冻结。",
        },
    }
    if preview:
        rule["预览规则"] = preview
    return rule


SOFA_FREEZE = {
    "云朵感三人位布艺沙发": (3, 210, 35, False),
    "奶油白猫抓布转角沙发": (3, 180, 115, True),
    "云感模块三人沙发": (3, 210, 35, False),
    "胡桃木框皮布混搭沙发": (3, 120, 170, False),
    "浅灰羽绒感转角沙发": (3, 190, 40, True),
    "原木框双人休闲沙发": (2, 110, 175, False),
}


def _sofa_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    dims = spec["尺寸参数"]
    shape = spec["造型参数"]
    width = _number(dims, "总宽")
    depth = _number(dims, "总深")
    height = _number(dims, "总高")
    seat_height = _number(dims, "座高")
    seat_depth = _number(dims, "座深")
    seats, arm_width, leg_height, sectional = SOFA_FREEZE[spec["家具名称"]]
    gap = _number_or(shape, 12, "座包缝隙", "座包缝隙_mm")
    inner_width = width - arm_width * 2
    cushion_width = (inner_width - gap * (seats - 1)) / seats
    cushion_height = 105
    back_height = height - seat_height + 70
    back_thickness = 150
    wood_frame = spec["家具名称"] in {"胡桃木框皮布混搭沙发", "原木框双人休闲沙发"}
    frame_material = "material_0" if wood_frame else "material_1"
    soft_material = "material_1" if wood_frame else "material_0"
    base_height = max(90, seat_height - cushion_height - leg_height)
    seat_rear = -depth / 2 + back_thickness
    main_depth = min(depth - 70, seat_depth + back_thickness * 0.72)
    main_z = -depth / 2 + main_depth / 2
    arm_height = min(height - leg_height, seat_height + 145 - leg_height)
    body_material = frame_material if wood_frame else soft_material
    parts = [
        _part("main_seat_frame" if sectional else "seat_frame", "rounded_box", [width - 40, base_height, main_depth], [0, leg_height + base_height / 2, main_z], body_material, 圆角_mm=24),
        _part("left_arm", "rounded_box", [arm_width, arm_height, main_depth], [-(width - arm_width) / 2, leg_height + arm_height / 2, main_z], soft_material if not wood_frame else frame_material, 圆角_mm=36),
    ]
    if sectional:
        chaise_x = inner_width / 2 - cushion_width / 2
        chaise_depth = depth - back_thickness
        chaise_z = back_thickness / 2
        parts.extend([
            _part("chaise_frame", "rounded_box", [cushion_width + 50, base_height, chaise_depth], [chaise_x, leg_height + base_height / 2, chaise_z], body_material, 圆角_mm=24),
            _part("chaise_outer_arm", "rounded_box", [arm_width, arm_height, chaise_depth], [(width - arm_width) / 2, leg_height + arm_height / 2, chaise_z], soft_material if not wood_frame else frame_material, 圆角_mm=36),
        ])
    else:
        parts.append(_part("right_arm", "rounded_box", [arm_width, arm_height, main_depth], [(width - arm_width) / 2, leg_height + arm_height / 2, main_z], soft_material if not wood_frame else frame_material, 圆角_mm=36))
    for index in range(seats):
        x = -inner_width / 2 + cushion_width / 2 + index * (cushion_width + gap)
        current_depth = depth - back_thickness if sectional and index == seats - 1 else seat_depth
        z = seat_rear + current_depth / 2
        parts.extend(
            [
                _part(f"seat_cushion_{index + 1}", "rounded_cushion", [cushion_width, cushion_height, current_depth], [x, seat_height - cushion_height / 2 + 25, z], soft_material),
                _part(f"back_cushion_{index + 1}", "curved_cushion", [cushion_width, back_height, back_thickness], [x, seat_height + back_height / 2 - 20, -depth / 2 + back_thickness / 2], soft_material, [-_number_or(spec["结构参数"], 10, "靠背后倾角_deg"), 0, 0]),
            ]
        )
    leg_x = width / 2 - 110
    rear_z = -depth / 2 + 100
    main_front_z = main_z + main_depth / 2 - 80
    foot_positions = [
        ("rear_left_foot", -leg_x, rear_z),
        ("rear_right_foot", leg_x, rear_z),
        ("main_front_left_foot", -leg_x, main_front_z),
        ("main_front_right_foot", leg_x, main_front_z),
    ]
    if sectional:
        foot_positions.extend([
            ("chaise_front_inner_foot", inner_width / 2 - cushion_width + 70, depth / 2 - 90),
            ("chaise_front_outer_foot", leg_x, depth / 2 - 90),
        ])
    for part_id, x, z in foot_positions:
        parts.append(_part(part_id, "tapered_wood_leg" if wood_frame else "rounded_box", [42, leg_height, 42], [x, leg_height / 2, z], frame_material, 圆角_mm=6))
    return _base_rule(
        spec, model_id, "sofa_v2", (width, height, depth), parts,
        {"座包厚度_mm": cushion_height, "靠背厚度_mm": back_thickness, "扶手宽_mm": arm_width, "座包缝隙_mm": gap, "支脚高度_mm": leg_height, "转角位": sectional},
    )


def _rect_table_parts(
    length: float, depth: float, height: float, top: float, material: str,
    leg_material: str | None = None, radius: float = 18, splay: float = 2,
) -> list[dict[str, Any]]:
    leg_material = leg_material or material
    leg_height = height - top
    leg_section = 52
    inset_x, inset_z = 105, 80
    parts = [_part("tabletop", "rounded_tabletop", [length, top, depth], [0, leg_height + top / 2, 0], material, 平面圆角半径_mm=radius * 4, 边缘圆角_mm=radius)]
    for part_id, x, z, rx, rz in (
        ("front_left_leg", -length / 2 + inset_x, depth / 2 - inset_z, splay, -splay),
        ("front_right_leg", length / 2 - inset_x, depth / 2 - inset_z, splay, splay),
        ("rear_left_leg", -length / 2 + inset_x, -depth / 2 + inset_z, -splay, -splay),
        ("rear_right_leg", length / 2 - inset_x, -depth / 2 + inset_z, -splay, splay),
    ):
        parts.append(_part(part_id, "top_pivot_tapered_wood_leg", [leg_section, leg_height, leg_section], [x, leg_height / 2, z], leg_material, [rx, 0, rz]))
    return parts


def _table_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    name = spec["家具名称"]
    dims = spec["尺寸参数"]
    shape = spec["造型参数"]
    m0, m1 = "material_0", "material_1"
    parts: list[dict[str, Any]]
    if name == "岩板套几（大小两件）":
        large, small = dims["大几"], dims["小几"]
        parts = []
        for prefix, item, x in (("large", large, -170), ("small", small, 260)):
            diameter, height, top = item["直径"], item["高"], item["台面厚"]
            parts.append(_part(f"{prefix}_top", "cylinder", [diameter, top, diameter], [x, height - top / 2, 0], m0))
            leg_radius = diameter * 0.27
            for index, angle in enumerate((0, 120, 240)):
                radians = angle * pi / 180
                parts.append(_part(f"{prefix}_leg_{index + 1}", "tube", [16, height - top, 16], [x + sin(radians) * leg_radius, (height - top) / 2, cos(radians) * leg_radius], m1))
        bounds = (1210, 460, 800)
        frozen = {"双几中心距_mm": 430, "三脚径向内缩比例": 0.24}
    elif name in {"岩板圆形餐桌", "暖白岩板圆餐桌"}:
        diameter, height = _number(dims, "直径"), _number(dims, "高")
        top = _number_or(dims, 30, "台面厚") + _number_or(dims, 0, "基层厚", "岩板厚")
        upper = _number_or(shape, 300, "底座上径")
        lower = _number_or(shape, _number_or(dims, 680, "底座直径"), "底座下径")
        parts = [
            _part("round_top", "cylinder", [diameter, top, diameter], [0, height - top / 2, 0], m0),
            _part("pedestal", "frustum", [lower, height - top, lower], [0, (height - top) / 2, 0], m1, 顶部直径_mm=upper, 底部直径_mm=lower),
            _part("base_ring", "cylinder", [lower, 12, lower], [0, 6, 0], m1),
        ]
        bounds, frozen = (diameter, height, diameter), {"底座上径_mm": upper, "底座下径_mm": lower, "底环厚度_mm": 12}
    elif name == "米白洞石双层茶几":
        length, depth, height = (_number(dims, "长"), _number(dims, "宽"), _number(dims, "高"))
        upper, lower = _number(dims, "上层台面厚"), _number(dims, "下层板厚")
        parts = [
            _part("upper_top", "rounded_tabletop", [length, upper, depth], [0, height - upper / 2, 0], m0, 平面圆角半径_mm=90, 边缘圆角_mm=2),
            _part("lower_shelf", "rounded_tabletop", [length - 150, lower, depth - 120], [0, 105, 0], m0, 平面圆角半径_mm=70, 边缘圆角_mm=2),
        ]
        for part_id, x, z in (("fl", -465, 250), ("fr", 465, 250), ("rl", -465, -250), ("rr", 465, -250)):
            parts.append(_part(f"frame_{part_id}", "rounded_box", [18, height - upper, 18], [x, (height - upper) / 2, z], m1, 圆角_mm=3))
        bounds, frozen = (length, height, depth), {"下层离地_mm": 97, "框架截面_mm": [18, 18]}
    elif name == "烟熏玻璃金属茶几":
        diameter, height, top = _number(dims, "直径"), _number(dims, "高"), _number(dims, "玻璃厚")
        parts = [_part("glass_top", "cylinder", [diameter, top, diameter], [0, height - top / 2, 0], m0)]
        for index, x in enumerate((-260, 0, 260)):
            parts.append(_part(f"arched_support_{index + 1}", "tube", [28, height - top, 28], [x, (height - top) / 2, 0], m1, [0, 0, (-10, 0, 10)[index]]))
        parts.extend([_part("base_ring_x", "tube", [28, diameter * 0.72, 28], [0, 20, 0], m1, [0, 0, 90]), _part("base_ring_z", "tube", [28, diameter * 0.72, 28], [0, 20, 0], m1, [90, 0, 0])])
        bounds, frozen = (diameter, height, diameter), {"弧架数量": 3, "底架展开_mm": diameter * 0.72}
    elif name == "奶油风不规则云朵茶几":
        length, depth, height, top = (_number(dims, "长"), _number(dims, "宽"), _number(dims, "高"), _number(dims, "台面厚"))
        parts = [
            _part("cloud_top", "cloud_tabletop", [length, top, depth], [0, height - top / 2, 0], m0, 边缘圆角_mm=18),
            _part("left_pedestal", "rounded_box", [250, height - top, 310], [-250, (height - top) / 2, 0], m0, 圆角_mm=110),
            _part("right_pedestal", "rounded_box", [300, height - top, 280], [245, (height - top) / 2, 20], m0, 圆角_mm=105),
        ]
        bounds, frozen = (length, height, depth), {"双基座中心距_mm": 495, "基座最小圆角_mm": 105}
    elif name == "黑胡桃椭圆餐桌":
        length, depth, height, top = (_number(dims, "长"), _number(dims, "宽"), _number(dims, "高"), _number(dims, "台面厚"))
        parts = [_part("oval_top", "elliptical_tabletop", [length, top, depth], [0, height - top / 2, 0], m0, 边缘圆角_mm=12)]
        for part_id, x, z, rz in (("fl", -520, 170, -7), ("fr", 520, 170, 7), ("rl", -520, -170, 7), ("rr", 520, -170, -7)):
            parts.append(_part(f"a_frame_{part_id}", "top_pivot_tapered_wood_leg", [70, height - top, 55], [x, (height - top) / 2, z], m0, [0, 0, rz]))
        parts.append(_part("center_beam", "wood_rail", [1050, 70, 55], [0, 300, 0], m0))
        bounds, frozen = (length, height, depth), {"A架外撇角_deg": 7, "中横梁截面_mm": [70, 55]}
    elif name == "可伸缩陶瓷餐桌":
        length, depth, height = (_number(dims, "收起长"), _number(dims, "宽"), _number(dims, "高"))
        top = _number(dims, "陶瓷板厚") + _number(dims, "玻璃基层厚")
        parts = _rect_table_parts(length, depth, height, top, m0, m1, 35, 5)
        parts.append(_part("extension_leaf", "rounded_tabletop", [300, top + 1, depth - 24], [0, height - top / 2 + 1, 0], m0, 平面圆角半径_mm=18, 边缘圆角_mm=3))
        bounds, frozen = (length, height, depth), {"展开长度_mm": _number(dims, "展开长"), "中缝_mm": _number_or(shape, 3, "展开缝隙")}
    else:
        length = _number(dims, "长", "桌板长")
        depth = _number(dims, "宽", "桌板宽")
        height = _number(dims, "高")
        top = _number(dims, "台面厚")
        radius = _number_or(shape, 12, "边缘圆角", "台面圆角")
        splay = _number_or(shape, 2, "桌腿外撇角_deg")
        parts = _rect_table_parts(length, depth, height, top, m0, None, radius, splay)
        bounds, frozen = (length, height, depth), {"桌腿截面_mm": [52, 52], "桌腿内缩_mm": [105, 80]}
    return _base_rule(spec, model_id, "table_v2", bounds, parts, frozen)


def _chair_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    dims, shape = spec["尺寸参数"], spec["造型参数"]
    width, depth, height = _number(dims, "总宽"), _number(dims, "总深"), _number(dims, "总高")
    seat_height, seat_width, seat_depth = _number(dims, "座高"), _number(dims, "座宽"), _number(dims, "座深")
    back_height = height - seat_height + 45
    lean = _number_or(shape, 10, "靠背后倾角_deg")
    name = spec["家具名称"]
    if name == "黑色极简悬臂餐椅":
        parts = [
            _part("seat", "rounded_cushion", [seat_width, 55, seat_depth], [0, seat_height, 15], "material_2"),
            _part("back", "curved_cushion", [seat_width, back_height, 45], [0, seat_height + back_height / 2, -depth / 2 + 40], "material_1", [-lean, 0, 0]),
            _part("left_runner", "tube", [28, depth - 80, 28], [-width / 2 + 36, 18, 10], "material_0", [90, 0, 0]),
            _part("right_runner", "tube", [28, depth - 80, 28], [width / 2 - 36, 18, 10], "material_0", [90, 0, 0]),
            _part("left_riser", "tube", [28, seat_height, 28], [-width / 2 + 36, seat_height / 2, depth / 2 - 55], "material_0"),
            _part("right_riser", "tube", [28, seat_height, 28], [width / 2 - 36, seat_height / 2, depth / 2 - 55], "material_0"),
            _part("front_crossbar", "tube", [28, width - 72, 28], [0, 18, depth / 2 - 55], "material_0", [0, 0, 90]),
            _part("back_crossbar", "tube", [28, width - 72, 28], [0, 18, -depth / 2 + 55], "material_0", [0, 0, 90]),
            _part("seat_support", "rounded_box", [seat_width - 30, 24, seat_depth - 40], [0, seat_height - 42, 15], "material_0", 圆角_mm=5),
        ]
        frozen = {"钢管直径_mm": 28, "座垫厚度_mm": 55, "悬臂回弹行程_mm": 12}
    else:
        frame_slot = _material_slot_for(
            spec,
            surfaces=("wood", "metal"),
            part_words=("木框", "椅腿", "框架"),
        )
        soft_slot = _material_slot_for(
            spec,
            surfaces=("fabric",),
            part_words=("座垫", "软包", "座面"),
            fallback=1,
        )
        rattan_slot = _material_slot_for(
            spec,
            surfaces=("rattan",),
            part_words=("藤编",),
            fallback=1,
        )
        frame_surface = _surface_type(
            spec["材质参数"][int(frame_slot.removeprefix("material_"))]
        )
        rattan_back = any(
            _surface_type(material) == "rattan"
            for material in spec["材质参数"]
        )
        parts = [
            _part("seat", "rounded_cushion", [seat_width, 60, seat_depth], [0, seat_height, 20], soft_slot),
            _part("back", "mesh_panel" if rattan_back else "curved_cushion", [seat_width - 35, back_height, 42], [0, seat_height + back_height / 2 - 12, -depth / 2 + 36], rattan_slot if rattan_back else soft_slot, [-lean, 0, 0], 网格间距_mm=14),
        ]
        leg_x, front_z, rear_z = width / 2 - 42, depth / 2 - 65, -depth / 2 + 55
        leg_geometry = "tapered_wood_leg" if frame_surface == "wood" else "rounded_box"
        rail_geometry = "wood_rail" if frame_surface == "wood" else "rounded_box"
        for part_id, x, z, rx in (("fl", -leg_x, front_z, 0), ("fr", leg_x, front_z, 0), ("rl", -leg_x, rear_z, 6), ("rr", leg_x, rear_z, 6)):
            parts.append(_part(f"leg_{part_id}", leg_geometry, [32, seat_height - 45, 32], [x, (seat_height - 45) / 2, z], frame_slot, [rx, 0, 0], 圆角_mm=5))
        parts.extend([
            _part("left_seat_rail", rail_geometry, [32, 46, seat_depth - 65], [-leg_x, seat_height - 52, 0], frame_slot, 圆角_mm=5),
            _part("right_seat_rail", rail_geometry, [32, 46, seat_depth - 65], [leg_x, seat_height - 52, 0], frame_slot, 圆角_mm=5),
            _part("front_rail", rail_geometry, [width - 84, 46, 32], [0, seat_height - 52, front_z], frame_slot, 圆角_mm=5),
            _part("left_back_post", "tapered_wood_post" if frame_surface == "wood" else "rounded_box", [34, back_height, 34], [-leg_x, seat_height + back_height / 2 - 25, rear_z], frame_slot, [-lean, 0, 0], 圆角_mm=5),
            _part("right_back_post", "tapered_wood_post" if frame_surface == "wood" else "rounded_box", [34, back_height, 34], [leg_x, seat_height + back_height / 2 - 25, rear_z], frame_slot, [-lean, 0, 0], 圆角_mm=5),
        ])
        frozen = {"座垫厚度_mm": 60, "木腿截面_mm": [32, 32], "靠背厚度_mm": 42, "座框横梁高度_mm": 46}
    return _base_rule(spec, model_id, "chair_v2", (width, height, depth), parts, frozen)


def _bed_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    dims, shape = spec["尺寸参数"], spec["造型参数"]
    width = _number(dims, "外框宽", "外宽")
    length = _number(dims, "外框长", "外长")
    bed_height = _number(dims, "床面高")
    head_height = _number(dims, "床头高", "床头总高")
    head_thickness = _number_or(dims, 90, "床头厚")
    mattress = dims.get("适配床垫_mm") or dims.get("适配床垫")
    mattress_width, mattress_length = mattress
    side = max(55, (width - mattress_width) / 2)
    floating = "悬浮" in spec["家具名称"] or "悬浮" in str(spec["结构参数"])
    plinth_inset = _number_or(dims, 190, "悬浮内缩")
    frame_slot = "material_0"
    soft = _surface_type(spec["材质参数"][0]) == "fabric"
    head_slot = "material_1" if len(spec["材质参数"]) > 1 else frame_slot
    mattress_slot = f"material_{len(spec['材质参数'])}"
    parts = [
        _part("left_side_rail", "rounded_box", [side, bed_height, length], [-(width - side) / 2, bed_height / 2, 0], frame_slot, 圆角_mm=18),
        _part("right_side_rail", "rounded_box", [side, bed_height, length], [(width - side) / 2, bed_height / 2, 0], frame_slot, 圆角_mm=18),
        _part("foot_rail", "rounded_box", [width - side * 2, bed_height, 90], [0, bed_height / 2, length / 2 - 45], frame_slot, 圆角_mm=18),
        _part("platform", "rounded_box", [mattress_width, 45, mattress_length], [0, bed_height - 30, 0], frame_slot, 圆角_mm=8),
        _part("mattress", "rounded_cushion", [mattress_width, 180, mattress_length], [0, bed_height + 90, 0], mattress_slot),
        _part("headboard", "curved_cushion" if soft or len(spec["材质参数"]) > 1 else "rounded_box", [width, head_height, head_thickness], [0, head_height / 2, -length / 2 + head_thickness / 2], head_slot, [-_number_or(shape, 4, "床头后倾角_deg"), 0, 0], 圆角_mm=_number_or(shape, 28, "床头圆角", "边缘圆角")),
        _part("floating_plinth", "rounded_box", [width - plinth_inset * 2, max(80, bed_height - 90), length - plinth_inset * 2], [0, max(80, bed_height - 90) / 2, 0], frame_slot, 圆角_mm=8),
    ]
    if spec["家具名称"] == "现代悬浮灯带储物床":
        parts.extend([
            _part("storage_front", "rounded_box", [width - 180, bed_height - 70, 28], [0, (bed_height - 70) / 2, length / 2 - 72], frame_slot, 圆角_mm=5),
            _part("underbed_light", "tube", [12, width - 300, 12], [0, 55, length / 2 - 120], "material_1", [0, 0, 90]),
        ])
    return _base_rule(
        spec,
        model_id,
        "bed_v2",
        (width, head_height, length),
        parts,
        {"床垫厚度_mm": 180, "床框边宽_mm": side, "床头厚度_mm": head_thickness, "悬浮内缩_mm": plinth_inset, "悬浮结构": floating},
        extra_materials=[{
            "部位": "床垫",
            "材质": "暖白针织面料",
            "base_color": "#F1ECE2",
            "roughness": 0.9,
            "metallic": 0,
            "normal_strength": 0.1,
        }],
    )


def _rug_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    dims = spec["尺寸参数"]
    length, width, height = _number(dims, "长"), _number(dims, "宽"), _number(dims, "总厚")
    parts = [
        _part("rug_body", "rug_panel", [length, height, width], [0, height / 2, 0], "material_0", 圆角_mm=18),
        _part("woven_pattern", "rug_panel", [length - 36, 1.2, width - 36], [0, height + 0.6, 0], "material_0", 圆角_mm=14, 图案=spec["造型参数"].get("图案", "纱线肌理")),
    ]
    return _base_rule(spec, model_id, "rug_v2", (length, height + 1.2, width), parts, {"绒高_mm": _number(dims, "绒高"), "包边宽_mm": 18})


def _lamp_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    name, dims = spec["家具名称"], spec["尺寸参数"]
    if name == "奶油白蘑菇落地灯":
        height = _number(dims, "总高")
        base_d, base_h = _number(dims, "底座直径"), _number(dims, "底座高")
        stem_d, shade_d, shade_h = _number(dims, "灯杆直径"), _number(dims, "灯罩直径"), _number(dims, "灯罩高")
        parts = [
            _part("base", "cylinder", [base_d, base_h, base_d], [0, base_h / 2, 0], "material_0"),
            _part("stem", "tube", [stem_d, height - shade_h - base_h, stem_d], [0, base_h + (height - shade_h - base_h) / 2, 0], "material_0"),
            _part("mushroom_shade", "frustum", [shade_d, shade_h, shade_d], [0, height - shade_h / 2, 0], "material_1", 顶部直径_mm=shade_d * 0.34, 底部直径_mm=shade_d),
        ]
        bounds, install, frozen = (shade_d, height, shade_d), "floor", {"灯罩顶部直径_mm": shade_d * 0.34}
    elif name == "纸艺吊线床头灯（一对）":
        shade_d, shade_h = _number(dims, "单灯灯罩直径"), _number(dims, "灯罩高")
        suspension = _pair(dims, "吊线可调范围")[1]
        parts = [_part("ceiling_plate", "cylinder", [420, 24, 140], [0, suspension + shade_h + 12, 0], "material_1")]
        for index, x in enumerate((-210, 210)):
            parts.extend([
                _part(f"cord_{index + 1}", "tube", [6, suspension, 6], [x, shade_h + suspension / 2, 0], "material_1"),
                _part(f"paper_shade_{index + 1}", "frustum", [shade_d, shade_h, shade_d], [x, shade_h / 2, 0], "material_0", 顶部直径_mm=shade_d * 0.55, 底部直径_mm=_number_or(spec["造型参数"], shade_d * 0.74, "下口直径")),
            ])
        bounds, install, frozen = (shade_d * 2.4, suspension + shade_h + 24, shade_d), "ceiling", {"双灯中心距_mm": 420, "展示吊线长度_mm": suspension}
    else:
        diameter, body_h = _number(dims, "灯体直径"), _number(dims, "灯体高")
        suspension = _pair(dims, "吊线可调")[1]
        parts = [
            _part("ceiling_plate", "cylinder", [_number(dims, "吸顶盘直径"), 24, _number(dims, "吸顶盘直径")], [0, suspension + body_h + 12, 0], "material_0"),
            _part("main_cord", "tube", [7, suspension, 7], [0, body_h + suspension / 2, 0], "material_0"),
            _part("brass_ring", "torus", [diameter, 22, diameter], [0, body_h * 0.55, 0], "material_0"),
        ]
        for index in range(6):
            angle = index * pi / 3
            ring_radius = diameter / 2 - 76
            x = sin(angle) * ring_radius
            z = cos(angle) * ring_radius
            parts.append(_part(f"glass_globe_{index + 1}", "sphere", [130, 130, 130], [x, body_h * 0.55, z], "material_1"))
        bounds, install, frozen = (diameter, suspension + body_h + 24, diameter), "ceiling", {"玻璃灯罩数量": 6, "展示吊线长度_mm": suspension}
    preview = None
    if install == "ceiling":
        preview = {
            "中心_mm": [0, (shade_h if name == "纸艺吊线床头灯（一对）" else body_h) / 2, 0],
            "半径_mm": (shade_d * 2.4 if name == "纸艺吊线床头灯（一对）" else diameter) * 0.62,
        }
    return _base_rule(spec, model_id, "lamp_v2", bounds, parts, frozen, install, preview=preview)


def _curtain_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    dims = spec["尺寸参数"]
    panel_width, height = _number(dims, "单片参考宽"), _number(dims, "参考高")
    depth = _number_or(spec["造型参数"], 110, "褶皱间距")
    gap = 28
    parts = [
        _part("left_panel", "curtain_panel", [panel_width, height, depth], [-panel_width / 2 - gap / 2, height / 2 + _number(dims, "离地"), 0], "material_0", 褶皱周期_mm=depth),
        _part("right_panel", "curtain_panel", [panel_width, height, depth], [panel_width / 2 + gap / 2, height / 2 + _number(dims, "离地"), 0], "material_0", 褶皱周期_mm=depth),
        _part("curtain_rod", "tube", [28, panel_width * 2 + 180, 28], [0, height + 42, 0], "material_0", [0, 0, 90]),
    ]
    return _base_rule(spec, model_id, "curtain_v2", (panel_width * 2 + gap, height + 56, depth), parts, {"中缝_mm": gap, "褶皱周期_mm": depth, "褶皱倍率": _number(dims, "褶皱倍率")}, "wall")


def _cabinet_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    dims = spec["尺寸参数"]
    width, depth, height = _number(dims, "宽"), _number(dims, "深"), _number(dims, "高")
    panel, leg_height = _number(dims, "柜体板厚"), _number(dims, "腿高")
    body_h = height - leg_height
    parts = [
        _part("top", "rounded_box", [width, panel, depth], [0, height - panel / 2, 0], "material_0", 圆角_mm=8),
        _part("bottom", "rounded_box", [width, panel, depth], [0, leg_height + panel / 2, 0], "material_0", 圆角_mm=5),
        _part("left_side", "rounded_box", [panel, body_h, depth], [-width / 2 + panel / 2, leg_height + body_h / 2, 0], "material_0", 圆角_mm=5),
        _part("right_side", "rounded_box", [panel, body_h, depth], [width / 2 - panel / 2, leg_height + body_h / 2, 0], "material_0", 圆角_mm=5),
        _part("drawer_front", "rounded_box", [width - panel * 2 - 8, 125, 22], [0, height - panel - 67, depth / 2 - 11], "material_0", 圆角_mm=7),
        _part("rattan_door", "mesh_panel", [width - panel * 2 - 8, body_h - 168, 20], [0, leg_height + (body_h - 168) / 2 + panel, depth / 2 - 10], "material_1", 网格间距_mm=18),
    ]
    for part_id, x, z in (("fl", -width / 2 + 42, depth / 2 - 42), ("fr", width / 2 - 42, depth / 2 - 42), ("rl", -width / 2 + 42, -depth / 2 + 42), ("rr", width / 2 - 42, -depth / 2 + 42)):
        parts.append(_part(f"leg_{part_id}", "tapered_wood_leg", [28, leg_height, 28], [x, leg_height / 2, z], "material_0"))
    return _base_rule(spec, model_id, "cabinet_v2", (width, height, depth), parts, {"背板厚度_mm": 9, "抽屉面高度_mm": 125, "藤编网格间距_mm": 18})


def _desk_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    dims = spec["尺寸参数"]
    length, depth, top = _number(dims, "桌板长"), _number(dims, "桌板宽"), _number(dims, "桌板厚")
    low, high = _pair(dims, "升降高度")
    display_height = (low + high) / 2
    frame_width, foot_length = _number(dims, "腿架外宽"), _number(dims, "脚掌长")
    parts = [_part("desktop", "rounded_tabletop", [length, top, depth], [0, display_height - top / 2, 0], "material_0", 平面圆角半径_mm=24, 边缘圆角_mm=10)]
    for side, x in (("left", -frame_width / 2), ("right", frame_width / 2)):
        parts.extend([
            _part(f"{side}_outer_column", "rounded_box", [70, 430, 70], [x, 215, 0], "material_1", 圆角_mm=6),
            _part(f"{side}_inner_column", "rounded_box", [54, display_height - top - 390, 54], [x, 430 + (display_height - top - 390) / 2, 0], "material_1", 圆角_mm=5),
            _part(f"{side}_foot", "rounded_box", [90, 28, foot_length], [x, 14, 0], "material_1", 圆角_mm=9),
        ])
    parts.extend([
        _part("crossbar", "rounded_box", [frame_width, 54, 44], [0, 410, 0], "material_1", 圆角_mm=5),
        _part("controller", "rounded_box", [120, 24, 46], [length / 2 - 110, display_height - top - 18, depth / 2 - 42], "material_1", 圆角_mm=6),
    ])
    return _base_rule(spec, model_id, "desk_v2", (length, high, depth), parts, {"展示高度_mm": display_height, "升降下限_mm": low, "升降上限_mm": high, "外柱截面_mm": [70, 70], "内柱截面_mm": [54, 54]})


def _shelf_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    dims = spec["尺寸参数"]
    width, depth, height = _number(dims, "宽"), _number(dims, "深"), _number(dims, "高")
    count, shelf_t = int(_number(dims, "层数")), _number(dims, "层板厚")
    post = _pair(dims, "立柱截面")
    parts = []
    for index in range(count):
        y = shelf_t / 2 + index * (height - shelf_t) / (count - 1)
        parts.append(_part(f"shelf_{index + 1}", "rounded_box", [width, shelf_t, depth], [0, y, 0], "material_0", 圆角_mm=3))
    for part_id, x, z in (("fl", -width / 2 + post[0] / 2, depth / 2 - post[1] / 2), ("fr", width / 2 - post[0] / 2, depth / 2 - post[1] / 2), ("rl", -width / 2 + post[0] / 2, -depth / 2 + post[1] / 2), ("rr", width / 2 - post[0] / 2, -depth / 2 + post[1] / 2)):
        parts.append(_part(f"post_{part_id}", "wood_rail", [post[0], height, post[1]], [x, height / 2, z], "material_0"))
    brace_length = (width ** 2 + height ** 2) ** 0.5
    angle = 90 - __import__("math").degrees(__import__("math").atan2(height, width))
    parts.extend([
        _part("rear_brace_left", "tube", [18, brace_length, 18], [0, height / 2, -depth / 2 + 12], "material_1", [0, 0, angle]),
        _part("rear_brace_right", "tube", [18, brace_length, 18], [0, height / 2, -depth / 2 + 12], "material_1", [0, 0, -angle]),
    ])
    return _base_rule(spec, model_id, "shelf_v2", (width, height, depth), parts, {"层板数量": count, "背拉杆直径_mm": 18, "层板厚度_mm": shelf_t})


def _ergonomic_chair_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    dims = spec["尺寸参数"]
    width, depth = _number(dims, "总宽"), _number(dims, "总深")
    height = _pair(dims, "总高范围")[0]
    seat_height = _pair(dims, "座高范围")[0]
    seat_width = _number(dims, "座宽")
    seat_depth = _pair(dims, "座深可调")[0]
    parts = [
        _part("seat", "mesh_panel", [seat_width, 65, seat_depth], [0, seat_height, 30], "material_0", 圆角_mm=32, 网格间距_mm=8),
        _part("back_frame", "mesh_panel", [seat_width - 30, 560, 55], [0, seat_height + 300, -depth / 2 + 40], "material_1", [-8, 0, 0], 网格间距_mm=9),
        _part("headrest", "mesh_panel", [_number(dims, "头枕宽"), 120, 45], [0, height - 60, -depth / 2 + 35], "material_0", [-10, 0, 0], 网格间距_mm=8),
        _part("gas_lift", "cylinder", [48, seat_height - 175, 48], [0, (seat_height - 175) / 2 + 95, 0], "material_2"),
        _part("hub", "cylinder", [92, 52, 92], [0, 76, 0], "material_2"),
    ]
    for index, angle in enumerate((0, 72, 144, 216, 288)):
        radians = angle * pi / 180
        spoke_x = sin(radians) * 150
        spoke_z = cos(radians) * 150
        caster_x = sin(radians) * 300
        caster_z = cos(radians) * 300
        parts.extend([
            _part(f"star_spoke_{index + 1}", "tube", [34, 300, 34], [spoke_x, 62, spoke_z], "material_2", [90, angle, 0]),
            _part(f"caster_{index + 1}", "cylinder", [54, 22, 54], [caster_x, 30, caster_z], "material_1", [90, angle, 0]),
        ])
    for side, x in (("left", -width / 2 + 70), ("right", width / 2 - 70)):
        parts.extend([
            _part(f"{side}_arm_support", "rounded_box", [36, 170, 42], [x, seat_height + 85, 0], "material_1", 圆角_mm=12),
            _part(f"{side}_arm_pad", "rounded_box", [78, 28, 220], [x, seat_height + 184, 18], "material_1", 圆角_mm=13),
        ])
    return _base_rule(spec, model_id, "ergonomic_chair_v2", (width, height, depth), parts, {"展示座高_mm": seat_height, "五星脚辐条长度_mm": 300, "网布网格_mm": 8, "气压杆直径_mm": 48})


COMPILERS: tuple[tuple[Callable[[str], bool], Callable[[dict[str, Any], str], dict[str, Any]]], ...] = (
    (lambda furniture_type: "沙发" in furniture_type, _sofa_rule),
    (lambda furniture_type: "茶几" in furniture_type or "套几" in furniture_type or "餐桌" in furniture_type, _table_rule),
    (lambda furniture_type: furniture_type == "人体工学椅", _ergonomic_chair_rule),
    (lambda furniture_type: "椅" in furniture_type, _chair_rule),
    (lambda furniture_type: "床头柜" in furniture_type, _cabinet_rule),
    (lambda furniture_type: "灯" in furniture_type, _lamp_rule),
    (lambda furniture_type: "床" in furniture_type, _bed_rule),
    (lambda furniture_type: "地毯" in furniture_type, _rug_rule),
    (lambda furniture_type: "窗帘" in furniture_type, _curtain_rule),
    (lambda furniture_type: "书桌" in furniture_type, _desk_rule),
    (lambda furniture_type: "书架" in furniture_type or "书柜" in furniture_type, _shelf_rule),
)


def compile_furniture_family_rule(spec: dict[str, Any], model_id: str) -> dict[str, Any]:
    """根据显式家具类型选择结构族，并产出无运行时默认值的部件规则。"""
    furniture_type = spec.get("家具类型")
    if not isinstance(furniture_type, str):
        raise FurnitureFamilyRuleError("家具类型必须为文本")
    for matches, compiler in COMPILERS:
        if matches(furniture_type):
            return compiler(spec, model_id)
    raise FurnitureFamilyRuleError(f"没有结构族编译器：{furniture_type}")
