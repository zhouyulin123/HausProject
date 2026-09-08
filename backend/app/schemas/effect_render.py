from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EffectRenderStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "dead_letter",
    "cancelled",
    "provider_unavailable",
]


class EffectRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(ge=1)
    plan_version_id: int = Field(ge=1)
    scene_id: int = Field(ge=1)
    scene_version: int = Field(ge=1)


class EffectRenderJobResponse(BaseModel):
    job_id: int
    request_id: str | None = None
    task_id: int
    plan_version_id: int
    scene_id: int | None = None
    scene_version_id: int | None = None
    scene_version: int | None = None
    scene_digest: str | None = None
    status: EffectRenderStatus
    progress: int
    attempt_count: int
    max_attempts: int
    image_url: str | None = None
    mode: str | None = None
    error_message: str | None = None
    cancel_requested_at: datetime | None = None
    next_retry_at: datetime | None = None
    execution_deadline_at: datetime
    dead_lettered_at: datetime | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
