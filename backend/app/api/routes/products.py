"""商品库接口：成品家具 SKU + 定制报价规则。

读接口给前端家具页用，写接口给管理页 /admin 与 Excel 导入用。
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_factory
from app.core.config import settings
from app.db.database import get_db
from app.db.models import CustomQuoteRule, Product, User
from app.schemas.catalog_readiness import CatalogReadinessResponse
from app.schemas.product_asset import (
    ProductAssetCreate,
    ProductAssetListResponse,
    ProductAssetResponse,
    ProductAssetReview,
)
from app.schemas.product_commercial import (
    CommercialReviewRequest,
    CommercialReviewResponse,
    ProductAuditEventListResponse,
    ProductAuditEventResponse,
)
from app.services.catalog_service import (
    development_catalog_enabled,
    build_catalog_readiness_summary,
    is_product_eligible,
)
from app.services.glb_validation import GlbValidationError, validate_glb_upload
from app.services import product_asset_service
from app.services import product_commercial_service
from app.services.product_asset_service import product_asset_contract
from app.services.upload_validation import UploadValidationError, validate_image_upload

router = APIRouter()

RequestIdHeader = Annotated[
    str | None,
    Header(
        alias="X-Request-ID",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]
IdempotencyKeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


def _record_version_conflict_detail(
    exc: product_commercial_service.ProductCommercialConflict,
) -> dict[str, object]:
    detail: dict[str, object] = {
        "code": "record_version_conflict",
        "message": str(exc),
    }
    if exc.expected_record_version is not None:
        detail["expected_record_version"] = exc.expected_record_version
    if exc.current_record_version is not None:
        detail["current_record_version"] = exc.current_record_version
    return detail


def _validate_product_lifecycle(product: Product) -> None:
    if product.data_origin == "development_fixture" and not development_catalog_enabled():
        raise HTTPException(status_code=422, detail="开发样本只能在已启用开发目录的开发环境维护")
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


def _validate_source_url(value: HttpUrl | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    normalized = str(TypeAdapter(HttpUrl).validate_python(value))
    if len(normalized) > 500:
        raise ValueError("来源地址不能超过 500 个字符")
    return normalized


def _validate_timezone_aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError("来源时间必须包含时区")
    return value


def _product_values_equal(current: object, requested: object) -> bool:
    if isinstance(current, datetime) and isinstance(requested, datetime):
        def normalized(value: datetime) -> datetime:
            if value.tzinfo is None:
                return value
            return value.astimezone(timezone.utc).replace(tzinfo=None)

        return normalized(current) == normalized(requested)
    if isinstance(current, list) and isinstance(requested, list):
        return [str(item).strip().upper() for item in current] == [
            str(item).strip().upper() for item in requested
        ]
    return current == requested


def _response_datetime(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _product_to_dict(
    p: Product,
    *,
    expose_pending_model: bool = False,
) -> dict:
    price_text = (
        f"¥{p.price:,} - {p.price_max:,}" if p.price_max else f"¥{p.price:,}"
    )
    eligibility = is_product_eligible(p)
    asset_contract = product_asset_contract(p)
    approved_assets = product_asset_service.public_product_assets(p)
    approved_glb = product_asset_service.approved_product_asset(p, "glb")
    approved_image_url = product_asset_service.approved_product_asset_url(p, "image")
    public_model_source = public_model_license = None
    public_model_reviewed_at = public_model_reviewed_by = None
    if asset_contract["approved_model_url"]:
        public_model_source = approved_glb.source if approved_glb else p.model_source
        public_model_license = (
            approved_glb.authorization if approved_glb else p.model_license
        )
        public_model_reviewed_at = (
            approved_glb.reviewed_at if approved_glb else p.model_reviewed_at
        )
        public_model_reviewed_by = (
            approved_glb.reviewed_by if approved_glb else p.model_reviewed_by
        )
    assets = (
        [
            ProductAssetResponse.model_validate(asset).model_dump()
            for asset in (p.assets or [])
        ]
        if expose_pending_model
        else approved_assets
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
        "image_url": (
            p.image_url
            if expose_pending_model
            else approved_image_url
        ),
        "model_url": (
            p.model_url
            if expose_pending_model
            else asset_contract["approved_model_url"]
        ),
        "model_status": p.model_status,
        "model_width_mm": p.model_width_mm,
        "model_height_mm": p.model_height_mm,
        "model_depth_mm": p.model_depth_mm,
        "model_license": (
            p.model_license
            if expose_pending_model
            else public_model_license
        ),
        "model_source": (
            p.model_source
            if expose_pending_model
            else public_model_source
        ),
        "model_reviewed_at": (
            _response_datetime(p.model_reviewed_at)
            if expose_pending_model
            else _response_datetime(public_model_reviewed_at)
        ),
        "model_reviewed_by": (
            p.model_reviewed_by
            if expose_pending_model
            else public_model_reviewed_by
        ),
        "model_review_note": p.model_review_note if expose_pending_model else None,
        "model_spec_json": p.model_spec_json,
        "data_origin": p.data_origin,
        "source_name": p.source_name,
        "source_url": p.source_url,
        "source_product_id": p.source_product_id,
        "source_retrieved_at": _response_datetime(p.source_retrieved_at),
        "price_observed_at": _response_datetime(p.price_observed_at),
        "price_note": p.price_note,
        "source_metadata": p.source_metadata,
        "verification_status": p.verification_status,
        "availability_status": p.availability_status,
        "region_codes": p.region_codes or [],
        "stock_quantity": p.stock_quantity,
        "lead_time_days_min": p.lead_time_days_min,
        "lead_time_days_max": p.lead_time_days_max,
        "price_valid_from": _response_datetime(p.price_valid_from),
        "price_valid_to": _response_datetime(p.price_valid_to),
        "verified_at": _response_datetime(p.verified_at),
        "verified_by": p.verified_by,
        "data_version": p.data_version,
        "record_version": p.record_version,
        "alternative_skus": p.alternative_skus or [],
        "eligibility": {
            "eligible": eligibility.eligible,
            "reason_codes": list(eligibility.reason_codes),
        },
        "assets": assets,
        **asset_contract,
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


@router.get("/admin/catalog")
def list_managed_products(
    verification_status: Optional[
        Literal["draft", "verified", "rejected", "expired"]
    ] = None,
    data_origin: Optional[str] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _user: User = Depends(require_factory),
):
    """返回商品审核所需的完整记录（包括待审核图片/模型资产）。"""
    stmt = select(Product)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    if verification_status:
        stmt = stmt.where(Product.verification_status == verification_status)
    if data_origin:
        stmt = stmt.where(Product.data_origin == data_origin.strip())
    products = db.scalars(stmt.order_by(Product.id)).all()
    return {
        "products": [
            _product_to_dict(product, expose_pending_model=True)
            for product in products
        ],
        "count": len(products),
    }


@router.get("/admin/readiness", response_model=CatalogReadinessResponse)
def get_catalog_readiness(
    region: str = Query(
        ...,
        min_length=2,
        max_length=20,
        pattern=r"^[A-Za-z0-9*-]+$",
    ),
    db: Session = Depends(get_db),
    _user: User = Depends(require_factory),
) -> CatalogReadinessResponse:
    """按指定交付地区返回商品目录的只读门禁缺口。"""
    return CatalogReadinessResponse.model_validate(
        build_catalog_readiness_summary(db, region=region)
    )


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
    model_config = ConfigDict(extra="forbid")

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
    data_origin: Literal[
        "development_fixture",
        "unknown",
        "merchant",
        "merchant_draft",
        "merchant_verified",
        "demo",
        "public_reference",
    ] = "unknown"
    source_name: Optional[str] = Field(default=None, max_length=100)
    source_url: Optional[str] = None
    source_product_id: Optional[str] = Field(default=None, max_length=100)
    source_retrieved_at: Optional[datetime] = None
    price_observed_at: Optional[datetime] = None
    price_note: Optional[str] = Field(default=None, max_length=500)
    source_metadata: Optional[dict[str, object]] = None
    model_width_mm: Optional[int] = Field(default=None, gt=0)
    model_height_mm: Optional[int] = Field(default=None, gt=0)
    model_depth_mm: Optional[int] = Field(default=None, gt=0)
    model_license: Optional[str] = Field(default=None, max_length=100)
    model_source: Optional[str] = Field(default=None, max_length=255)
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

    @field_validator("source_url", mode="before")
    @classmethod
    def validate_source_url(cls, value):
        return _validate_source_url(value)

    @field_validator(
        "source_retrieved_at",
        "price_observed_at",
        "price_valid_from",
        "price_valid_to",
    )
    @classmethod
    def validate_timestamps(cls, value):
        return _validate_timezone_aware(value)


@router.post("")
def create_product(
    data: ProductCreate,
    request_id: RequestIdHeader = None,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    payload = data.model_dump()
    product = Product(**payload)
    product.verification_status = "draft"
    product.verified_at = None
    product.verified_by = None
    _validate_product_lifecycle(product)
    db.add(product)
    db.flush()
    product_commercial_service.append_product_audit_event(
        db,
        product=product,
        event_type="commercial_created",
        actor=f"user:{_user.id}",
        request_id=product_commercial_service.request_id_or_new(request_id),
        before={
            field: None for field in product_commercial_service.AUDITED_FIELDS
        },
    )
    db.commit()
    db.refresh(product)
    return _product_to_dict(product, expose_pending_model=True)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_version: int = Field(gt=0)
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
    data_origin: Optional[
        Literal[
            "development_fixture",
            "unknown",
            "merchant",
            "merchant_draft",
            "merchant_verified",
            "demo",
            "public_reference",
        ]
    ] = None
    source_name: Optional[str] = Field(default=None, max_length=100)
    source_url: Optional[str] = None
    source_product_id: Optional[str] = Field(default=None, max_length=100)
    source_retrieved_at: Optional[datetime] = None
    price_observed_at: Optional[datetime] = None
    price_note: Optional[str] = Field(default=None, max_length=500)
    source_metadata: Optional[dict[str, object]] = None
    model_width_mm: Optional[int] = Field(default=None, gt=0)
    model_height_mm: Optional[int] = Field(default=None, gt=0)
    model_depth_mm: Optional[int] = Field(default=None, gt=0)
    model_license: Optional[str] = Field(default=None, max_length=100)
    model_source: Optional[str] = Field(default=None, max_length=255)
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

    @field_validator("source_url", mode="before")
    @classmethod
    def validate_source_url(cls, value):
        return _validate_source_url(value)

    @field_validator(
        "source_retrieved_at",
        "price_observed_at",
        "price_valid_from",
        "price_valid_to",
    )
    @classmethod
    def validate_timestamps(cls, value):
        return _validate_timezone_aware(value)


@router.patch("/{product_id}")
def update_product(
    product_id: int,
    data: ProductUpdate,
    request_id: RequestIdHeader = None,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    product = db.scalar(
        select(Product)
        .where(Product.id == product_id)
        .with_for_update()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    submitted = data.model_dump(exclude_unset=True)
    expected_record_version = submitted.pop("record_version")
    if expected_record_version != product.record_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "record_version_conflict",
                "message": "商品已被其他运营人员更新，请刷新后重试",
                "expected_record_version": expected_record_version,
                "current_record_version": product.record_version,
            },
        )
    changes = {
        key: value
        for key, value in submitted.items()
        if not _product_values_equal(getattr(product, key), value)
    }
    if not changes:
        return _product_to_dict(product, expose_pending_model=True)

    before = product_commercial_service.snapshot_product_fields(product)
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
    commercial_changed = bool(
        product_commercial_service.COMMERCIAL_EDIT_FIELDS.intersection(changes)
    )
    if commercial_changed:
        product.verification_status = "draft"
        product.verified_at = None
        product.verified_by = None

    _validate_product_lifecycle(product)
    if model_review_fields.intersection(changes) and product.model_url:
        product.model_status = "pending_review"
        product.model_reviewed_at = None
        product.model_reviewed_by = None
        product.model_review_note = None
    if commercial_changed:
        product_commercial_service.append_product_audit_event(
            db,
            product=product,
            event_type="commercial_patch",
            actor=f"user:{_user.id}",
            request_id=product_commercial_service.request_id_or_new(request_id),
            before=before,
        )
    db.commit()
    db.refresh(product)
    return _product_to_dict(product, expose_pending_model=True)


@router.delete("/{product_id}")
def deactivate_product(
    product_id: int,
    idempotency_key: IdempotencyKeyHeader,
    expected_record_version: int = Query(..., ge=1),
    request_id: RequestIdHeader = None,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    try:
        event = product_commercial_service.deactivate_product(
            db,
            product_id=product_id,
            expected_record_version=expected_record_version,
            actor=f"user:{_user.id}",
            request_id=product_commercial_service.request_id_or_new(request_id),
            idempotency_key=idempotency_key,
        )
    except product_commercial_service.ProductCommercialNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except product_commercial_service.ProductCommercialIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "message": str(exc)},
        ) from exc
    except product_commercial_service.ProductCommercialConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=_record_version_conflict_detail(exc),
        ) from exc
    return ProductAuditEventResponse.model_validate(event)


@router.post(
    "/{product_id}/commercial-review",
    response_model=CommercialReviewResponse,
)
def review_product_commercially(
    product_id: int,
    data: CommercialReviewRequest,
    idempotency_key: IdempotencyKeyHeader,
    request_id: RequestIdHeader = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CommercialReviewResponse:
    try:
        event = product_commercial_service.review_product(
            db,
            product_id=product_id,
            payload=data,
            actor=f"user:{user.id}",
            request_id=product_commercial_service.request_id_or_new(request_id),
            idempotency_key=idempotency_key,
        )
    except product_commercial_service.ProductCommercialNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except product_commercial_service.ProductCommercialEvidenceIncomplete as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "commercial_evidence_incomplete",
                "message": str(exc),
                "reason_codes": list(exc.reason_codes),
            },
        ) from exc
    except product_commercial_service.ProductCommercialIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "message": str(exc)},
        ) from exc
    except product_commercial_service.ProductCommercialConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=_record_version_conflict_detail(exc),
        ) from exc
    return CommercialReviewResponse.model_validate(event)


@router.get(
    "/{product_id}/audit-events",
    response_model=ProductAuditEventListResponse,
)
def get_product_audit_events(
    product_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
) -> ProductAuditEventListResponse:
    try:
        events = product_commercial_service.list_product_audit_events(
            db,
            product_id=product_id,
            limit=limit,
        )
    except product_commercial_service.ProductCommercialNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProductAuditEventListResponse(
        items=[ProductAuditEventResponse.model_validate(event) for event in events],
        count=len(events),
    )


@router.get(
    "/{product_id}/assets",
    response_model=ProductAssetListResponse,
)
def get_product_assets(
    product_id: int,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
) -> ProductAssetListResponse:
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    return ProductAssetListResponse(
        assets=[
            ProductAssetResponse.model_validate(asset)
            for asset in product_asset_service.list_product_assets(db, product_id)
        ]
    )


@router.post(
    "/{product_id}/assets",
    response_model=ProductAssetResponse,
    status_code=201,
)
def create_product_asset(
    product_id: int,
    data: ProductAssetCreate,
    user: User = Depends(require_factory),
    db: Session = Depends(get_db),
) -> ProductAssetResponse:
    try:
        asset = product_asset_service.create_product_asset(
            db,
            product_id=product_id,
            payload=data,
            actor=f"user:{user.id}",
        )
    except product_asset_service.ProductAssetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except product_asset_service.ProductAssetConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProductAssetResponse.model_validate(asset)


@router.post(
    "/{product_id}/assets/{asset_id}/review",
    response_model=ProductAssetResponse,
)
def review_product_asset(
    product_id: int,
    asset_id: int,
    data: ProductAssetReview,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductAssetResponse:
    try:
        asset = product_asset_service.review_product_asset(
            db,
            product_id=product_id,
            asset_id=asset_id,
            decision=data.decision,
            note=data.note,
            actor=f"user:{user.id}",
        )
    except product_asset_service.ProductAssetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except product_asset_service.ProductAssetConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProductAssetResponse.model_validate(asset)


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
        product_asset_service.register_uploaded_glb(
            db,
            product=product,
            actor=f"user:{_user.id}",
        )
        db.commit()
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise
    db.refresh(product)
    return _product_to_dict(product, expose_pending_model=True)


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
    try:
        asset = product_asset_service.register_uploaded_glb(
            db,
            product=product,
            actor=f"user:{user.id}",
        )
        product_asset_service.review_product_asset(
            db,
            product_id=product.id,
            asset_id=asset.id,
            decision=data.decision,
            note=(data.note or "").strip() or None,
            actor=f"user:{user.id}",
        )
    except product_asset_service.ProductAssetConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.refresh(product)
    return _product_to_dict(product, expose_pending_model=True)


# ---------------------------------------------------------------- 定制报价规则写接口


class QuoteRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)
    pricing_unit: str = Field(min_length=1, max_length=20)
    unit_price: int = Field(gt=0)
    material_grade: str = Field(min_length=1, max_length=50)
    region_codes: list[str] = Field(default_factory=list, max_length=100)
    waste_rate_bps: int = Field(default=0, ge=0, le=10000)
    minimum_quantity: float = Field(default=0, ge=0)
    installation_fee: int = Field(default=0, ge=0)
    shipping_fee: int = Field(default=0, ge=0)
    tax_rate_bps: int = Field(default=0, ge=0, le=10000)
    data_version: str = Field(default="draft-v1", min_length=1, max_length=100)
    description: Optional[str] = None


class QuoteRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(ge=1, strict=True)
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

    @model_validator(mode="after")
    def reject_null_business_fields(self):
        for field_name in self.model_fields_set - {
            "expected_record_version",
            "description",
        }:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


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
    rule = db.scalar(
        select(CustomQuoteRule)
        .where(CustomQuoteRule.id == rule_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Quote rule not found")
    if rule.record_version != data.expected_record_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "record_version_conflict",
                "message": "报价规则已被其他操作更新，请刷新后重试",
                "current_record_version": rule.record_version,
            },
        )
    for k, v in data.model_dump(
        exclude_unset=True,
        exclude={"expected_record_version"},
    ).items():
        setattr(rule, k, v)
    _normalize_quote_rule(rule)
    rule.record_version = (rule.record_version or 1) + 1
    db.commit()
    return {"id": rule.id, "status": "ok", "record_version": rule.record_version}


@router.delete("/quote-rules/{rule_id}")
def deactivate_quote_rule(
    rule_id: int,
    expected_record_version: int = Query(ge=1),
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    rule = db.scalar(
        select(CustomQuoteRule)
        .where(CustomQuoteRule.id == rule_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Quote rule not found")
    if rule.record_version != expected_record_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "record_version_conflict",
                "message": "报价规则已被其他操作更新，请刷新后重试",
                "current_record_version": rule.record_version,
            },
        )
    rule.is_active = False
    rule.record_version = (rule.record_version or 1) + 1
    db.commit()
    return {"status": "ok", "record_version": rule.record_version}
