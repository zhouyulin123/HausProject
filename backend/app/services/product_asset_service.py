"""商品 3D 资产展示契约。

只有完成授权与人工审核的 GLB 才能进入真实资产加载路径；其余商品使用
参数化体块并携带稳定原因码，调用方不得根据 ``model_status`` 自行推断。
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


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


class ProductAssetContract(TypedDict):
    asset_mode: AssetMode
    fallback_reason: AssetFallbackReason | None


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


def product_asset_contract(product: Any) -> ProductAssetContract:
    """基于服务端审核事实裁决商品的 Web 3D 展示模式。"""
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
    else:
        return {"asset_mode": "approved_glb", "fallback_reason": None}
    return {"asset_mode": "parametric", "fallback_reason": reason}
