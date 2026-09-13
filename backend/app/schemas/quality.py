"""运营质量指标的公开响应契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


VersionDimension = Literal[
    "model",
    "prompt_digest",
    "rules_digest",
    "data_digest",
]


class NodeLatencyMetrics(BaseModel):
    samples: int = Field(ge=1)
    p50_ms: int = Field(ge=0)
    p95_ms: int = Field(ge=0)


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
    node_latency: dict[str, NodeLatencyMetrics]


class GenerationVersionCohortItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    prompt_digest: str | None = None
    rules_digest: str | None = None
    data_digest: str | None = None
    version_complete: bool
    missing_dimensions: list[VersionDimension]
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
    known_cost_cny: float = Field(ge=0)
    unknown_cost_run_count: int = Field(ge=0)


class GenerationVersionCohorts(BaseModel):
    total_cohorts: int = Field(ge=0)
    returned_cohorts: int = Field(ge=0)
    truncated: bool
    items: list[GenerationVersionCohortItem]


class AgentQualityMetrics(BaseModel):
    turn_total: int = Field(ge=0)
    handoff_total: int = Field(ge=0)
    handoff_rate: float | None = Field(default=None, ge=0, le=1)
    statuses: dict[str, int]


class ModelCallQualityMetrics(BaseModel):
    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    blocked: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    known_actual_cost_cny: float = Field(ge=0)
    unknown_cost_call_count: int = Field(ge=0)
    provider_failures: dict[str, int]


class LayoutQualityMetrics(BaseModel):
    total: int = Field(ge=0)
    hard_pass_total: int = Field(ge=0)
    hard_pass_rate: float | None = Field(default=None, ge=0, le=1)
    average_score: float | None = None
    issue_codes: dict[str, int]


class FeedbackActionCounts(BaseModel):
    adopt: int = Field(ge=0)
    remove: int = Field(ge=0)
    replace: int = Field(ge=0)
    move: int = Field(ge=0)
    final_select: int = Field(ge=0)


class FeedbackQualityMetrics(BaseModel):
    total: int = Field(ge=0)
    action_counts: FeedbackActionCounts
    modification_total: int = Field(ge=0)
    modification_rate: float | None = Field(default=None, ge=0, le=1)
    final_select_total: int = Field(ge=0)
    satisfaction_count: int = Field(ge=0)
    satisfaction_mean: float | None = Field(default=None, ge=1, le=5)
    glb_load_failure_total: int = Field(ge=0)


class RenderQueueQualityMetrics(BaseModel):
    total: int = Field(ge=0)
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    dead_letter: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)
    queue_wait_p50_ms: int | None = Field(default=None, ge=0)
    queue_wait_p95_ms: int | None = Field(default=None, ge=0)
    execution_p50_ms: int | None = Field(default=None, ge=0)
    execution_p95_ms: int | None = Field(default=None, ge=0)


class QualitySummaryResponse(BaseModel):
    generated_at: datetime
    window_days: int = Field(ge=1, le=365)
    generation: GenerationQualityMetrics
    version_cohorts: GenerationVersionCohorts
    agent: AgentQualityMetrics
    model_calls: ModelCallQualityMetrics
    layout: LayoutQualityMetrics
    feedback: FeedbackQualityMetrics
    effect_render: RenderQueueQualityMetrics
    blender_render: RenderQueueQualityMetrics
    failure_codes: dict[str, int]
