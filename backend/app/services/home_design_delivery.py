"""从精确整屋版本派生概念交付，不推断商品、价格或施工结论。"""

from hashlib import sha256
import json
from math import hypot

from sqlalchemy import select

from app.db.models import DesignSpaceVersion, HomeDesignVersion
from app.schemas.home_design import HomeDesignDocument
from app.schemas.spatial import SpatialDocument
from app.services.home_design_validation import validate_design

EPS = 1e-8
CALCULATION_VERSION = "home-delivery/1.0"
LIMITATIONS = [
    "概念方案沟通资料，不是采购单、施工图或施工安全结论。",
    "仅计已指定饰面的平面净面积与物件件数，不自动补全未设计区域。",
    "面积不含洞口侧边、收口、基层、损耗、工艺和安装工程量。",
    "物件按盒体表达；校验不覆盖承重、门扇开启、活动动线及设备专业条件。",
    "材料名称与颜色不是商业规格；价格、税费、运输及人工均待报价。",
]


def _wall_intervals(wall, polygon):
    """把房间的共线边界投影到墙长轴并合并，只计实际邻接部分。"""
    dx, dz = wall.end.x - wall.start.x, wall.end.z - wall.start.z
    length = hypot(dx, dz)
    if length <= EPS:
        return []
    dx, dz = dx / length, dz / length
    intervals = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if any(
            abs(dx * (p.z - wall.start.z) - dz * (p.x - wall.start.x)) > EPS
            for p in (a, b)
        ):
            continue
        positions = [
            (p.x - wall.start.x) * dx + (p.z - wall.start.z) * dz for p in (a, b)
        ]
        low, high = max(0.0, min(positions)), min(length, max(positions))
        if high - low > EPS:
            intervals.append((low, high))
    merged = []
    for low, high in sorted(intervals):
        if merged and low <= merged[-1][1] + EPS:
            merged[-1] = (merged[-1][0], max(high, merged[-1][1]))
        else:
            merged.append((low, high))
    return merged


def _surface_area(surface, space):
    room = next(room for room in space.rooms if room.id == surface.room_id)
    if surface.kind != "wall":
        points = room.polygon
        return (
            abs(
                sum(
                    a.x * b.z - b.x * a.z
                    for a, b in zip(points, points[1:] + points[:1])
                )
            )
            / 2
        )
    wall = next(wall for wall in space.walls if wall.id == surface.wall_id)
    intervals = _wall_intervals(wall, room.polygon)
    if not intervals:
        return None
    height = min(wall.height, room.height)
    area = sum(high - low for low, high in intervals) * height
    for opening in space.openings:
        if opening.wall_id != wall.id:
            continue
        opening_height = max(
            0.0,
            min(height, opening.sill_height + opening.height)
            - max(0.0, opening.sill_height),
        )
        for low, high in intervals:
            opening_width = max(
                0.0,
                min(high, opening.offset + opening.width) - max(low, opening.offset),
            )
            area -= opening_width * opening_height
    return max(0.0, area)


