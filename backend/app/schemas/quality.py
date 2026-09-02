"""运营质量指标的公开响应契约。"""

from datetime import datetime

from pydantic import BaseModel, Field


class GenerationQualityMetrics(BaseModel):
    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    active: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)
    fallback_rate: float | None = Field(default=None, ge=0, le=1)
    duration_p50_ms: int | None = Field(default=None, ge=0)
    duration_p95_ms: int | None = Field(default=None, ge=0)
    total_tokens: int = Field(ge=0)
    total_cost_cny: float = Field(ge=0)


class AgentQualityMetrics(BaseModel):
    turn_total: int = Field(ge=0)
    handoff_total: int = Field(ge=0)
    handoff_rate: float | None = Field(default=None, ge=0, le=1)
    statuses: dict[str, int]


class LayoutQualityMetrics(BaseModel):
    total: int = Field(ge=0)
    hard_pass_total: int = Field(ge=0)
    hard_pass_rate: float | None = Field(default=None, ge=0, le=1)
    average_score: float | None = None
    issue_codes: dict[str, int]


class QualitySummaryResponse(BaseModel):
    generated_at: datetime
    window_days: int = Field(ge=1, le=365)
    generation: GenerationQualityMetrics
    agent: AgentQualityMetrics
    layout: LayoutQualityMetrics
    failure_codes: dict[str, int]
