from datetime import datetime
from typing import Literal

from pydantic import BaseModel


BillingStatus = Literal["metered", "not_billable", "unknown"]
TimelineSource = Literal["agent", "generation", "effect", "blender"]


class TaskTimelineEventResponse(BaseModel):
    event_id: int
    source_type: TimelineSource
    source_id: int
    attempt: int | None = None
    event_code: str
    summary: str
    billing_status: BillingStatus
    cost_cny: float | None = None
    occurred_at: datetime


class TaskTimelineResponse(BaseModel):
    task_id: int
    events: list[TaskTimelineEventResponse]
    next_cursor: int | None = None
    next_before_id: int | None = None
    next_after_id: int | None = None
    known_cost_cny: float | None = None
    has_unknown_cost: bool
    unknown_cost_event_count: int