def build_delivery(*, task_id, version, document, space, assets=None):
    validation = validate_design(document, space).model_dump(mode="json")
    lines, gaps = [], []
    rooms = {room.id: room.name for room in space.rooms}
    for surface in sorted(document.surfaces, key=lambda item: item.id):
        quantity = (
            _surface_area(surface, space) if space.scale_status == "confirmed" else None
        )
        status = (
            "measured"
            if quantity is not None
            else "pending_scale"
            if space.scale_status != "confirmed"
            else "unmeasurable"
        )
        if status != "measured":
            gaps.append({"code": status, "entity_type": "surface", "id": surface.id})
        line = {
            "entity_type": "surface",
            "id": surface.id,
            "room_id": surface.room_id,
            "room_name": rooms[surface.room_id],
            "name": {"floor": "地面", "ceiling": "顶面", "wall": "墙面"}[
                surface.kind
            ],
            "material": surface.material.model_dump(),
            "unit": "m2",
            "quantity": round(quantity, 6) if quantity is not None else None,
            "quantity_status": status,
            "unit_price": None,
            "total_price": None,
            "price_status": "pending_quote",
        }
        if surface.quote_rule_id is not None:
            line["quote_rule_id"] = surface.quote_rule_id
        lines.append(line)
    for item in sorted(document.objects, key=lambda item: item.id):
        lines.append(
            {
                "entity_type": "object",
                "asset": {
                    key: value
                    for key, value in (assets or {}).get(item.asset_id, {}).items()
                    if key != "model_spec"
                }
                if item.asset_id is not None
                else None,
                "id": item.id,
                "room_id": item.room_id,
                "room_name": rooms[item.room_id],
                "name": item.name,
                "material": item.material.model_dump(),
                "unit": "piece",
                "quantity": 1,
                "quantity_status": "counted",
                "unit_price": None,
                "total_price": None,
                "price_status": "pending_quote",
            }
        )
    if not lines:
        gaps.append({"code": "no_design_elements", "entity_type": None, "id": None})
    result = {
        "schema_version": CALCULATION_VERSION,
        "task_id": task_id,
        "home_version": version,
        "space_version": document.space_version,
        "purpose": "concept_review",
        "document": document.model_dump(mode="json"),
        "space": space.model_dump(mode="json"),
        "assets": list((assets or {}).values()),
        "lines": lines,
        "validation": validation,
        "gaps": gaps,
        "limitations": list(LIMITATIONS),
        "total_price": None,
        "price_status": "pending_quote",
    }
    result["content_digest"] = sha256(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return result


def get_delivery(db, task_id, version):
    row = db.scalar(
        select(HomeDesignVersion).where(
            HomeDesignVersion.task_id == task_id, HomeDesignVersion.version == version
        )
    )
    if row is None:
        raise LookupError("整屋家装版本不存在")
    document = HomeDesignDocument.model_validate(row.document_json)
    space_row = db.scalar(
        select(DesignSpaceVersion).where(
            DesignSpaceVersion.task_id == task_id,
            DesignSpaceVersion.version == document.space_version,
        )
    )
    if space_row is None:
        raise LookupError("家装绑定的空间版本不存在")
    space = SpatialDocument.model_validate(space_row.document_json)
    from app.services.home_design_asset_service import validate_bindings

    assets = {
        identifier: asset.model_dump(mode="json")
        for identifier, asset in validate_bindings(db, task_id, document).items()
    }
    return build_delivery(
        task_id=task_id, version=version, document=document, space=space, assets=assets
    )


def compare_deliveries(before, after):
    changes = []
    for entity_type, collection in (("surface", "surfaces"), ("object", "objects"), ("point", "points")):
        old = {item["id"]: item for item in before["document"].get(collection, [])}
        new = {item["id"]: item for item in after["document"].get(collection, [])}
        old_lines = {
            item["id"]: item
            for item in before["lines"]
            if item["entity_type"] == entity_type
        }
        new_lines = {
            item["id"]: item
            for item in after["lines"]
            if item["entity_type"] == entity_type
        }
        for identifier in sorted(old.keys() | new.keys()):
            left, right = old.get(identifier), new.get(identifier)
            fields = sorted(
                key
                for key in (left or {}).keys() | (right or {}).keys()
                if (left or {}).get(key) != (right or {}).get(key)
            )
            if left is not None and right is not None and entity_type != "point":
                fields += [
                    key
                    for key in ("quantity", "quantity_status", "room_name")
                    if old_lines[identifier][key] != new_lines[identifier][key]
                ]
            if fields or left is None or right is None:
                changes.append(
                    {
                        "entity_type": entity_type,
                        "id": identifier,
                        "change": "added"
                        if left is None
                        else "removed"
                        if right is None
                        else "modified",
                        "changed_fields": fields,
                        "before": left,
                        "after": right,
                        "before_line": old_lines.get(identifier),
                        "after_line": new_lines.get(identifier),
                    }
                )
    return {
        "schema_version": "home-comparison/1.0",
        "task_id": before["task_id"],
        "from_version": before["home_version"],
        "to_version": after["home_version"],
        "from_space_version": before["space_version"],
        "to_space_version": after["space_version"],
        "space_changed": before["space_version"] != after["space_version"],
        "validation_changed": before["validation"] != after["validation"],
        "before_validation": before["validation"],
        "after_validation": after["validation"],
        "changes": changes,
        "limitations": list(LIMITATIONS),
    }
