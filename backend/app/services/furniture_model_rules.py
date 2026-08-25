"""家具确定性建模规则的合并、编译与完整性校验。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class FurnitureRuleError(ValueError):
    """建模源数据缺失、冲突或规则不完整。"""


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
    seat_center_z = (depth - seat_depth) / 2
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
            [0, seat_height + back_height / 2, -depth / 2 + back_thickness / 2],
            [-back_lean, 0, 0],
            "upholstery",
        ),
        _part(
            "left_arm",
            "wood_rail",
            [arm_profile[0], arm_profile[1], seat_depth],
            [-width / 2 + arm_profile[0] / 2, arm_height, seat_center_z],
            [0, 0, 0],
            "wood_frame",
        ),
        _part(
            "right_arm",
            "wood_rail",
            [arm_profile[0], arm_profile[1], seat_depth],
            [width / 2 - arm_profile[0] / 2, arm_height, seat_center_z],
            [0, 0, 0],
            "wood_frame",
        ),
    ]

    leg_x = width / 2 - leg_section / 2
    front_z = depth / 2 - leg_section / 2
    rear_z = -depth / 2 + leg_section / 2
    for part_id, x, z, lean in [
        ("front_left_leg", -leg_x, front_z, 0),
        ("front_right_leg", leg_x, front_z, 0),
        ("rear_left_leg", -leg_x, rear_z, -rear_leg_lean),
        ("rear_right_leg", leg_x, rear_z, -rear_leg_lean),
    ]:
        parts.append(
            _part(
                part_id,
                "tapered_wood_leg",
                [leg_section, leg_height, leg_section],
                [x, leg_height / 2, z],
                [lean, 0, 0],
                "wood_frame",
            )
        )

    rule = {
        "规则版本": "1.0.0",
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
            "木扶手": {"截面_mm": arm_profile, "中心高_mm": arm_height},
            "木腿": {
                "截面_mm": [leg_section, leg_section],
                "高度_mm": leg_height,
                "后腿后倾角_deg": rear_leg_lean,
                "前腿渐缩": bool(shape.get("前腿渐缩")),
            },
        },
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
