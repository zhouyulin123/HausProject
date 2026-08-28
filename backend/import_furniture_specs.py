# -*- coding: utf-8 -*-
"""把 40 款家具参数同步到商品库，并注入 ready 的确定性规则。

    python import_furniture_specs.py           # 导入（覆盖已有 model_spec_json）
    python import_furniture_specs.py --dry-run # 只打印匹配结果，不写库
"""

import json
import sys
from pathlib import Path

from app.db.database import SessionLocal
from app.db.models import Product

SPEC_FILE = Path(__file__).resolve().parent / "furniture_3d_specs_40.json"
RULES_FILE = Path(__file__).resolve().parent / "furniture_model_rules.json"


def load_ready_rules() -> dict[str, dict]:
    with open(RULES_FILE, encoding="utf-8") as file:
        data = json.load(file)
    return {
        item["家具名称"]: item["确定性规则"]
        for item in data.get("模型目录") or []
        if item.get("规则状态") == "ready"
        and isinstance(item.get("确定性规则"), dict)
    }


def load_model_ids() -> dict[str, str]:
    with open(RULES_FILE, encoding="utf-8") as file:
        data = json.load(file)
    return {
        item["家具名称"]: item["模型ID"]
        for item in data.get("模型目录") or []
        if item.get("家具名称") and item.get("模型ID")
    }


def load_specs() -> list[dict]:
    with open(SPEC_FILE, encoding="utf-8") as file:
        data = json.load(file)
    specs = data.get("家具列表") or []
    ready_rules = load_ready_rules()
    for spec in specs:
        rule = ready_rules.get(spec.get("家具名称"))
        if rule is not None:
            spec["确定性建模规则"] = rule
    return specs


def _first_number(dimensions: dict, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = dimensions.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def _category(furniture_type: str) -> str:
    for category in ("沙发", "茶几", "餐桌", "餐椅", "床"):
        if category in furniture_type:
            return category
    return furniture_type


def product_payload_from_spec(spec: dict, model_id: str) -> dict:
    dimensions = spec.get("尺寸参数") or {}
    width = _first_number(dimensions, ("总宽", "外框宽", "长", "直径"))
    depth = _first_number(dimensions, ("总深", "外框长", "宽", "直径"))
    height = _first_number(dimensions, ("总高", "床头高", "高"))
    material_specs = spec.get("材质参数") or []
    material = next(
        (
            entry.get("材质")
            for entry in material_specs
            if isinstance(entry, dict) and entry.get("材质")
        ),
        "真实参数材质",
    )
    price_range = spec.get("参考价格_元") or [0]
    price = int(price_range[0])
    price_max = int(price_range[1]) if len(price_range) > 1 else None
    size = (
        f"{width} × {depth} × {height}mm"
        if all(value is not None for value in (width, depth, height))
        else "详见 3D 参数"
    )
    return {
        "sku": model_id,
        "name": spec["家具名称"],
        "category": _category(spec["家具类型"]),
        "room": spec["空间"],
        "style": spec["风格"],
        "material": material,
        "price": price,
        "price_max": price_max,
        "size": size,
        "selling_point": f"真实尺寸参数建模，{material}材质",
        "alternative": "可选同类型其他参数款",
        "model_width_mm": width,
        "model_height_mm": height,
        "model_depth_mm": depth,
        "model_source": "家具3D真实参数",
    }


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    specs = load_specs()
    if not specs:
        print("furniture_3d_specs_40.json 没有找到「家具列表」")
        return

    db = SessionLocal()
    matched = added = 0
    model_ids = load_model_ids()
    try:
        for spec in specs:
            name = (spec.get("家具名称") or "").strip()
            payload = product_payload_from_spec(spec, model_ids[name])
            product = db.query(Product).filter(Product.name == name).first()
            if product is None:
                product = Product(**payload)
                if not dry_run:
                    db.add(product)
                added += 1
            if not dry_run:
                for field in (
                    "model_width_mm",
                    "model_height_mm",
                    "model_depth_mm",
                    "model_source",
                ):
                    setattr(product, field, payload[field])
                product.model_spec_json = spec
                product.is_active = True
                matched += 1
            else:
                matched += 1
        if not dry_run:
            db.commit()
            print(f"OK: 同步 {matched} 件商品（新增 {added}），并写入 3D 建模参数")
        else:
            print(f"[dry-run] 将同步 {matched} 件商品（新增 {added}）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
