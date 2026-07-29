"""商品库接口：成品家具 SKU + 定制报价规则。

读接口给前端家具页用，写接口给管理页 /admin 与 Excel 导入用。
"""

import re
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.db.models import CustomQuoteRule, Product

router = APIRouter()


def _product_to_dict(p: Product) -> dict:
    price_text = (
        f"¥{p.price:,} - {p.price_max:,}" if p.price_max else f"¥{p.price:,}"
    )
    return {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "category": p.category,
        "room": p.room,
        "style": p.style,
        "material": p.material,
        "price": p.price,
        "price_max": p.price_max,
        "price_text": price_text,
        "size": p.size,
        "selling_point": p.selling_point,
        "alternative": p.alternative,
        "image_url": p.image_url,
    }


@router.get("")
def list_products(
    room: Optional[str] = None,
    category: Optional[str] = None,
    style: Optional[str] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Product).where(Product.is_active.is_(True))
    if room:
        stmt = stmt.where(Product.room == room)
    if category:
        stmt = stmt.where(Product.category == category)
    if style:
        stmt = stmt.where(Product.style == style)
    products = db.scalars(stmt.order_by(Product.id)).all()
    return {"products": [_product_to_dict(p) for p in products]}


@router.get("/meta")
def product_meta(db: Session = Depends(get_db)):
    """给前端筛选器用的可选项（从库里实际存在的值动态生成）。"""
    products = db.scalars(select(Product).where(Product.is_active.is_(True))).all()

    def distinct(field: str) -> list:
        return sorted({getattr(p, field) for p in products if getattr(p, field)})

    return {
        "rooms": distinct("room"),
        "categories": distinct("category"),
        "styles": distinct("style"),
        "count": len(products),
    }


@router.get("/quote-rules")
def list_quote_rules(db: Session = Depends(get_db)):
    rules = db.scalars(
        select(CustomQuoteRule)
        .where(CustomQuoteRule.is_active.is_(True))
        .order_by(CustomQuoteRule.category, CustomQuoteRule.project_name, CustomQuoteRule.unit_price)
    ).all()
    return {
        "rules": [
            {
                "id": r.id,
                "project_name": r.project_name,
                "category": r.category,
                "pricing_unit": r.pricing_unit,
                "material_grade": r.material_grade,
                "unit_price": r.unit_price,
                "description": r.description,
            }
            for r in rules
        ]
    }


# ---------------------------------------------------------------- 写接口（后续管理页用）


class ProductCreate(BaseModel):
    name: str
    category: str
    room: str
    style: str
    price: int
    sku: Optional[str] = None
    price_max: Optional[int] = None
    material: Optional[str] = None
    size: Optional[str] = None
    selling_point: Optional[str] = None
    alternative: Optional[str] = None
    image_url: Optional[str] = None


@router.post("")
def create_product(data: ProductCreate, db: Session = Depends(get_db)):
    product = Product(**data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return _product_to_dict(product)


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    room: Optional[str] = None
    style: Optional[str] = None
    price: Optional[int] = None
    sku: Optional[str] = None
    price_max: Optional[int] = None
    material: Optional[str] = None
    size: Optional[str] = None
    selling_point: Optional[str] = None
    alternative: Optional[str] = None
    image_url: Optional[str] = None


@router.patch("/{product_id}")
def update_product(product_id: int, data: ProductUpdate, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(product, k, v)
    db.commit()
    db.refresh(product)
    return _product_to_dict(product)


@router.delete("/{product_id}")
def deactivate_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = False  # 软删除，保留历史方案引用
    db.commit()
    return {"status": "ok"}


@router.post("/upload-image")
async def upload_product_image(file: UploadFile = File(...)):
    """上传产品图，返回可访问 URL（供创建/编辑产品时填入 image_url）。"""
    content = await file.read()
    upload_dir = Path(settings.upload_dir) / "products"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]", "_", file.filename or "product.jpg")
    fname = f"{int(time.time())}_{safe}"
    (upload_dir / fname).write_bytes(content)
    return {"image_url": f"/uploads/products/{fname}"}


# ---------------------------------------------------------------- 定制报价规则写接口


class QuoteRuleCreate(BaseModel):
    project_name: str
    category: str
    pricing_unit: str
    unit_price: int
    material_grade: Optional[str] = None
    description: Optional[str] = None


class QuoteRuleUpdate(BaseModel):
    project_name: Optional[str] = None
    category: Optional[str] = None
    pricing_unit: Optional[str] = None
    unit_price: Optional[int] = None
    material_grade: Optional[str] = None
    description: Optional[str] = None


@router.post("/quote-rules")
def create_quote_rule(data: QuoteRuleCreate, db: Session = Depends(get_db)):
    rule = CustomQuoteRule(**data.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "status": "ok"}


@router.patch("/quote-rules/{rule_id}")
def update_quote_rule(rule_id: int, data: QuoteRuleUpdate, db: Session = Depends(get_db)):
    rule = db.get(CustomQuoteRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Quote rule not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    db.commit()
    return {"id": rule.id, "status": "ok"}


@router.delete("/quote-rules/{rule_id}")
def deactivate_quote_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(CustomQuoteRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Quote rule not found")
    rule.is_active = False
    db.commit()
    return {"status": "ok"}
