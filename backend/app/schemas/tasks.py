from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.feedback import DesignFeedbackEventResponse
from app.schemas.scenes import SceneResponse, Transform


class TaskCreate(BaseModel):
    session_id: Optional[str] = None
    image_ids: List[int] = []
    user_input: str = ""
    active_mode: Literal[
        "catalog_design",
        "custom_furniture",
        "room_reconstruction",
    ] = "catalog_design"
    # 前端定制表单收集的结构化需求；提供时跳过解析直接确认
    requirement: Optional[Dict[str, Any]] = None


class TaskResponse(BaseModel):
    task_id: int
    status: str


class RequirementResponse(BaseModel):
    parsed_requirement: Dict[str, Any]
    missing_fields: List[str]
    follow_up_questions: List[str]
    parser: str  # llm / rule


class ConfirmRequirementRequest(BaseModel):
    confirmed_requirement: Dict[str, Any]


class GenerateResponse(BaseModel):
    task_id: int
    status: str
    generator: str  # llm / template


class GenerationQueuedResponse(BaseModel):
    run_id: int
    status: Literal[
        "queued",
        "running",
        "completed",
        "failed",
        "dead_letter",
        "cost_limit_exceeded",
        "provider_unavailable",
        "cancelled",
    ]


class GenerationEventResponse(BaseModel):
    node: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    progress: int
    source: Optional[str] = None
    duration_ms: Optional[int] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class GenerationStatusResponse(BaseModel):
    run_id: int
    request_id: Optional[str] = None
    attempt: int
    attempt_count: int
    max_attempts: int
    status: str
    progress: int
    current_node: Optional[str] = None
    generator: Optional[str] = None
    error_message: Optional[str] = None
    cancel_requested_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    execution_deadline_at: Optional[datetime] = None
    dead_lettered_at: Optional[datetime] = None
    cost_cny: Optional[float] = None
    cost_reserved_cny: float = 0.0
    cost_limit_cny: Optional[float] = None
    result_revision_id: Optional[int] = None
    output_digest: Optional[str] = None
    events: List[GenerationEventResponse] = Field(default_factory=list)


class TaskStatusResponse(BaseModel):
    task_id: int
    status: str
    progress: int


class TaskResultResponse(BaseModel):
    plans: List[Dict[str, Any]]
    generator: str
    revision_version: Optional[int] = None
    images: List[Dict[str, Any]] = []
    pdf_url: Optional[str] = None


class DesignRevisionSummary(BaseModel):
    version: int
    generator: str
    status: str
    plan_count: int
    quote_min: int
    quote_max: int
    created_at: Optional[datetime] = None


class DesignRevisionListResponse(BaseModel):
    revisions: List[DesignRevisionSummary]


class DesignRevisionDetailResponse(BaseModel):
    version: int
    generator: str
    status: str
    requirement: Dict[str, Any]
    image_context: List[str]
    workflow_trace: List[Dict[str, Any]]
    plans: List[Dict[str, Any]]
    created_at: Optional[datetime] = None


class ChatRequest(BaseModel):
    message: str
    task_id: Optional[int] = None
    history: List[Dict[str, str]] = []
    requirement: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    reply: str
    source: str  # llm
    task_id: int


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(ge=1)
    plan_version_id: int = Field(ge=1)


class RenderResponse(BaseModel):
    image_url: str
    mode: str  # controlnet / text2img
    source: str  # sd / unavailable


class RefinePlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=500)


class RefinePlanResponse(BaseModel):
    plan: Dict[str, Any]
    version: int
    message: str = ""


class PlanMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_mutation_id: str = Field(
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    base_revision_version: int = Field(ge=1)
    plan_version_id: int = Field(ge=1)
    action: Literal["adopt", "remove", "replace"]
    source_instance_id: str | None = Field(default=None, min_length=1, max_length=100)
    target_sku: str | None = Field(default=None, min_length=1, max_length=50)
    placement_mode: Literal["auto_place", "explicit"] | None = None
    placement_transform: Transform | None = None
    room_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "PlanMutationRequest":
        if self.action == "adopt":
            if self.target_sku is None or self.placement_mode is None:
                raise ValueError("采用商品必须提供 target_sku 和 placement_mode")
            if self.placement_mode == "explicit" and self.placement_transform is None:
                raise ValueError("显式落位必须提供 placement_transform")
        elif self.action == "remove" and self.source_instance_id is None:
            raise ValueError("移除商品必须提供 source_instance_id")
        elif self.action == "replace" and (
            self.source_instance_id is None or self.target_sku is None
        ):
            raise ValueError("替换商品必须提供 source_instance_id 和 target_sku")
        return self


class PlanMutationResponse(BaseModel):
    revision_version: int
    plan: Dict[str, Any]
    scene: SceneResponse
    feedback: DesignFeedbackEventResponse
