"""阶段 4 真实案例治理就绪度响应契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RealWorldSplitCounts(BaseModel):
    total: int = Field(ge=0)
    eligible: int = Field(ge=0)


class RealWorldSplitReadiness(BaseModel):
    development: RealWorldSplitCounts
    regression: RealWorldSplitCounts
    blind: RealWorldSplitCounts


class RealWorldReadinessResponse(BaseModel):
    source: Literal["governance_database"]
    manifest_version: str | None = Field(min_length=1)
    dataset_id: str | None = Field(min_length=1)
    frozen_dataset_count: int = Field(ge=0)
    total: int = Field(ge=0)
    eligible_total: int = Field(ge=0)
    private_real_eligible_total: int = Field(ge=0)
    blocked_total: int = Field(ge=0)
    split_counts: RealWorldSplitReadiness
    consent_status_counts: dict[str, int]
    annotation_status_counts: dict[str, int]
    blocker_counts: dict[str, int]
    minimum_required: int = Field(default=20, ge=1)
    minimum_met: bool = Field(description="当前候选满足最低冻结门槛，不代表评测或发布通过")
    checked_at: datetime


RealWorldSplitName = Literal["development", "regression", "blind"]
