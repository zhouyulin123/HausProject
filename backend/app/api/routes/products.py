"""商品库接口：成品家具 SKU + 定制报价规则。

读接口给前端家具页用，写接口给管理页 /admin 与 Excel 导入用。
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_factory
from app.core.config import settings
from app.db.database import get_db
from app.db.models import CustomQuoteRule, Product, User
from app.services.catalog_service import is_product_eligible
from app.services.glb_validation import GlbValidationError, validate_glb_upload
from app.services.product_asset_service import product_asset_contract
from app.services.upload_validation import UploadValidationError, validate_image_upload

router = APIRouter()


def _validate_product_lifecycle(product: Product) -> None:
    product.region_codes = list(
        dict.fromkeys(
            str(code).strip().upper()
            for code in (product.region_codes or [])
            if str(code).strip()
        )
    )
    product.alternative_skus = list(
        dict.fromkeys(
            str(sku).strip().upper()
            for sku in (product.alternative_skus or [])
            if str(sku).strip()
        )
    )
    if product.sku and product.sku.upper() in product.alternative_skus:
        raise HTTPException(status_code=422, detail="替代 SKU 不能包含商品自身")
    if (
        product.lead_time_days_min is not None
        and product.lead_time_days_max is not None
        and product.lead_time_days_min > product.lead_time_days_max
    ):
        raise HTTPException(status_code=422, detail="最短交期不能大于最长交期")
    if (
        product.price_valid_from is not None
        and product.price_valid_to is not None
        and product.price_valid_from > product.price_valid_to
    ):
        raise HTTPException(status_code=422, detail="价格生效时间不能晚于失效时间")
    if product.price_max is not None and product.price_max < product.price:
        raise HTTPException(status_code=422, detail="价格上限不能低于参考价")


def _product_to_dict(p: Product) -> dict:
    price_text = (
        f"¥{p.price:,} - {p.price_max:,}" if p.price_max else f"¥{p.price:,}"
    )
    eligibility = is_product_eligible(p)
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
        "model_url": p.model_url,
        "model_status": p.model_status,
        "model_width_mm": p.model_width_mm,
        "model_height_mm": p.model_height_mm,
        "model_depth_mm": p.model_depth_mm,
        "model_license": p.model_license,
        "model_source": p.model_source,
        "model_reviewed_at": p.model_reviewed_at,
        "model_reviewed_by": p.model_reviewed_by,
        "model_review_note": p.model_review_note,
        "model_spec_json": p.model_spec_json,
        "data_origin": p.data_origin,
        "source_name": p.source_name,
        "source_url": p.source_url,
        "source_product_id": p.source_product_id,
        "source_retrieved_at": p.source_retrieved_at,
        "price_observed_at": p.price_observed_at,
        "price_note": p.price_note,
        "source_metadata": p.source_metadata,
        "verification_status": p.verification_status,
        "availability_status": p.availability_status,
        "region_codes": p.region_codes or [],
        "stock_quantity": p.stock_quantity,
        "lead_time_days_min": p.lead_time_days_min,
        "lead_time_days_max": p.lead_time_days_max,
        "price_valid_from": p.price_valid_from,
        "price_valid_to": p.price_valid_to,
        "verified_at": p.verified_at,
        "verified_by": p.verified_by,
        "data_version": p.data_version,
        "record_version": p.record_version,
        "alternative_skus": p.alternative_skus or [],
        "eligibility": {
            "eligible": eligibility.eligible,
            "reason_codes": list(eligibility.reason_codes),
        },
        **product_asset_contract(p),
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
                "region_codes": r.region_codes or [],
                "waste_rate_bps": r.waste_rate_bps,
                "minimum_quantity": r.minimum_quantity,
                "installation_fee": r.installation_fee,
                "shipping_fee": r.shipping_fee,
                "tax_rate_bps": r.tax_rate_bps,
                "data_version": r.data_version,
                "record_version": r.record_version,
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
    price: int = Field(gt=0)
    sku: Optional[str] = None
    price_max: Optional[int] = None
    material: Optional[str] = None
    size: Optional[str] = None
    selling_point: Optional[str] = None
    alternative: Optional[str] = None
    image_url: Optional[str] = None
    model_width_mm: Optional[int] = Field(default=None, gt=0)
    model_height_mm: Optional[int] = Field(default=None, gt=0)
    model_depth_mm: Optional[int] = Field(default=None, gt=0)
    model_license: Optional[str] = Field(default=None, max_length=100)
    model_source: Optional[str] = Field(default=None, max_length=255)
    verification_status: Literal["draft", "verified", "rejected", "expired"] = "draft"
    availability_status: Literal[
        "in_stock", "low_stock", "out_of_stock", "preorder", "unknown"
    ] = "unknown"
    region_codes: list[str] = Field(default_factory=list, max_length=100)
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    lead_time_days_min: Optional[int] = Field(default=None, ge=0)
    lead_time_days_max: Optional[int] = Field(default=None, ge=0)
    price_valid_from: Optional[datetime] = None
    price_valid_to: Optional[datetime] = None
    data_version: str = Field(default="draft-v1", min_length=1, max_length=100)
    alternative_skus: list[str] = Field(default_factory=list, max_length=100)


@router.post("")
def create_product(
    data: ProductCreate,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    payload = data.model_dump()
    product = Product(**payload)
    if product.verification_status == "verified":
        product.verified_at = datetime.now(timezone.utc)
        product.verified_by = f"user:{_user.id}"
    _validate_product_lifecycle(product)
    db.add(product)
    db.commit()
    db.refresh(product)
    return _product_to_dict(product)


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    room: Optional[str] = None
    style: Optional[str] = None
    price: Optional[int] = Field(default=None, gt=0)
    sku: Optional[str] = None
    price_max: Optional[int] = None
    material: Optional[str] = None
    size: Optional[str] = None
    selling_point: Optional[str] = None
    alternative: Optional[str] = None
    image_url: Optional[str] = None
    model_width_mm: Optional[int] = Field(default=None, gt=0)
    model_height_mm: Optional[int] = Field(default=None, gt=0)
    model_depth_mm: Optional[int] = Field(default=None, gt=0)
    model_license: Optional[str] = Field(default=None, max_length=100)
    model_source: Optional[str] = Field(default=None, max_length=255)
    verification_status: Optional[
        Literal["draft", "verified", "rejected", "expired"]
    ] = None
    availability_status: Optional[
        Literal["in_stock", "low_stock", "out_of_stock", "preorder", "unknown"]
    ] = None
    region_codes: Optional[list[str]] = Field(default=None, max_length=100)
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    lead_time_days_min: Optional[int] = Field(default=None, ge=0)
    lead_time_days_max: Optional[int] = Field(default=None, ge=0)
    price_valid_from: Optional[datetime] = None
    price_valid_to: Optional[datetime] = None
    data_version: Optional[str] = Field(default=None, min_length=1, max_length=100)
    alternative_skus: Optional[list[str]] = Field(default=None, max_length=100)


@router.patch("/{product_id}")
def update_product(
    product_id: int,
    data: ProductUpdate,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    changes = data.model_dump(exclude_unset=True)
    commercial_fields = {
        "price",
        "price_max",
        "availability_status",
        "stock_quantity",
        "region_codes",
        "lead_time_days_min",
        "lead_time_days_max",
        "price_valid_from",
        "price_valid_to",
        "model_width_mm",
        "model_height_mm",
        "model_depth_mm",
        "data_version",
    }
    model_review_fields = {
        "model_width_mm",
        "model_height_mm",
        "model_depth_mm",
        "model_license",
        "model_source",
    }
    for k, v in changes.items():
        setattr(product, k, v)
    product.record_version = (product.record_version or 1) + 1
    if changes.get("verification_status") == "verified":
        product.verified_at = datetime.now(timezone.utc)
        product.verified_by = f"user:{_user.id}"
    elif commercial_fields.intersection(changes):
        product.verification_status = "draft"
        product.verified_at = None
        product.verified_by = None
    if model_review_fields.intersection(changes) and product.model_url:
        product.model_status = "pending_review"
        product.model_reviewed_at = None
        product.model_reviewed_by = None
        product.model_review_note = None
    _validate_product_lifecycle(product)
    db.commit()
    db.refresh(product)
    return _product_to_dict(product)


@router.delete("/{product_id}")
def deactivate_product(
    product_id: int,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = False  # 软删除，保留历史方案引用
    db.commit()
    return {"status": "ok"}


@router.post("/upload-image")
async def upload_product_image(
    file: UploadFile = File(...),
    _user: User = Depends(require_factory),
):
    """上传产品图，返回可访问 URL（供创建/编辑产品时填入 image_url）。"""
    content = await file.read()
    try:
        validated = validate_image_upload(
            content=content,
            content_type=file.content_type or "",
            filename=file.filename or "",
            max_bytes=settings.max_upload_image_mb * 1024 * 1024,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    upload_dir = Path(settings.upload_dir) / "products"
    upload_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid4().hex}.{validated.extension}"
    (upload_dir / fname).write_bytes(content)
    return {"image_url": f"/uploads/products/{fname}"}


@router.post("/{product_id}/model")
async def upload_product_model(
    product_id: int,
    file: UploadFile = File(...),
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    """上传并绑定商品 GLB；可用模型必须先维护真实物理尺寸。"""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not all(
        (product.model_width_mm, product.model_height_mm, product.model_depth_mm)
    ):
        raise HTTPException(status_code=422, detail="请先填写模型宽、高、深尺寸")
    if not (product.model_license or "").strip() or not (
        product.model_source or ""
    ).strip():
        raise HTTPException(status_code=422, detail="请先填写模型授权和来源")

    content = await file.read()
    try:
        validate_glb_upload(
            content=content,
            content_type=file.content_type or "",
            filename=file.filename or "",
            max_bytes=settings.max_upload_model_mb * 1024 * 1024,
        )
    except GlbValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    upload_dir = Path(settings.upload_dir) / "models"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}.glb"
    stored_path = upload_dir / stored_name
    stored_path.write_bytes(content)
    product.model_url = f"/uploads/models/{stored_name}"
    product.model_status = "pending_review"
    product.model_reviewed_at = None
    product.model_reviewed_by = None
    product.model_review_note = None
    try:
        db.commit()
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise
    db.refresh(product)
    return _product_to_dict(product)


class ProductModelReview(BaseModel):
    decision: Literal["approve", "reject"]
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/{product_id}/model-review")
def review_product_model(
    product_id: int,
    data: ProductModelReview,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not product.model_url or product.model_status not in {
        "pending_review",
        "ready",
        "rejected",
    }:
        raise HTTPException(status_code=409, detail="商品没有可审核的模型")
    if not (product.model_license or "").strip() or not (
        product.model_source or ""
    ).strip():
        raise HTTPException(status_code=422, detail="模型授权和来源不完整")
    product.model_status = "ready" if data.decision == "approve" else "rejected"
    product.model_reviewed_at = datetime.now(timezone.utc)
    product.model_reviewed_by = f"user:{user.id}"
    product.model_review_note = (data.note or "").strip() or None
    db.commit()
    db.refresh(product)
    return _product_to_dict(product)


# ---------------------------------------------------------------- 定制报价规则写接口


class QuoteRuleCreate(BaseModel):
    project_name: str
    category: str
    pricing_unit: str
    unit_price: int = Field(gt=0)
    material_grade: Optional[str] = None
    region_codes: list[str] = Field(default_factory=list, max_length=100)
    waste_rate_bps: int = Field(default=0, ge=0, le=10000)
    minimum_quantity: float = Field(default=0, ge=0)
    installation_fee: int = Field(default=0, ge=0)
    shipping_fee: int = Field(default=0, ge=0)
    tax_rate_bps: int = Field(default=0, ge=0, le=10000)
    data_version: str = Field(default="draft-v1", min_length=1, max_length=100)
    description: Optional[str] = None


class QuoteRuleUpdate(BaseModel):
    project_name: Optional[str] = None
    category: Optional[str] = None
    pricing_unit: Optional[str] = None
    unit_price: Optional[int] = Field(default=None, gt=0)
    material_grade: Optional[str] = None
    region_codes: Optional[list[str]] = Field(default=None, max_length=100)
    waste_rate_bps: Optional[int] = Field(default=None, ge=0, le=10000)
    minimum_quantity: Optional[float] = Field(default=None, ge=0)
    installation_fee: Optional[int] = Field(default=None, ge=0)
    shipping_fee: Optional[int] = Field(default=None, ge=0)
    tax_rate_bps: Optional[int] = Field(default=None, ge=0, le=10000)
    data_version: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = None


def _normalize_quote_rule(rule: CustomQuoteRule) -> None:
    rule.region_codes = list(
        dict.fromkeys(
            str(code).strip().upper()
            for code in (rule.region_codes or [])
            if str(code).strip()
        )
    )


@router.post("/quote-rules")
def create_quote_rule(
    data: QuoteRuleCreate,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    rule = CustomQuoteRule(**data.model_dump())
    _normalize_quote_rule(rule)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "status": "ok"}


@router.patch("/quote-rules/{rule_id}")
def update_quote_rule(
    rule_id: int,
    data: QuoteRuleUpdate,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    rule = db.get(CustomQuoteRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Quote rule not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    _normalize_quote_rule(rule)
    rule.record_version = (rule.record_version or 1) + 1
    db.commit()
    return {"id": rule.id, "status": "ok"}


@router.delete("/quote-rules/{rule_id}")
def deactivate_quote_rule(
    rule_id: int,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    rule = db.get(CustomQuoteRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Quote rule not found")
    rule.is_active = False
    db.commit()
    return {"status": "ok"}
