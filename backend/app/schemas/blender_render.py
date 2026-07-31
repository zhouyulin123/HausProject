"""Blender 高质量场景渲染作业的 API 契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.scenes import SceneModel


RenderProfile = Literal["preview", "final"]
RenderJobStatus = Literal["queued", "running", "completed", "failed"]


class BlenderRenderRequest(SceneModel):
    base_version: int = Field(ge=1)
    profile: RenderProfile = "preview"


class BlenderRenderJobResponse(BaseModel):
    id: int
    scene_id: int
    scene_version: int
    profile: RenderProfile
    status: RenderJobStatus
    progress: int
    attempt: int
    output_url: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
