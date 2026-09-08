"""商品目录就绪度的只读响应契约。"""

from datetime import datetime

from pydantic import BaseModel, Field


class CatalogReadinessResponse(BaseModel):
    checked_at: datetime
    region: str = Field(min_length=2, max_length=20)
    total: int = Field(ge=0)
    active_total: int = Field(ge=0)
    inactive_total: int = Field(ge=0)
    eligible_total: int = Field(ge=0)
    ineligible_total: int = Field(ge=0)
    verification_status_counts: dict[str, int]
    availability_status_counts: dict[str, int]
    data_origin_counts: dict[str, int]
    reason_code_counts: dict[str, int]
