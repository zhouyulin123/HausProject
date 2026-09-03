"""商品 3D 资产展示契约。

只有完成授权与人工审核的 GLB 才能进入真实资产加载路径；其余商品使用
参数化体块并携带稳定原因码，调用方不得根据 ``model_status`` 自行推断。
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal, TypedDict
from urllib.parse import unquote


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
    glb_approved: bool,
    glb_reason: AssetFallbackReason | None,
) -> dict[Literal["image", "cad", "glb", "material"], AssetReviewState]:
    missing_review: AssetReviewState = {
        "status": "unavailable",
        "reason_code": "review_evidence_missing",
    }
    return {
        "image": dict(missing_review),
        "cad": dict(missing_review),
        "glb": {
            "status": "approved" if glb_approved else "unavailable",
            "reason_code": None if glb_approved else glb_reason,
        },
        "material": dict(missing_review),
    }


def product_asset_contract(product: Any) -> ProductAssetContract:
    """基于服务端审核事实裁决 Web、方案快照与 Blender 的资产。"""
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
                glb_approved=True,
                glb_reason=None,
            ),
        }
    return {
        "asset_mode": "parametric",
        "fallback_reason": reason,
        "approved_model_url": None,
        "asset_review": _review_states(
            glb_approved=False,
            glb_reason=reason,
        ),
    }
