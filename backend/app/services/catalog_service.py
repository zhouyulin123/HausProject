"""商品库 ↔ AI 方案的桥接层。

两个职责：
1. build_catalog_context —— 把成品家具库 + 定制价目表压缩成 LLM 上下文
2. verify_and_enrich_plans —— 校验 LLM 选的 SKU、用数据库回填真实价格/材质/尺寸，
   并生成「本店产品报价单」(shopQuote)。AI 永远不能自己编价格。
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CustomQuoteRule, Product

logger = logging.getLogger(__name__)


def _active_products(db: Session) -> List[Product]:
    return db.scalars(select(Product).where(Product.is_active.is_(True))).all()


def _active_rules(db: Session) -> List[CustomQuoteRule]:
    return db.scalars(
        select(CustomQuoteRule).where(CustomQuoteRule.is_active.is_(True))
    ).all()


def build_catalog_context(db: Session) -> str:
    """商品库上下文（约 30 行文本，随库增长后续可按风格预筛）。"""
    lines = ["【本店成品家具库】格式: sku|名称|类别|空间|风格|材质|价格(元)|尺寸"]
    for p in _active_products(db):
        price = f"{p.price}-{p.price_max}" if p.price_max else str(p.price)
        lines.append(
            f"{p.sku}|{p.name}|{p.category}|{p.room}|{p.style}|{p.material}|{price}|{p.size}"
        )
    lines.append("")
    lines.append("【本店定制项目价目表】格式: 项目|材料档位|单价(元)|计价单位")
    for r in _active_rules(db):
        lines.append(f"{r.project_name}|{r.material_grade}|{r.unit_price}|{r.pricing_unit}")
    return "\n".join(lines)


def _product_price_text(p: Product) -> str:
    return f"¥{p.price:,} - {p.price_max:,}" if p.price_max else f"¥{p.price:,}"


def _fallback_furniture(products: List[Product], plan_style: str, count: int = 4) -> List[Dict[str, Any]]:
    """LLM 没选出有效 SKU 时，按风格就近从库里挑。"""
    def score(p: Product) -> int:
        if not p.style:
            return 0
        return 2 if p.style in plan_style else (1 if p.style[:2] in plan_style else 0)

    picked = sorted(products, key=score, reverse=True)[:count]
    return [{"sku": p.sku, "quantity": 1} for p in picked]


def _match_rule(
    rules: List[CustomQuoteRule], project: str, grade: Optional[str]
) -> Optional[CustomQuoteRule]:
    exact = [r for r in rules if r.project_name == project and grade and r.material_grade == grade]
    if exact:
        return exact[0]
    by_project = [r for r in rules if r.project_name == project]
    if by_project:
        return by_project[0]
    # 项目名模糊匹配（LLM 可能写「衣柜定制」而库里是「定制衣柜」）
    loose = [r for r in rules if project and (project in r.project_name or r.project_name in project)]
    return loose[0] if loose else None


def verify_and_enrich_plans(db: Session, plans: List[Dict[str, Any]]) -> None:
    """就地校验/回填每套方案（LLM 与模板方案统一走这里）。"""
    products = _active_products(db)
    rules = _active_rules(db)
    by_sku = {p.sku: p for p in products if p.sku}

    for plan in plans:
        plan_style = str(plan.get("style", ""))

        # ---- 成品家具：SKU 校验 + 真实数据回填 ----
        raw_items = plan.get("furnitureSuggestions") or []
        valid_raw = [
            item for item in raw_items
            if isinstance(item, dict) and (item.get("sku") or item.get("id")) in by_sku
        ]
        if not valid_raw:
            logger.warning("方案 %s 的家具无有效 SKU，按风格从库中回退挑选", plan.get("id"))
            valid_raw = _fallback_furniture(products, plan_style)

        enriched = []
        furniture_total = 0
        for i, item in enumerate(valid_raw):
            sku = item.get("sku") or item.get("id")
            p = by_sku.get(sku)
            if not p:
                continue
            try:
                qty = max(1, min(10, int(item.get("quantity", 1))))
            except (TypeError, ValueError):
                qty = 1
            subtotal = p.price * qty
            furniture_total += subtotal
            enriched.append(
                {
                    "id": sku,
                    "sku": sku,
                    "name": p.name,
                    "category": p.category,
                    "room": p.room,
                    "style": p.style,
                    "material": p.material,
                    "priceRange": _product_price_text(p),
                    "sizeSuggestion": p.size or "",
                    "matchScore": max(85, 97 - i * 3),
                    "reason": item.get("reason") or p.selling_point or "",
                    "alternative": item.get("alternative") or p.alternative or "可选同风格系列款",
                    "imageUrl": p.image_url,
                    "quantity": qty,
                    "unitPrice": p.price,
                    "subtotal": subtotal,
                }
            )
        plan["furnitureSuggestions"] = enriched

        # ---- 定制项目：规则匹配 + 单价强制以价目表为准 ----
        raw_customs = plan.get("customItems") or []
        if not raw_customs:
            # 兜底：常规两项（衣柜 + 电视柜背景墙）
            raw_customs = [
                {"project": "定制衣柜", "quantity": 6, "note": "主卧衣柜投影约 6㎡"},
                {"project": "电视柜背景墙", "quantity": 4, "note": "客厅整墙约 4㎡"},
            ]
        custom_items = []
        custom_total = 0
        for item in raw_customs:
            if not isinstance(item, dict):
                continue
            rule = _match_rule(rules, str(item.get("project", "")), item.get("grade"))
            if not rule:
                continue
            try:
                qty = max(0.5, min(60.0, float(item.get("quantity", 1))))
            except (TypeError, ValueError):
                qty = 1.0
            subtotal = round(rule.unit_price * qty)
            custom_total += subtotal
            custom_items.append(
                {
                    "project": rule.project_name,
                    "grade": rule.material_grade,
                    "unit": rule.pricing_unit,
                    "unitPrice": rule.unit_price,
                    "quantity": round(qty, 1),
                    "subtotal": subtotal,
                    "note": item.get("note") or rule.description or "",
                }
            )
        plan["customItems"] = custom_items

        # ---- 本店产品报价单 ----
        plan["shopQuote"] = {
            "furnitureTotal": furniture_total,
            "customTotal": custom_total,
            "total": furniture_total + custom_total,
        }
