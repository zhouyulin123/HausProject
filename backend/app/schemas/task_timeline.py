from datetime import datetime
from typing import Literal

from pydantic import BaseModel


BillingStatus = Literal["metered", "not_billable", "unknown"]
TimelineSource = Literal[
    "agent",
    "requirement",
    "vision",
    "profile",
    "generation",
    "effect",
    "blender",
]


class TaskTimelineEventResponse(BaseModel):
    event_id: int
    request_id: str | None = None
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
    model_cost_limit_cny: float | None = None
    model_cost_allocated_cny: float | None = None
    model_actual_cost_cny: float | None = None
    model_unknown_cost_call_count: int = 0
    model_call_count: int = 0
