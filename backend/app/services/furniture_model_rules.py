"""家具确定性建模规则的合并、编译与完整性校验。"""

from __future__ import annotations

from copy import deepcopy
from math import cos, radians, sin
from typing import Any


class FurnitureRuleError(ValueError):
    """建模源数据缺失、冲突或规则不完整。"""


SAMPLE_FURNITURE_NAME = "中古风绒布单人椅"
SAMPLE_MODEL_ID = "HAUS-CHAIR-001"


def build_deterministic_rule_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """为统一目录建立稳定模型 ID，并登记规则完成状态。"""
    items = catalog.get("家具列表")
    if not isinstance(items, list):
        raise FurnitureRuleError("统一目录缺少家具列表")

    model_entries: list[dict[str, Any]] = []
    prefix_counters: dict[str, int] = {}
    used_model_ids = {SAMPLE_MODEL_ID}

    for item in items:
        name = _require_text(item, "家具名称")
        furniture_type = _require_text(item, "家具类型")
        if name == SAMPLE_FURNITURE_NAME:
            rule = compile_lounge_chair_rule(item)
            model_entries.append(
                {
                    "模型ID": SAMPLE_MODEL_ID,
                    "家具名称": name,
                    "家具类型": furniture_type,
                    "数据批次": item.get("数据批次"),
                    "规则状态": "ready",
                    "确定性规则": rule,
                }
            )
            continue

        prefix = _model_id_prefix(furniture_type)
        sequence = prefix_counters.get(prefix, 0) + 1
        model_id = f"HAUS-{prefix}-{sequence:03d}"
        while model_id in used_model_ids:
            sequence += 1
            model_id = f"HAUS-{prefix}-{sequence:03d}"
        prefix_counters[prefix] = sequence
        used_model_ids.add(model_id)
        model_entries.append(
            {
                "模型ID": model_id,
                "家具名称": name,
                "家具类型": furniture_type,
                "数据批次": item.get("数据批次"),
                "规则状态": "pending",
                "待完善内容": [
                    "部件尺寸与空间变换",
                    "材质槽与部件绑定",
                    "设计冻结值",
                    "模型质量规则",
                ],
            }
        )

    ready_count = sum(item["规则状态"] == "ready" for item in model_entries)
    return {
        "文件说明": "40 款家具的确定性建模规则目录；pending 项不得进入正式模型生产。",
        "规则库版本": "1.0.0",
        "家具数量": len(model_entries),
        "已完成规则数量": ready_count,
        "待完善规则数量": len(model_entries) - ready_count,
        "模型目录": model_entries,
    }


