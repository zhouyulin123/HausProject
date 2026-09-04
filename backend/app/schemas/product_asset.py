"""商品资产登记与审核 API 契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AssetKind = Literal["image", "cad", "glb", "material"]
AssetReviewStatus = Literal[
    "pending_review",
    "approved",
    "rejected",
    "superseded",
]


class ProductAssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: AssetKind
    url: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=500)
    authorization: str = Field(min_length=1, max_length=500)

    @field_validator("url", "source", "authorization")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("资产 URL、来源和授权不能为空")
        return normalized


class ProductAssetReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ProductAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    kind: AssetKind
    url: str
    source: str | None
    authorization: str | None
    review_status: AssetReviewStatus
    reviewed_at: datetime | None
    reviewed_by: str | None
    review_note: str | None
    created_by: str
    created_at: datetime | None
    updated_at: datetime | None


class ProductAssetListResponse(BaseModel):
    assets: list[ProductAssetResponse]
