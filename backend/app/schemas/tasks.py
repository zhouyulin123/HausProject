from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TaskCreate(BaseModel):
    session_id: Optional[str] = None
    image_ids: List[int] = []
    user_input: str = ""
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


class RenderRequest(BaseModel):
    plan_id: str
    style: str
    task_id: Optional[int] = None
    room_type: Optional[str] = None


class RenderResponse(BaseModel):
    image_url: str
    mode: str  # controlnet / text2img
    source: str  # sd / unavailable