def merge_furniture_catalogs(
    catalogs: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """合并多个家具参数批次，并统一公共字段。"""
    merged_items: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for batch_name, catalog in catalogs:
        items = catalog.get("家具列表")
        if not isinstance(items, list):
            raise FurnitureRuleError(f"{batch_name} 缺少家具列表")

        for source_item in items:
            item = deepcopy(source_item)
            name = item.get("家具名称")
            if not isinstance(name, str) or not name.strip():
                raise FurnitureRuleError(f"{batch_name} 存在没有家具名称的数据")
            if name in seen_names:
                raise FurnitureRuleError(f"发现重复家具名称：{name}")

            space = item.get("空间") or item.get("适用空间")
            if not isinstance(space, str) or not space.strip():
                raise FurnitureRuleError(f"{name} 缺少空间信息")

            item["空间"] = space
            item.pop("适用空间", None)
            item["数据批次"] = batch_name
            seen_names.add(name)
            merged_items.append(item)

    return {
        "文件说明": "项目家具 3D 参数统一目录；原始参数保持不变，仅统一公共字段。",
        "版本": "2.0",
        "家具数量": len(merged_items),
        "家具列表": merged_items,
    }


def _model_id_prefix(furniture_type: str) -> str:
    if "沙发" in furniture_type:
        return "SOFA"
    if "椅" in furniture_type:
        return "CHAIR"
    if "茶几" in furniture_type or "套几" in furniture_type:
        return "COFFEE"
    if "餐桌" in furniture_type:
        return "DINING"
    if "书桌" in furniture_type:
        return "DESK"
    if "床头柜" in furniture_type:
        return "NIGHTSTAND"
    if "床" in furniture_type:
        return "BED"
    if "灯" in furniture_type:
        return "LAMP"
    if "地毯" in furniture_type:
        return "RUG"
    if "窗帘" in furniture_type:
        return "CURTAIN"
    if "书架" in furniture_type or "书柜" in furniture_type:
        return "SHELF"
    raise FurnitureRuleError(f"没有模型 ID 分类规则：{furniture_type}")


def compile_lounge_chair_rule(spec: dict[str, Any]) -> dict[str, Any]:
    """把中古风绒布单人椅编译为不依赖运行时默认值的规则。"""
    name = _require_text(spec, "家具名称")
    if name != "中古风绒布单人椅":
        raise FurnitureRuleError(f"当前样板编译器不支持：{name}")

    dimensions = _require_mapping(spec, "尺寸参数")
    structure = _require_mapping(spec, "结构参数")
    shape = _require_mapping(spec, "造型参数")
    materials = _require_list(spec, "材质参数")
    mesh = _require_mapping(spec, "网格与贴图")

    width = _require_number(dimensions, "总宽")
    depth = _require_number(dimensions, "总深")
    height = _require_number(dimensions, "总高")
    seat_width = _require_number(dimensions, "座宽")
    seat_depth = _require_number(dimensions, "座深")
    seat_height = _require_number(dimensions, "座高")
    arm_height = _require_number(dimensions, "扶手高")
    arm_profile = _require_number_pair(shape, "扶手截面")
    back_lean = _require_number(structure, "靠背后倾角_deg")
    rear_leg_lean = _require_number(structure, "后腿后倾角_deg")

    # 原始数据没有以下加工尺寸。作为 1.0 样板的设计冻结值显式保存，
    # 后续只能通过规则版本升级修改，渲染端不得另设默认值。
    seat_thickness = 90
    back_thickness = 85
    leg_section = 32
    leg_height = seat_height - seat_thickness
    # 座框以模型原点为中心；总深度只用于相机/碰撞包围盒，不能直接拿来
    # 把座面推到最前端，否则座面与靠背会产生结构断裂。
    seat_center_z = 0
    back_height = height - seat_height

    material_slots = [
        _material_slot(materials, 0, "upholstery"),
        _material_slot(materials, 1, "wood_frame"),
    ]

    parts = [
        _part(
            "seat_cushion",
            "rounded_cushion",
            [seat_width, seat_thickness, seat_depth],
            [0, seat_height - seat_thickness / 2, seat_center_z],
            [0, 0, 0],
            "upholstery",
        ),
        _part(
            "back_cushion",
            "curved_cushion",
            [seat_width, back_height, back_thickness],
            [
                0,
                seat_height + back_height / 2,
                -seat_depth / 2 + back_thickness / 2,
            ],
            [-back_lean, 0, 0],
            "upholstery",
        ),
        _part(
            "left_arm",
            "wood_rail",
            [arm_profile[0], arm_profile[1], seat_depth],
            [
                -width / 2 + arm_profile[0] / 2,
                arm_height - arm_profile[1] / 2,
                seat_center_z,
            ],
            [0, 0, 0],
            "wood_frame",
        ),
        _part(
            "right_arm",
            "wood_rail",
            [arm_profile[0], arm_profile[1], seat_depth],
            [
                width / 2 - arm_profile[0] / 2,
                arm_height - arm_profile[1] / 2,
                seat_center_z,
            ],
            [0, 0, 0],
            "wood_frame",
        ),
    ]

    rail_height = arm_profile[1]
    rail_center_y = leg_height - rail_height / 2
    frame_width = width - leg_section * 2
    frame_depth = seat_depth - leg_section * 2
    frame_front_z = seat_center_z + seat_depth / 2 - leg_section / 2
    frame_rear_z = seat_center_z - seat_depth / 2 + leg_section / 2
    parts.extend(
        [
            _part(
                "front_seat_rail",
                "wood_rail",
                [frame_width, rail_height, leg_section],
                [0, rail_center_y, frame_front_z],
                [0, 0, 0],
                "wood_frame",
            ),
            _part(
                "rear_seat_rail",
                "wood_rail",
                [frame_width, rail_height, leg_section],
                [0, rail_center_y, frame_rear_z],
                [0, 0, 0],
                "wood_frame",
            ),
            _part(
                "left_seat_rail",
                "wood_rail",
                [leg_section, rail_height, frame_depth],
                [-width / 2 + leg_section / 2, rail_center_y, seat_center_z],
                [0, 0, 0],
                "wood_frame",
            ),
            _part(
                "right_seat_rail",
                "wood_rail",
                [leg_section, rail_height, frame_depth],
                [width / 2 - leg_section / 2, rail_center_y, seat_center_z],
                [0, 0, 0],
                "wood_frame",
            ),
        ]
    )

    leg_x = width / 2 - leg_section / 2
    front_z = frame_front_z
    rear_z = frame_rear_z
    front_leg_height = arm_height - arm_profile[1]
    for part_id, x, z, part_height, lean in [
        ("front_left_leg", -leg_x, front_z, front_leg_height, 0),
        ("front_right_leg", leg_x, front_z, front_leg_height, 0),
        ("rear_left_leg", -leg_x, rear_z, leg_height, rear_leg_lean),
        ("rear_right_leg", leg_x, rear_z, leg_height, rear_leg_lean),
    ]:
        parts.append(
            _part(
                part_id,
                "tapered_wood_leg",
                [leg_section, part_height, leg_section],
                [x, part_height / 2, z],
                [lean, 0, 0],
                "wood_frame",
            )
        )

    back_post_height = height - leg_height
    rear_leg_angle = radians(rear_leg_lean)
    rear_leg_top_y = leg_height * cos(rear_leg_angle)
    rear_leg_top_z = rear_z + leg_height * sin(rear_leg_angle)
    for part_id, x in [
        ("left_back_post", -leg_x),
        ("right_back_post", leg_x),
    ]:
        parts.append(
            _part(
                part_id,
                "tapered_wood_post",
                [leg_section, back_post_height, leg_section],
                [x, rear_leg_top_y + back_post_height / 2, rear_leg_top_z],
                [-back_lean, 0, 0],
                "wood_frame",
            )
        )

    craft = _require_mapping(spec, "工艺细节")
    upholstery_material = material_slots[0]
    wood_material = material_slots[1]
    appearance_rules = {
        "软包": {
            "滚边": {
                "启用": craft.get("软包滚边") is True,
                "直径_mm": 7,
            },
            "缝线": {
                "启用": True,
                "线径_mm": 1.4,
                "内缩_mm": 10,
            },
            "绒面": {
                "方向性": craft.get("绒面方向性") is True,
                "法线强度": _require_number(upholstery_material, "normal_strength"),
                "纹理周期_mm": 3,
            },
            "坐垫形变": {
                "前缘压缩": _require_number(craft, "坐垫前缘压缩"),
                "中心隆起_mm": 10,
            },
            "靠背曲面": {
                "横向弧度半径_mm": _require_number(shape, "靠背横向弧度半径"),
            },
        },
        "木材": {
            "树种": _require_text(wood_material, "材质"),
            "纹理周期_mm": 42,
            "法线强度": _require_number(wood_material, "normal_strength"),
            "透明面漆": {"强度": 0.14, "粗糙度": 0.62},
            "榫卯节点": {
                "启用": "榫卯" in _require_text(craft, "木连接"),
                "榫肩线宽_mm": 1.2,
                "距构件端部_mm": 18,
            },
        },
    }

    rule = {
        "规则版本": "1.2.0",
        "规则状态": "ready",
        "模型ID": "HAUS-CHAIR-001",
        "家具名称": name,
        "家具类型": _require_text(spec, "家具类型"),
        "生成器": "lounge_chair_v1",
        "坐标系统": {
            "单位": "mm",
            "上轴": "Y",
            "前向": "+Z",
            "原点": "floor_center",
        },
        "包围尺寸_mm": {"宽": width, "高": height, "深": depth},
        "几何规则": {
            "座位数": 1,
            "座垫": {
                "尺寸_mm": [seat_width, seat_thickness, seat_depth],
                "圆角_mm": 38,
                "前缘压缩": _require_number(
                    _require_mapping(spec, "工艺细节"), "坐垫前缘压缩"
                ),
            },
            "靠背": {
                "尺寸_mm": [seat_width, back_height, back_thickness],
                "后倾角_deg": back_lean,
                "横向弧度半径_mm": _require_number(shape, "靠背横向弧度半径"),
            },
            "木扶手": {"截面_mm": arm_profile, "顶面高_mm": arm_height},
            "木腿": {
                "截面_mm": [leg_section, leg_section],
                "前腿高度_mm": front_leg_height,
                "后腿下段高度_mm": leg_height,
                "后腿后倾角_deg": rear_leg_lean,
                "前腿渐缩": bool(shape.get("前腿渐缩")),
            },
            "木框连接": {
                "连接方式": _require_text(
                    _require_mapping(spec, "工艺细节"), "木连接"
                ),
                "座下横梁截面_mm": [leg_section, rail_height],
                "靠背立柱截面_mm": [leg_section, leg_section],
            },
        },
        "外观规则": appearance_rules,
        "材质槽": material_slots,
        "部件": parts,
        "质量规则": {
            "目标三角面": _require_number(mesh, "目标三角面"),
            "需要UV": mesh.get("UV") is True,
            "贴图分辨率": _require_text(mesh, "贴图分辨率"),
            "LOD": deepcopy(mesh.get("LOD")),
        },
        "设计冻结": {
            "座垫厚度_mm": seat_thickness,
            "靠背厚度_mm": back_thickness,
            "木腿截面_mm": [leg_section, leg_section],
            "座框中心Z_mm": seat_center_z,
            "软包滚边直径_mm": 7,
            "软包缝线线径_mm": 1.4,
            "软包缝线内缩_mm": 10,
            "绒面纹理周期_mm": 3,
            "坐垫中心隆起_mm": 10,
            "木纹周期_mm": 42,
            "木材透明面漆强度": 0.14,
            "木材透明面漆粗糙度": 0.62,
            "榫肩线宽_mm": 1.2,
            "榫肩线距构件端部_mm": 18,
            "说明": "原始参数未给出的加工尺寸；经样板设计明确后冻结。",
        },
    }
    validate_deterministic_rule(rule)
    return rule


def validate_deterministic_rule(rule: dict[str, Any]) -> None:
    """校验规则能否在没有隐式默认值的情况下交给模型生成器。"""
    required_keys = {
        "规则版本",
        "规则状态",
        "模型ID",
        "家具名称",
        "生成器",
        "坐标系统",
        "包围尺寸_mm",
        "几何规则",
        "外观规则",
        "材质槽",
        "部件",
        "质量规则",
    }
    missing = required_keys - rule.keys()
    if missing:
        raise FurnitureRuleError(f"规则缺少字段：{sorted(missing)}")

    bounds = _require_mapping(rule, "包围尺寸_mm")
    for key in ("宽", "高", "深"):
        if _require_number(bounds, key) <= 0:
            raise FurnitureRuleError(f"包围尺寸必须大于 0：{key}")

    material_slots = _require_list(rule, "材质槽")
    material_ids = {_require_text(slot, "槽位ID") for slot in material_slots}
    if len(material_ids) != len(material_slots):
        raise FurnitureRuleError("材质槽位 ID 重复")

    parts = _require_list(rule, "部件")
    part_ids: set[str] = set()
    for part in parts:
        part_id = _require_text(part, "部件ID")
        if part_id in part_ids:
            raise FurnitureRuleError(f"部件 ID 重复：{part_id}")
        part_ids.add(part_id)

        material_id = _require_text(part, "材质槽")
        if material_id not in material_ids:
            raise FurnitureRuleError(f"部件引用未知材质槽：{material_id}")
        for vector_key in ("尺寸_mm", "位置_mm", "旋转_deg"):
            vector = part.get(vector_key)
            if not isinstance(vector, list) or len(vector) != 3:
                raise FurnitureRuleError(f"{part_id} 的 {vector_key} 必须为三维数组")
        if any(not isinstance(value, (int, float)) or value <= 0 for value in part["尺寸_mm"]):
            raise FurnitureRuleError(f"{part_id} 的尺寸必须全部大于 0")

    appearance = _require_mapping(rule, "外观规则")
    upholstery = _require_mapping(appearance, "软包")
    for detail_key in ("滚边", "缝线", "绒面", "坐垫形变", "靠背曲面"):
        _require_mapping(upholstery, detail_key)
    wood = _require_mapping(appearance, "木材")
    _require_mapping(wood, "透明面漆")
    _require_mapping(wood, "榫卯节点")


def _part(
    part_id: str,
    geometry: str,
    size: list[float],
    position: list[float],
    rotation: list[float],
    material_slot: str,
) -> dict[str, Any]:
    return {
        "部件ID": part_id,
        "几何": geometry,
        "尺寸_mm": size,
        "位置_mm": position,
        "旋转_deg": rotation,
        "材质槽": material_slot,
    }


def _material_slot(
    materials: list[Any], index: int, slot_id: str
) -> dict[str, Any]:
    try:
        material = deepcopy(materials[index])
    except IndexError as exc:
        raise FurnitureRuleError(f"缺少材质槽：{slot_id}") from exc
    if not isinstance(material, dict):
        raise FurnitureRuleError(f"材质槽格式错误：{slot_id}")
    material["槽位ID"] = slot_id
    return material


def _require_mapping(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    if not isinstance(value, dict):
        raise FurnitureRuleError(f"缺少对象字段：{key}")
    return value


def _require_list(container: dict[str, Any], key: str) -> list[Any]:
    value = container.get(key)
    if not isinstance(value, list) or not value:
        raise FurnitureRuleError(f"缺少数组字段：{key}")
    return value


def _require_text(container: dict[str, Any], key: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FurnitureRuleError(f"缺少文本字段：{key}")
    return value


def _require_number(container: dict[str, Any], key: str) -> float:
    value = container.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FurnitureRuleError(f"缺少数值字段：{key}")
    return value


def _require_number_pair(container: dict[str, Any], key: str) -> list[float]:
    value = container.get(key)
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(item, (int, float)) for item in value)
    ):
        raise FurnitureRuleError(f"字段必须为两个数值：{key}")
    return value
