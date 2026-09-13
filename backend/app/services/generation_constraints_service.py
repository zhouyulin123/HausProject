"""正式方案生成与精修共用的已确认约束上下文。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import isfinite
import re
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import DesignTask
from app.services import catalog_service, task_service


def _positive_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if isfinite(normalized) and normalized > 0 else None


def _positive_int(value: Any) -> int | None:
    normalized = _positive_float(value)
    rounded = round(normalized) if normalized is not None else None
    return rounded if rounded is not None and rounded > 0 else None


def _positive_meters(value: Any) -> float | None:
    normalized = _positive_float(value)
    if normalized is None or round(normalized * 1000) <= 0:
        return None
    return normalized


def parse_budget_range(value: Any) -> tuple[int | None, int | None]:
    """解析现有中文预算区间；不从面积或风格推测预算。"""
    if not isinstance(value, str) or not value.strip():
        return None, None
    normalized = value.replace("，", "").replace(",", "").strip()
    tokens = re.findall(r"(\d+(?:\.\d+)?)\s*(万|元)?", normalized)
    if not tokens:
        return None, None
    has_ten_thousand_unit = any(unit == "万" for _, unit in tokens)
    amounts = []
    for raw_number, unit in tokens:
        number = float(raw_number)
        multiplier = 10_000 if unit == "万" else 1
        if not unit and has_ten_thousand_unit and number < 1_000:
            multiplier = 10_000
        amounts.append(round(number * multiplier))
    if len(amounts) >= 2 and any(mark in normalized for mark in ("-", "~", "至")):
        low, high = amounts[0], amounts[1]
        return min(low, high), max(low, high)
    amount = amounts[0]
    if any(mark in normalized for mark in ("以上", "起")):
        return amount, None
    return None, amount


def normalize_requirement_facts(requirement: dict[str, Any]) -> dict[str, Any]:
    """把已支持的需求字段别名归一化，不补造未确认事实。"""
    facts: dict[str, Any] = {}
    aliases = {
        "space_type": ("space_type", "spaceType"),
        "style": ("style",),
        "budget_min": ("budget_min", "budgetMin"),
        "budget_max": ("budget_max", "budgetMax"),
        "max_unit_price": ("max_unit_price", "maxUnitPrice"),
        "room_width_m": ("room_width_m", "roomWidthM", "roomWidth"),
        "room_depth_m": ("room_depth_m", "roomDepthM", "roomDepth"),
        "ceiling_height_m": (
            "ceiling_height_m",
            "ceilingHeightM",
            "ceilingHeight",
        ),
        "delivery_region": (
            "delivery_region",
            "deliveryRegion",
            "region_code",
            "regionCode",
        ),
    }
    cleared = {key for key in aliases if key in requirement and requirement[key] is None}
    for target, keys in aliases.items():
        for key in keys:
            value = requirement.get(key)
            if value not in (None, "", 0):
                facts[target] = value
                break

    rooms = requirement.get("rooms")
    if "space_type" not in facts and isinstance(rooms, list) and rooms:
        if isinstance(rooms[0], str) and rooms[0].strip():
            facts["space_type"] = rooms[0].strip()
    styles = requirement.get("styles")
    if "style" not in facts and isinstance(styles, list) and styles:
        if isinstance(styles[0], str) and styles[0].strip():
            facts["style"] = styles[0].strip()

    budget = requirement.get("budget")
    if isinstance(budget, dict):
        if "budget_min" not in facts:
            facts["budget_min"] = budget.get("min_budget")
        if "budget_max" not in facts:
            facts["budget_max"] = budget.get("max_budget")
    elif "budget_max" not in facts and budget not in (None, "", 0):
        facts["budget_max"] = budget

    budget_min, budget_max = parse_budget_range(requirement.get("budgetRange"))
    if "budget_min" not in facts and budget_min is not None:
        facts["budget_min"] = budget_min
    if "budget_max" not in facts and budget_max is not None:
        facts["budget_max"] = budget_max

    if "delivery_region" in facts:
        region = str(facts["delivery_region"]).strip().upper()
        if region:
            facts["delivery_region"] = region
        else:
            facts.pop("delivery_region", None)
    if "preferred_materials" in requirement:
        facts["preferred_materials"] = requirement["preferred_materials"]
    return {key: value for key, value in facts.items() if value is not None and key not in cleared}


@dataclass(frozen=True, slots=True)
class GenerationConstraints:
    delivery_region: str | None = None
    budget_max: int | None = None
    max_unit_price: int | None = None
    room_width_m: float | None = None
    room_depth_m: float | None = None
    ceiling_height_m: float | None = None

    def as_dict(self) -> dict[str, str | int | float]:
        values = {
            "delivery_region": self.delivery_region,
            "budget_max": self.budget_max,
            "max_unit_price": self.max_unit_price,
            "room_width_m": self.room_width_m,
            "room_depth_m": self.room_depth_m,
            "ceiling_height_m": self.ceiling_height_m,
        }
        return {key: value for key, value in values.items() if value is not None}

    def max_dimensions_mm(self) -> dict[str, int] | None:
        if self.room_width_m is None or self.room_depth_m is None:
            return None
        dimensions = {
            "width": round(self.room_width_m * 1000),
            "depth": round(self.room_depth_m * 1000),
        }
        if self.ceiling_height_m is not None:
            dimensions["height"] = round(self.ceiling_height_m * 1000)
        return dimensions

    def catalog_kwargs(self) -> dict[str, Any]:
        values = {
            "region": self.delivery_region,
            "max_unit_price": self.max_unit_price,
            "max_dimensions_mm": self.max_dimensions_mm(),
        }
        return {key: value for key, value in values.items() if value is not None}

    def enrichment_kwargs(self) -> dict[str, Any]:
        values = {
            "region": self.delivery_region,
            "budget_max": self.budget_max,
            "max_unit_price": self.max_unit_price,
            "max_dimensions_mm": self.max_dimensions_mm(),
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class GenerationContext:
    constraints: GenerationConstraints
    requirement: dict[str, Any]
    catalog_context: str
    catalog_fingerprint: dict[str, str]


def requirement_for_task(task: DesignTask) -> dict[str, Any]:
    requirement = task.confirmed_requirement_json
    if requirement is None:
        requirement = task_service.parse_requirement(task.raw_user_input or "")
    return deepcopy(requirement or {})


def constraints_for_task(
    task: DesignTask,
    *,
    requirement: dict[str, Any] | None = None,
) -> GenerationConstraints:
    source = requirement_for_task(task) if requirement is None else requirement
    constraints = constraints_from_facts(source)
    budget_max = constraints.budget_max
    if task.budget_max is not None:
        budget_max = _positive_int(task.budget_max)
    return GenerationConstraints(
        delivery_region=constraints.delivery_region,
        budget_max=budget_max,
        max_unit_price=constraints.max_unit_price,
        room_width_m=constraints.room_width_m,
        room_depth_m=constraints.room_depth_m,
        ceiling_height_m=constraints.ceiling_height_m,
    )


def constraints_from_facts(facts: dict[str, Any]) -> GenerationConstraints:
    """把任意已确认事实映射为同一套目录与报价硬约束。"""
    normalized = normalize_requirement_facts(facts)
    region = normalized.get("delivery_region")
    return GenerationConstraints(
        delivery_region=region if isinstance(region, str) else None,
        budget_max=_positive_int(normalized.get("budget_max")),
        max_unit_price=_positive_int(normalized.get("max_unit_price")),
        room_width_m=_positive_meters(normalized.get("room_width_m")),
        room_depth_m=_positive_meters(normalized.get("room_depth_m")),
        ceiling_height_m=_positive_meters(normalized.get("ceiling_height_m")),
    )


def build_generation_context(
    db: Session,
    task: DesignTask,
    *,
    requirement: dict[str, Any] | None = None,
) -> GenerationContext:
    """冻结单次调用使用的规范需求、硬约束与受限商品上下文。"""
    source = (
        requirement_for_task(task) if requirement is None else deepcopy(requirement)
    )
    constraints = constraints_for_task(task, requirement=source)
    normalized_requirement = {**source, **constraints.as_dict()}
    checked_at = datetime.now(timezone.utc)
    scoped_catalog = catalog_service.build_catalog_context(
        db,
        at=checked_at,
        **constraints.catalog_kwargs(),
    )
    catalog_fingerprint = catalog_service.catalog_revision_fingerprint(
        db,
        at=checked_at,
        **constraints.catalog_kwargs(),
    )
    constraint_context = json.dumps(
        constraints.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    catalog_context = (
        f"【本次已确认生成硬约束】\n{constraint_context}\n\n{scoped_catalog}"
    )
    return GenerationContext(
        constraints=constraints,
        requirement=normalized_requirement,
        catalog_context=catalog_context,
        catalog_fingerprint=catalog_fingerprint,
    )
