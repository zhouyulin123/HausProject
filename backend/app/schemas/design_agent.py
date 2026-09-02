from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.custom_furniture import CustomFurnitureSpecPatch


ActiveMode = Literal[
    "catalog_design",
    "custom_furniture",
    "room_reconstruction",
]


class AgentFactsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_type: str | None = Field(default=None, min_length=1, max_length=50)
    style: str | None = Field(default=None, min_length=1, max_length=50)
    budget_min: int | None = Field(default=None, ge=0, le=100_000_000)
    budget_max: int | None = Field(default=None, gt=0, le=100_000_000)
    room_width_m: float | None = Field(default=None, gt=0, le=50)
    room_depth_m: float | None = Field(default=None, gt=0, le=50)
    ceiling_height_m: float | None = Field(default=None, ge=1.8, le=8)

    @model_validator(mode="after")
    def validate_budget_range(self) -> "AgentFactsPatch":
        if (
            self.budget_min is not None
            and self.budget_max is not None
            and self.budget_min > self.budget_max
        ):
            raise ValueError("budget_min 不能大于 budget_max")
        return self


class AgentTurnRequest(BaseModel):
    client_turn_id: str = Field(min_length=8, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    active_mode: ActiveMode = "catalog_design"
    active_room_id: str | None = Field(default=None, max_length=100)
    scene_id: int | None = Field(default=None, ge=1)
    base_scene_version: int | None = Field(default=None, ge=1)
    selected_instance_id: str | None = Field(default=None, max_length=100)
    answers: AgentFactsPatch | None = None
    custom_furniture_spec: CustomFurnitureSpecPatch | None = None

    @model_validator(mode="after")
    def validate_scene_context(self) -> "AgentTurnRequest":
        supplied = (
            self.scene_id is not None,
            self.base_scene_version is not None,
        )
        if any(supplied) and not all(supplied):
            raise ValueError("scene_id 与 base_scene_version 必须同时提供")
        return self


class AgentPendingQuestion(BaseModel):
    field: str
    prompt: str
    reason: str


class AgentToolEventResponse(BaseModel):
    sequence: int
    type: str
    node: str
    status: str
    source: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class AgentMessageResponse(BaseModel):
    id: int
    role: Literal["user", "ai"]
    content: str
    created_at: datetime | None = None


class AgentStateResponse(BaseModel):
    status: str
    current_node: str
    active_room_id: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    step_count: int = 0
    retry_count: int = 0
    max_steps: int = 12
    max_retries: int = 2
    pending_questions: list[AgentPendingQuestion] = Field(default_factory=list)
    hard_errors: list[str] = Field(default_factory=list)
    custom_furniture_spec: dict[str, Any] | None = None
    approval_required: bool = False
    exit_reason: str


class AgentTurnResponse(BaseModel):
    task_id: int
    turn_id: int
    state_version: int
    status: str
    active_mode: ActiveMode
    active_room_id: str | None = None
    intent: str
    reply: str
    state: AgentStateResponse
    pending_questions: list[AgentPendingQuestion] = Field(default_factory=list)
    events: list[AgentToolEventResponse] = Field(default_factory=list)
    approval_required: bool = False
    exit_reason: str
    scene_ref: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


class AgentCheckpointResponse(BaseModel):
    task_id: int
    state_version: int
    status: str
    active_mode: ActiveMode
    active_room_id: str | None = None
    intent: str
    current_node: str
    facts: dict[str, Any] = Field(default_factory=dict)
    pending_questions: list[AgentPendingQuestion] = Field(default_factory=list)
    step_count: int = 0
    retry_count: int = 0
    max_steps: int = 12
    max_retries: int = 2
    hard_errors: list[str] = Field(default_factory=list)
    custom_furniture_spec: dict[str, Any] | None = None
    approval_required: bool = False
    exit_reason: str
    scene_ref: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    messages: list[AgentMessageResponse] = Field(default_factory=list)
