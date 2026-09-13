"""以当前开发商品构建跨空间案例，并运行目录、报价和布局工具。

从 backend 执行：python -m evals.development_catalog_cases --output ../outputs/development-catalog-report.json
只读数据库；不导入真实案例治理库，不调用 LLM，不签发正式评测证据。
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Product
from app.schemas.scenes import Opening, RoomGeometry, SceneDocument, Vector2XZ
from app.services.catalog_service import is_product_eligible, verify_and_enrich_plans
from app.services.evaluation_binding_service import normalize_task_input
from app.services.layout_generator import generate_layouts
from app.services.layout_service import build_layout_furniture


ROOMS = {"客厅": (4.2, 5.2), "卧室": (3.6, 4.4), "餐厅": (3.8, 4.2), "书房": (3.2, 3.8)}
NEEDS = ("保留开放活动区域", "便于日常清洁", "兼顾收纳和采光", "适合两人共同使用", "优先紧凑布局")
BUDGETS = (12000, 18000, 25000, 35000, 45000)


def build_cases(db: Session) -> list[dict[str, Any]]:
    """按空间及类别轮换已有 SKU，覆盖所有受支持空间中的开发商品。"""
    products = db.scalars(select(Product).where(
        Product.is_active.is_(True), Product.data_origin == "development_fixture",
    ).order_by(Product.sku)).all()
    if not products:
        raise ValueError("没有活动开发商品，请先补充开发目录")
    groups: dict[str, dict[str, list[Product]]] = defaultdict(lambda: defaultdict(list))
    for product in products:
        if product.room not in ROOMS or not product.sku or not product.category:
            raise ValueError(f"开发商品空间、SKU 或类别不完整：{product.sku}")
        groups[product.room][product.category].append(product)
    missing = set(ROOMS) - set(groups)
    if missing:
        raise ValueError(f"开发商品缺少空间：{'、'.join(sorted(missing))}")
    cases = []
    for room_index, (room_name, (width, depth)) in enumerate(ROOMS.items()):
        categories = groups[room_name]
        count = max(5, max(len(items) for items in categories.values()))
        for index in range(count):
            chosen = [items[index % len(items)] for _, items in sorted(categories.items())]
            budget = BUDGETS[index % len(BUDGETS)]
            w, d = round(width + index * 0.2, 2), round(depth + index * 0.15, 2)
            need = NEEDS[index % len(NEEDS)]
            case_id = f"development-catalog-{room_index + 1}-{index + 1:02d}"
            task_input = normalize_task_input({
                "raw_user_input": f"请为{w}米×{d}米的{room_name}搭配家具，预算{budget}元，{need}。",
                "space_type": room_name, "style": chosen[0].style or "现代简约",
                "budget_min": 0, "budget_max": budget,
                "confirmed_requirement": {"space": room_name, "region": "CN", "needs": [need]},
            })
            cases.append({
                "case_id": case_id, "origin": "synthetic", "split": "development",
                "assumptions": ["房间尺寸、门窗及需求为开发构造，非真实客户标注",
                                "价格与尺寸复用目录；库存和销售区域为开发假设",
                                "自然语言需求仅作为后续 LLM 输入，本 runner 不评判语义满足度"],
                "task_input": task_input, "region": "CN",
                "requested_skus": [p.sku for p in chosen],
                "room": RoomGeometry(id=case_id, name=room_name, ceiling_height=2.8,
                    floor_polygon=[Vector2XZ(x=-w/2, z=-d/2), Vector2XZ(x=w/2, z=-d/2),
                                   Vector2XZ(x=w/2, z=d/2), Vector2XZ(x=-w/2, z=d/2)]).model_dump(mode="json"),
                "openings": [Opening(id="door-1", type="door", wall_index=2, offset=0.3,
                                     width=0.9, height=2.1).model_dump(mode="json"),
                             Opening(id="window-1", type="window", wall_index=1, offset=1.0,
                                     width=1.2, height=1.2, sill_height=0.9).model_dump(mode="json")],
            })
    return cases


def run_suite(db: Session, cases: list[dict[str, Any]], *, at: datetime | None = None) -> dict[str, Any]:
    """每条案例保留失败，不删除不合格 SKU 或空模型来改善统计。"""
    if not cases:
        raise ValueError("案例集不能为空")
    if len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("案例 ID 重复")
    now = at or datetime.now(timezone.utc)
    rows = []
    for case in cases:
        if case.get("origin") != "synthetic" or case.get("split") != "development":
            raise ValueError("只允许 synthetic development 案例")
        task = normalize_task_input(case["task_input"])
        room = RoomGeometry.model_validate(case["room"])
        openings = [Opening.model_validate(item) for item in case["openings"]]
        failures = []
        for sku in case["requested_skus"]:
            product = db.scalar(select(Product).where(Product.sku == sku))
            if product is None:
                failures.append("product_missing")
            elif product.data_origin != "development_fixture":
                failures.append("not_development_fixture")
            else:
                failures.extend(is_product_eligible(product, at=now, region=case["region"],
                    required_quantity=1).reason_codes)
        if not case["requested_skus"]:
            failures.append("missing_product_sku")
        plan = {"furnitureSuggestions": [{"sku": sku, "quantity": 1} for sku in case["requested_skus"]]}
        verify_and_enrich_plans(db, [plan], at=now, region=case["region"], budget_max=task["budget_max"])
        failures.extend(plan["catalogValidation"]["hardErrors"])
        quote = plan.get("shopQuote")
        if quote and (sum(line["unitPrice"] * line["quantity"] for line in quote["lineItems"])
                      != quote["total"]):
            failures.append("quote_recalculation_mismatch")
        results = generate_layouts(room, openings, build_layout_furniture(db, plan["furnitureSuggestions"]))
        scene = None
        score = None
        issues = []
        if results:
            scene_model, score_model = results[0]
            scene = SceneDocument.model_validate(scene_model).model_dump(mode="json", by_alias=True)
            score = score_model.total
            issues = [issue.code for issue in score_model.issues]
            if not score_model.valid:
                failures.append("layout_invalid")
        else:
            failures.append("layout_empty")
        rows.append({"case_id": case["case_id"], "passed": not failures,
                     "failures": sorted(set(failures)), "layout_issue_codes": issues,
                     "layout_score": score, "quote": quote, "scene": scene, "input": case,
                     "resolved_skus": [item["sku"] for item in plan["furnitureSuggestions"]]})
    passed = sum(row["passed"] for row in rows)
    return {"schema_version": "development-catalog-eval/1.0", "origin": "synthetic",
            "production_acceptance": False, "llm_accuracy": None,
            "scope": "确定性目录资格、报价复算、布局检查；不包含 LLM/视觉/授权/制造验收",
            "checked_at": now.isoformat(), "total": len(rows), "passed": passed,
            "failed": len(rows)-passed, "cases": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        report = run_suite(db, build_cases(db))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("total", "passed", "failed", "scope")}, ensure_ascii=False))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
