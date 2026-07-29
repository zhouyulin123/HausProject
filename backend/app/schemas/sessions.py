from datetime import datetime

from pydantic import BaseModel


class AnonymousSessionResponse(BaseModel):
    session_id: str
    status: str
    expires_at: datetime


class SessionTaskSummary(BaseModel):
    task_id: int
    status: str
    progress: int
    space_type: str | None = None
    style: str | None = None
    created_at: datetime | None = None


class SessionTaskListResponse(BaseModel):
    tasks: list[SessionTaskSummary]
