from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AgentApprovalDecisionRequest(BaseModel):
    client_decision_id: str = Field(min_length=8, max_length=100)
    decision: Literal["approve", "reject"]
    conclusion: str = Field(min_length=1, max_length=2000)

    @field_validator("client_decision_id", "conclusion")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized


class AgentApprovalResponse(BaseModel):
    id: int
    task_id: int
    turn_id: int
    approval_type: Literal["quote_review", "construction_risk", "quality_gate"]
    status: Literal["pending", "approved", "rejected"]
    request_reason: str
    reason_code: str
    request_context: dict[str, Any]
    requested_at: datetime
    client_decision_id: str | None = None
    decision: Literal["approve", "reject"] | None = None
    conclusion: str | None = None
    decided_by_type: str | None = None
    decided_by_id: str | None = None
    decided_at: datetime | None = None


class AgentApprovalListResponse(BaseModel):
    approvals: list[AgentApprovalResponse] = Field(default_factory=list)
