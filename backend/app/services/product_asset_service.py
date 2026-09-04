"""商品 3D 资产展示契约。

只有完成授权与人工审核的 GLB 才能进入真实资产加载路径；其余商品使用
参数化体块并携带稳定原因码，调用方不得根据 ``model_status`` 自行推断。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Literal, TypedDict
from urllib.parse import unquote, urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Product, ProductAsset
from app.schemas.product_asset import AssetKind, ProductAssetCreate


AssetMode = Literal["approved_glb", "parametric", "fallback"]
AssetFallbackReason = Literal[
    "glb_unavailable",
    "glb_pending_review",
    "glb_rejected",
    "glb_marked_failed",
    "glb_metadata_invalid",
    "asset_contract_missing",
    "catalog_product_unavailable",
    "glb_load_failed",
]
AssetReviewReason = AssetFallbackReason | Literal["review_evidence_missing"]

_ALLOWED_EXTENSIONS: dict[AssetKind, frozenset[str]] = {
    "image": frozenset({".jpg", ".jpeg", ".png", ".webp", ".avif"}),
    "cad": frozenset({".dwg", ".dxf", ".step", ".stp", ".iges", ".igs"}),
    "glb": frozenset({".glb"}),
    "material": frozenset({".jpg", ".jpeg", ".png", ".webp", ".pdf", ".json"}),
}


class ProductAssetNotFound(ValueError):
    pass


class ProductAssetConflict(ValueError):
    pass


class AssetReviewState(TypedDict):
    status: Literal["approved", "unavailable"]
    reason_code: AssetReviewReason | None


class ProductAssetContract(TypedDict):
    asset_mode: AssetMode
    fallback_reason: AssetFallbackReason | None
    approved_model_url: str | None
    asset_review: dict[
        Literal["image", "cad", "glb", "material"],
        AssetReviewState,
    ]


def _normalized_asset_url(value: str, kind: AssetKind) -> str:
    normalized = unquote(value.strip())
    parsed = urlsplit(normalized)
    if (
        "\\" in normalized
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.scheme not in {"", "https"}
    ):
        raise ProductAssetConflict("资产 URL 必须是无凭据、无查询参数的站内或 HTTPS 地址")
    if parsed.scheme == "" and not parsed.path.startswith("/"):
        raise ProductAssetConflict("站内资产 URL 必须以 / 开头")
    path = PurePosixPath(parsed.path)
    if ".." in path.parts or path.suffix.lower() not in _ALLOWED_EXTENSIONS[kind]:
        raise ProductAssetConflict(f"{kind} 资产 URL 的路径或扩展名不合法")
    return value.strip()


def list_product_assets(db: Session, product_id: int) -> list[ProductAsset]:
    return list(
        db.scalars(
            select(ProductAsset)
            .where(ProductAsset.product_id == product_id)
            .order_by(ProductAsset.id)
        ).all()
    )


def create_product_asset(
    db: Session,
    *,
    product_id: int,
    payload: ProductAssetCreate,
    actor: str,
) -> ProductAsset:
    product = db.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise ProductAssetNotFound("商品不存在")
    if payload.kind == "glb":
        raise ProductAssetConflict("GLB 资产必须通过模型上传接口完成文件校验")
    url = _normalized_asset_url(payload.url, payload.kind)
    asset = ProductAsset(
        product_id=product.id,
        kind=payload.kind,
        url=url,
        source=payload.source,
        authorization=payload.authorization,
        review_status="pending_review",
        created_by=actor,
    )
    db.add(asset)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ProductAssetConflict("同一商品已登记相同资产") from exc
    db.refresh(asset)
    return asset


def register_uploaded_glb(
    db: Session,
    *,
    product: Product,
    actor: str,
) -> ProductAsset:
    if not product.model_url:
        raise ProductAssetConflict("商品没有已上传的 GLB")
    url = _normalized_asset_url(product.model_url, "glb")
    asset = db.scalar(
        select(ProductAsset).where(
            ProductAsset.product_id == product.id,
            ProductAsset.kind == "glb",
            ProductAsset.url == url,
        )
    )
    if asset is None:
        asset = ProductAsset(
            product_id=product.id,
            kind="glb",
            url=url,
            created_by=actor,
        )
        db.add(asset)
    asset.source = product.model_source
    asset.authorization = product.model_license
    asset.review_status = "pending_review"
    asset.reviewed_at = None
    asset.reviewed_by = None
    asset.review_note = None
    db.flush()
    return asset


def review_product_asset(
    db: Session,
    *,
    product_id: int,
    asset_id: int,
    decision: Literal["approve", "reject"],
    note: str | None,
    actor: str,
    commit: bool = True,
) -> ProductAsset:
    product = db.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise ProductAssetNotFound("商品不存在")
    asset = db.scalar(
        select(ProductAsset).where(
            ProductAsset.id == asset_id,
            ProductAsset.product_id == product_id,
        )
    )
    if asset is None:
        raise ProductAssetNotFound("商品资产不存在")
    if not _has_text(asset.source) or not _has_text(asset.authorization):
        raise ProductAssetConflict("资产来源和授权不完整")
    _normalized_asset_url(asset.url, asset.kind)

    now = datetime.now(timezone.utc)
    if decision == "approve":
        for previous in db.scalars(
            select(ProductAsset).where(
                ProductAsset.product_id == product_id,
                ProductAsset.kind == asset.kind,
                ProductAsset.review_status == "approved",
                ProductAsset.id != asset.id,
            )
        ):
            previous.review_status = "superseded"
        asset.review_status = "approved"
    else:
        asset.review_status = "rejected"
    asset.reviewed_at = now
    asset.reviewed_by = actor
    asset.review_note = note

    if asset.kind == "image" and decision == "approve":
        product.image_url = asset.url
    if asset.kind == "glb" and product.model_url == asset.url:
        product.model_status = "ready" if decision == "approve" else "rejected"
        product.model_source = asset.source
        product.model_license = asset.authorization
        product.model_reviewed_at = now
        product.model_reviewed_by = actor
        product.model_review_note = note
    if commit:
        db.commit()
        db.refresh(asset)
    else:
        db.flush()
    return asset


def public_product_assets(product: Any) -> list[dict[str, Any]]:
    assets = getattr(product, "assets", ()) or ()
    return [
        {
            "id": asset.id,
            "kind": asset.kind,
            "url": asset.url,
            "source": asset.source,
            "authorization": asset.authorization,
            "reviewed_at": asset.reviewed_at,
        }
        for asset in assets
        if asset.review_status == "approved"
    ]


def approved_product_asset(product: Any, kind: AssetKind) -> ProductAsset | None:
    """返回指定类型最后获批的审核事实，不回退到旧商品字段。"""
    return next(
        (
            asset
            for asset in reversed(getattr(product, "assets", ()) or ())
            if asset.kind == kind and asset.review_status == "approved"
        ),
        None,
    )


def approved_product_asset_url(product: Any, kind: AssetKind) -> str | None:
    asset = approved_product_asset(product, kind)
    return asset.url if asset is not None else None


def _has_positive_dimensions(product: Any) -> bool:
    dimensions = (
        getattr(product, "model_width_mm", None),
        getattr(product, "model_height_mm", None),
        getattr(product, "model_depth_mm", None),
    )
    return all(
        isinstance(value, (int, float)) and value > 0
        for value in dimensions
    )


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_deliverable_glb_url(value: Any) -> bool:
    if not _has_text(value):
        return False
    url = unquote(value.strip())
    if "\\" in url or "://" in url or "?" in url or "#" in url:
        return False
    if not url.startswith(("/models/", "/uploads/models/")):
        return False
    path = PurePosixPath(url)
    return ".." not in path.parts and path.suffix.lower() == ".glb"


def _review_states(
    *,
    product: Any,
    glb_approved: bool,
    glb_reason: AssetFallbackReason | None,
) -> dict[Literal["image", "cad", "glb", "material"], AssetReviewState]:
    missing_review: AssetReviewState = {
        "status": "unavailable",
        "reason_code": "review_evidence_missing",
    }
    approved_kinds = {
        asset.kind
        for asset in (getattr(product, "assets", ()) or ())
        if asset.review_status == "approved"
    }
    return {
        "image": (
            {"status": "approved", "reason_code": None}
            if "image" in approved_kinds
            else dict(missing_review)
        ),
        "cad": (
            {"status": "approved", "reason_code": None}
            if "cad" in approved_kinds
            else dict(missing_review)
        ),
        "glb": {
            "status": "approved" if glb_approved else "unavailable",
            "reason_code": None if glb_approved else glb_reason,
        },
        "material": (
            {"status": "approved", "reason_code": None}
            if "material" in approved_kinds
            else dict(missing_review)
        ),
    }


def product_asset_contract(product: Any) -> ProductAssetContract:
    """基于服务端审核事实裁决 Web、方案快照与 Blender 的资产。"""
    glb_assets = [
        asset
        for asset in (getattr(product, "assets", ()) or ())
        if asset.kind == "glb"
    ]
    approved_glb = next(
        (
            asset
            for asset in reversed(glb_assets)
            if asset.review_status == "approved"
        ),
        None,
    )
    if approved_glb is not None:
        if not _has_positive_dimensions(product) or not (
            _has_text(approved_glb.authorization)
            and _has_text(approved_glb.source)
            and approved_glb.reviewed_at is not None
            and _has_text(approved_glb.reviewed_by)
            and _is_deliverable_glb_url(approved_glb.url)
        ):
            reason: AssetFallbackReason = "glb_metadata_invalid"
        else:
            return {
                "asset_mode": "approved_glb",
                "fallback_reason": None,
                "approved_model_url": approved_glb.url.strip(),
                "asset_review": _review_states(
                    product=product,
                    glb_approved=True,
                    glb_reason=None,
                ),
            }
    elif glb_assets:
        latest_status = glb_assets[-1].review_status
        reason = (
            "glb_rejected"
            if latest_status == "rejected"
            else "glb_pending_review"
            if latest_status == "pending_review"
            else "glb_unavailable"
        )
        return {
            "asset_mode": "parametric",
            "fallback_reason": reason,
            "approved_model_url": None,
            "asset_review": _review_states(
                product=product,
                glb_approved=False,
                glb_reason=reason,
            ),
        }

    status = getattr(product, "model_status", None) or "missing"
    if status == "pending_review":
        reason: AssetFallbackReason = "glb_pending_review"
    elif status == "rejected":
        reason = "glb_rejected"
    elif status == "failed":
        reason = "glb_marked_failed"
    elif status != "ready" or not getattr(product, "model_url", None):
        reason = "glb_unavailable"
    elif not _has_positive_dimensions(product):
        reason = "glb_metadata_invalid"
    elif not (
        _has_text(getattr(product, "model_license", None))
        and _has_text(getattr(product, "model_source", None))
        and getattr(product, "model_reviewed_at", None) is not None
        and _has_text(getattr(product, "model_reviewed_by", None))
    ):
        reason = "glb_pending_review"
    elif not _is_deliverable_glb_url(product.model_url):
        reason = "glb_metadata_invalid"
    else:
        return {
            "asset_mode": "approved_glb",
            "fallback_reason": None,
            "approved_model_url": product.model_url.strip(),
            "asset_review": _review_states(
                product=product,
                glb_approved=True,
                glb_reason=None,
            ),
        }
    return {
        "asset_mode": "parametric",
        "fallback_reason": reason,
        "approved_model_url": None,
        "asset_review": _review_states(
            product=product,
            glb_approved=False,
            glb_reason=reason,
        ),
    }
