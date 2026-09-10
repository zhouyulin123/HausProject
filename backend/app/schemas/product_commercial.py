"""商品商业审核与审计 API 契约。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommercialReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    expected_record_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_rejection_note(self):
        if self.decision == "reject" and not (self.note or "").strip():
            raise ValueError("拒绝商业核验时必须填写原因")
        return self


class ProductAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    event_type: str
    actor: str
    request_id: str
    changed_fields: list[str]
    changes: dict[str, dict[str, Any]]
    decision: str | None
    resulting_status: str
    resulting_record_version: int
    created_at: datetime


class ProductAuditEventListResponse(BaseModel):
    items: list[ProductAuditEventResponse]
    count: int


class CommercialReviewResponse(ProductAuditEventResponse):
    pass
