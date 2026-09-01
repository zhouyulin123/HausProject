"""定制家具参数化预览：严格校验输入、生成确定性几何并复算规则报价。"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CustomQuoteRule
from app.schemas.custom_furniture import (
    CabinetSpec,
    CustomFurniturePreviewResult,
    CustomFurnitureQuotePreview,
    CustomFurnitureSpec,
    TableSpec,
)
from app.services.furniture_model_rules import validate_deterministic_rule


PURPOSE_PROJECT_NAMES = {
    "wardrobe": "定制衣柜",
    "entryway_cabinet": "玄关柜",
    "bookcase": "书柜",
    "balcony_storage": "阳台储物柜",
    "dining_table": "定制餐桌",
    "desk": "定制书桌",
    "kitchen_island": "岛台",
}

MATERIAL_APPEARANCE = {
    "E0 颗粒板": ("wood", "#CDBB9E", 0.72, 0.0),
    "多层实木": ("wood", "#A9794F", 0.64, 0.0),
    "实木（橡木）": ("wood", "#B98B5B", 0.58, 0.0),
    "E0 颗粒板（防潮封边）": ("wood", "#C3B394", 0.7, 0.0),
    "岩板 + 金属": ("stone", "#D8D4CA", 0.38, 0.05),
    "多层实木 + 岩板台面": ("stone", "#D1CEC5", 0.42, 0.02),
}


def _stable_model_id(spec: CustomFurnitureSpec) -> str:
    canonical = json.dumps(
        spec.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()[:12].upper()
    return f"CUSTOM-{spec.family.upper()}-{digest}"


def _part(
    part_id: str,
    geometry: str,
    size: list[float],
    position: list[float],
    material_slot: str,
    rotation: list[float] | None = None,
    **details: Any,
) -> dict[str, Any]:
    return {
        "部件ID": part_id,
        "几何": geometry,
        "尺寸_mm": [round(value, 4) for value in size],
        "位置_mm": [round(value, 4) for value in position],
        "旋转_deg": rotation or [0, 0, 0],
        "材质槽": material_slot,
        **details,
    }


def _material_slots(spec: CustomFurnitureSpec) -> list[dict[str, Any]]:
    surface, color, roughness, metallic = MATERIAL_APPEARANCE[spec.material]
    slots = [
        {
            "槽位ID": "primary",
            "部位": "主体",
            "材质": spec.material,
            "表面类型": surface,
            "base_color": color,
            "roughness": roughness,
            "metallic": metallic,
            "normal_strength": 0.12,
        }
    ]
    if spec.material == "岩板 + 金属":
        slots.append(
            {
                "槽位ID": "base",
                "部位": "桌架",
                "材质": "金属",
                "表面类型": "metal",
                "base_color": "#393A3C",
                "roughness": 0.34,
                "metallic": 0.82,
                "normal_strength": 0.04,
            }
        )
    elif spec.material == "多层实木 + 岩板台面":
        slots.append(
            {
                "槽位ID": "base",
                "部位": "桌架",
                "材质": "多层实木",
                "表面类型": "wood",
                "base_color": "#9E714B",
                "roughness": 0.62,
                "metallic": 0.0,
                "normal_strength": 0.12,
            }
        )
    return slots


def _appearance(slots: list[dict[str, Any]]) -> dict[str, Any]:
    wood = next(
        (slot for slot in slots if slot["表面类型"] == "wood"),
        None,
    )
    if wood is None:
        return {"表面": {slot["槽位ID"]: slot["表面类型"] for slot in slots}}
    return {
        "木材": {
            "树种": wood["材质"],
            "纹理周期_mm": 52,
            "法线强度": wood["normal_strength"],
            "透明面漆": {"强度": 0.1, "粗糙度": wood["roughness"]},
            "榫卯节点": {
                "启用": True,
                "榫肩线宽_mm": 1,
                "距构件端部_mm": 16,
            },
        }
    }


def _base_rule(
    *,
    spec: CustomFurnitureSpec,
    furniture_type: str,
    generator: str,
    parts: list[dict[str, Any]],
    slots: list[dict[str, Any]],
) -> dict[str, Any]:
    dimensions = spec.dimensions
    rule = {
        "规则版本": "1.0.0",
        "规则状态": "ready",
        "模型ID": _stable_model_id(spec),
        "家具名称": spec.name,
        "家具类型": furniture_type,
        "生成器": generator,
        "坐标系统": {
            "单位": "mm",
            "上轴": "Y",
            "前向": "+Z",
            "原点": "floor_center",
        },
        "安装规则": {"基准": "floor", "偏移_mm": 0},
        "包围尺寸_mm": {
            "宽": dimensions.width_mm,
            "高": dimensions.height_mm,
            "深": dimensions.depth_mm,
        },
        "几何规则": {
            "显式部件数": len(parts),
            "结构族": generator,
        },
        "外观规则": _appearance(slots),
        "材质槽": slots,
        "部件": parts,
        "质量规则": {
            "目标三角面": 32000,
            "需要UV": True,
            "贴图分辨率": "2K",
            "LOD": [32000, 16000, 6000],
        },
        "设计冻结": {
            "输入来源": "CustomFurnitureSpec",
            "单位": "mm",
            "说明": "全部几何由已校验参数确定性计算，投产前仍需工程复核。",
        },
    }
    validate_deterministic_rule(rule)
    return rule


def _build_cabinet_rule(spec: CabinetSpec) -> dict[str, Any]:
    width = spec.dimensions.width_mm
    height = spec.dimensions.height_mm
    depth = spec.dimensions.depth_mm
    structure = spec.structure
    panel = structure.panel_thickness_mm
    leg_height = structure.leg_height_mm
    body_height = height - leg_height
    inner_width = width - 2 * panel
    inner_height = body_height - 2 * panel
    parts = [
        _part("top", "rounded_box", [width, panel, depth], [0, height - panel / 2, 0], "primary", 圆角_mm=4),
        _part("bottom", "rounded_box", [width, panel, depth], [0, leg_height + panel / 2, 0], "primary", 圆角_mm=3),
        _part("left_side", "rounded_box", [panel, body_height, depth], [-width / 2 + panel / 2, leg_height + body_height / 2, 0], "primary", 圆角_mm=3),
        _part("right_side", "rounded_box", [panel, body_height, depth], [width / 2 - panel / 2, leg_height + body_height / 2, 0], "primary", 圆角_mm=3),
        _part("back", "rounded_box", [inner_width, inner_height, 9], [0, leg_height + panel + inner_height / 2, -depth / 2 + 4.5], "primary", 圆角_mm=1),
    ]
    compartment_width = inner_width / structure.compartment_count
    for index in range(1, structure.compartment_count):
        x = -inner_width / 2 + index * compartment_width
        parts.append(
            _part(
                f"partition_{index}",
                "rounded_box",
                [panel, inner_height, depth - 12],
                [x, leg_height + panel + inner_height / 2, 0],
                "primary",
                圆角_mm=2,
            )
        )
    for index in range(structure.shelf_count):
        y = leg_height + panel + inner_height * (index + 1) / (structure.shelf_count + 1)
        parts.append(
            _part(
                f"shelf_{index + 1}",
                "rounded_box",
                [inner_width, panel, depth - 18],
                [0, y, 0],
                "primary",
                圆角_mm=2,
            )
        )
    if structure.door_count:
        gap = 3
        door_width = (inner_width - gap * (structure.door_count - 1)) / structure.door_count
        for index in range(structure.door_count):
            x = -inner_width / 2 + door_width / 2 + index * (door_width + gap)
            parts.append(
                _part(
                    f"door_{index + 1}",
                    "rounded_box",
                    [door_width, inner_height, 20],
                    [x, leg_height + panel + inner_height / 2, depth / 2 - 10],
                    "primary",
                    圆角_mm=4,
                )
            )
    for index in range(structure.drawer_count):
        drawer_width = min(compartment_width - 8, 700)
        drawer_height = min(160, inner_height / max(structure.drawer_count + 1, 2))
        y = leg_height + panel + drawer_height / 2 + index * drawer_height
        parts.append(
            _part(
                f"drawer_front_{index + 1}",
                "rounded_box",
                [drawer_width, drawer_height - 4, 22],
                [-inner_width / 2 + compartment_width / 2, y, depth / 2 - 11],
                "primary",
                圆角_mm=3,
            )
        )
    if leg_height:
        for part_id, x, z in (
            ("front_left", -width / 2 + 45, depth / 2 - 45),
            ("front_right", width / 2 - 45, depth / 2 - 45),
            ("rear_left", -width / 2 + 45, -depth / 2 + 45),
            ("rear_right", width / 2 - 45, -depth / 2 + 45),
        ):
            parts.append(
                _part(
                    f"leg_{part_id}",
                    "tapered_wood_leg",
                    [32, leg_height, 32],
                    [x, leg_height / 2, z],
                    "primary",
                )
            )
    slots = _material_slots(spec)
    return _base_rule(
        spec=spec,
        furniture_type="定制柜体",
        generator="cabinet_v2",
        parts=parts,
        slots=slots,
    )


def _build_table_rule(spec: TableSpec) -> dict[str, Any]:
    width = spec.dimensions.width_mm
    height = spec.dimensions.height_mm
    depth = spec.dimensions.depth_mm
    structure = spec.structure
    top = structure.top_thickness_mm
    leg_height = height - top
    slots = _material_slots(spec)
    base_slot = "base" if len(slots) > 1 else "primary"
    if structure.top_shape == "round":
        parts = [
            _part("tabletop", "cylinder", [width, top, depth], [0, height - top / 2, 0], "primary")
        ]
    else:
        parts = [
            _part(
                "tabletop",
                "rounded_tabletop",
                [width, top, depth],
                [0, height - top / 2, 0],
                "primary",
                平面圆角半径_mm=structure.edge_radius_mm,
                边缘圆角_mm=min(structure.edge_radius_mm, top / 2),
            )
        ]
    if structure.base_style == "four_leg":
        inset_x = min(120, width * 0.12)
        inset_z = min(100, depth * 0.14)
        for part_id, x, z in (
            ("front_left", -width / 2 + inset_x, depth / 2 - inset_z),
            ("front_right", width / 2 - inset_x, depth / 2 - inset_z),
            ("rear_left", -width / 2 + inset_x, -depth / 2 + inset_z),
            ("rear_right", width / 2 - inset_x, -depth / 2 + inset_z),
        ):
            parts.append(
                _part(
                    f"leg_{part_id}",
                    "top_pivot_tapered_wood_leg",
                    [55, leg_height, 55],
                    [x, leg_height / 2, z],
                    base_slot,
                )
            )
    elif structure.base_style == "pedestal":
        base_diameter = min(width, depth) * 0.56
        parts.extend(
            [
                _part(
                    "pedestal",
                    "frustum",
                    [base_diameter, leg_height, base_diameter],
                    [0, leg_height / 2, 0],
                    base_slot,
                    顶部直径_mm=base_diameter * 0.48,
                    底部直径_mm=base_diameter,
                ),
                _part(
                    "base_ring",
                    "cylinder",
                    [base_diameter, 12, base_diameter],
                    [0, 6, 0],
                    base_slot,
                ),
            ]
        )
    else:
        support_x = width * 0.3
        support_width = min(120, width * 0.08)
        for side, x in (("left", -support_x), ("right", support_x)):
            parts.append(
                _part(
                    f"{side}_trestle",
                    "rounded_box",
                    [support_width, leg_height, depth * 0.72],
                    [x, leg_height / 2, 0],
                    base_slot,
                    圆角_mm=8,
                )
            )
        parts.append(
            _part(
                "center_rail",
                "wood_rail",
                [support_x * 2, 70, 60],
                [0, leg_height * 0.42, 0],
                base_slot,
            )
        )
    furniture_types = {
        "dining_table": "定制餐桌",
        "desk": "定制书桌",
        "kitchen_island": "定制岛台桌",
    }
    return _base_rule(
        spec=spec,
        furniture_type=furniture_types[spec.purpose],
        generator="table_v2",
        parts=parts,
        slots=slots,
    )


def _build_model_spec(spec: CustomFurnitureSpec) -> dict[str, Any]:
    rule = _build_cabinet_rule(spec) if isinstance(spec, CabinetSpec) else _build_table_rule(spec)
    furniture_type = rule["家具类型"]
    dimensions = spec.dimensions
    return {
        "家具类型": furniture_type,
        "家具名称": spec.name,
        "尺寸参数": {
            "宽": dimensions.width_mm,
            "高": dimensions.height_mm,
            "深": dimensions.depth_mm,
        },
        "结构参数": spec.structure.model_dump(mode="json"),
        "材质参数": [
            {
                key: value
                for key, value in slot.items()
                if key != "槽位ID" and key != "表面类型"
            }
            for slot in rule["材质槽"]
        ],
        "真实制造约束": {
            "尺寸单位": "mm",
            "投产状态": "待工程复核",
            "参数来源": "CustomFurnitureSpec",
        },
        "确定性建模规则": rule,
        "安装参数": {"锚点": "floor"},
    }


def _quote_quantity(spec: CustomFurnitureSpec, pricing_unit: str) -> Decimal | None:
    dimensions = spec.dimensions
    if pricing_unit == "㎡":
        value = Decimal(dimensions.width_mm * dimensions.height_mm) / Decimal(1_000_000)
    elif pricing_unit in {"米", "延米"}:
        value = Decimal(dimensions.width_mm) / Decimal(1000)
    elif pricing_unit == "项":
        value = Decimal(1)
    else:
        return None
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _build_quote_preview(
    db: Session,
    spec: CustomFurnitureSpec,
) -> CustomFurnitureQuotePreview:
    project_name = PURPOSE_PROJECT_NAMES[spec.purpose]
    rules = db.scalars(
        select(CustomQuoteRule)
        .where(
            CustomQuoteRule.project_name == project_name,
            CustomQuoteRule.material_grade == spec.material,
            CustomQuoteRule.is_active.is_(True),
        )
        .order_by(CustomQuoteRule.id)
    ).all()
    if not rules:
        return CustomFurnitureQuotePreview(
            status="needs_human",
            reason_code="quote_rule_missing",
            project_name=project_name,
            material_grade=spec.material,
        )
    if len(rules) > 1:
        return CustomFurnitureQuotePreview(
            status="needs_human",
            reason_code="quote_rule_ambiguous",
            project_name=project_name,
            material_grade=spec.material,
        )
    rule = rules[0]
    quantity = _quote_quantity(spec, rule.pricing_unit)
    if quantity is None or rule.unit_price <= 0:
        return CustomFurnitureQuotePreview(
            status="needs_human",
            reason_code="quote_rule_invalid",
            rule_id=rule.id,
            project_name=project_name,
            material_grade=spec.material,
            pricing_unit=rule.pricing_unit,
            description=rule.description,
        )
    amount = (quantity * Decimal(rule.unit_price)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    return CustomFurnitureQuotePreview(
        status="estimated",
        rule_id=rule.id,
        project_name=project_name,
        material_grade=spec.material,
        pricing_unit=rule.pricing_unit,
        unit_price=rule.unit_price,
        quantity=quantity,
        estimated_amount=amount,
        description=rule.description,
    )


def build_preview(
    db: Session,
    spec: CustomFurnitureSpec,
) -> CustomFurniturePreviewResult:
    """只构建预览，不持久化草案，也不执行任何模型产生的代码。"""
    quote = _build_quote_preview(db, spec)
    warnings = ["参数化结果投产前需要工程师复核结构、五金与加工余量。"]
    if quote.status == "needs_human":
        warnings.append("没有唯一可复算的启用报价规则，价格需要人工确认。")
    return CustomFurniturePreviewResult(
        status="preview_ready" if quote.status == "estimated" else "needs_human",
        spec=spec,
        model_spec=_build_model_spec(spec),
        quote_preview=quote,
        warnings=warnings,
    )
