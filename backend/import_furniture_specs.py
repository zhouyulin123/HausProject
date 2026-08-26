# -*- coding: utf-8 -*-
"""把 20 款家具的 3D 建模真实参数（furniture_3d_specs.json）按名称匹配写入 products.model_spec_json。

    python import_furniture_specs.py           # 导入（覆盖已有 model_spec_json）
    python import_furniture_specs.py --dry-run # 只打印匹配结果，不写库
"""

import json
import sys
from pathlib import Path

from app.db.database import SessionLocal
from app.db.models import Product

SPEC_FILE = Path(__file__).resolve().parent / "furniture_3d_specs.json"
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


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    specs = load_specs()
    if not specs:
        print("furniture_3d_specs.json 没有找到「家具列表」")
        return

    db = SessionLocal()
    matched = 0
    missing: list[str] = []
    try:
        for spec in specs:
            name = (spec.get("家具名称") or "").strip()
            product = db.query(Product).filter(Product.name == name).first()
            if product is None:
                missing.append(name)
                continue
            if not dry_run:
                product.model_spec_json = spec
                matched += 1
            else:
                matched += 1
        if not dry_run:
            db.commit()
            print(f"OK: 已写入 {matched} 件商品的 3D 建模参数")
        else:
            print(f"[dry-run] 将写入 {matched} 件商品的 3D 建模参数")
    finally:
        db.close()

    if missing:
        print(f"警告：{len(missing)} 款未匹配到商品：")
        for name in missing:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
