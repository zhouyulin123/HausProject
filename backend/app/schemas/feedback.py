"""设计反馈事件的严格输入与输出契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FeedbackAction = Literal["adopt", "remove", "replace", "move", "final_select"]


class DesignFeedbackEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    client_event_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    action_type: FeedbackAction
    plan_version_id: int | None = Field(default=None, ge=1)
    scene_id: int | None = Field(default=None, ge=1)
    scene_version: int | None = Field(default=None, ge=1)
    room_id: str | None = Field(default=None, min_length=1, max_length=100)
    instance_id: str | None = Field(default=None, min_length=1, max_length=100)
    source_sku: str | None = Field(default=None, min_length=1, max_length=50)
    target_sku: str | None = Field(default=None, min_length=1, max_length=50)
    satisfaction_score: int | None = Field(default=None, ge=1, le=5)

    @field_validator("room_id", "instance_id", "source_sku", "target_sku")
    @classmethod
    def normalize_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("标识符不能为空")
        return normalized

    @field_validator("source_sku", "target_sku")
    @classmethod
    def normalize_sku(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "DesignFeedbackEventRequest":
        if self.action_type == "adopt":
            if self.plan_version_id is None or self.target_sku is None:
                raise ValueError("采用事件必须提供方案版本和目标 SKU")
        elif self.action_type == "remove":
            if self.plan_version_id is None or self.source_sku is None:
                raise ValueError("删除事件必须提供方案版本和原 SKU")
        elif self.action_type == "replace":
            if (
                self.plan_version_id is None
                or self.source_sku is None
                or self.target_sku is None
            ):
                raise ValueError("替换事件必须提供方案版本、原 SKU 和目标 SKU")
            if self.source_sku == self.target_sku:
                raise ValueError("替换事件的原 SKU 与目标 SKU 不能相同")
        elif self.action_type == "move":
            if (
                self.scene_id is None
                or self.scene_version is None
                or self.instance_id is None
            ):
                raise ValueError("移动事件必须提供场景、场景版本和实例 ID")
        elif self.action_type == "final_select" and self.plan_version_id is None:
            raise ValueError("最终选择事件必须提供方案版本")
        if self.action_type != "final_select" and self.satisfaction_score is not None:
            raise ValueError("满意度只允许随最终选择事件提交")
        return self


class DesignFeedbackEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    client_event_id: str
    action_type: FeedbackAction
    plan_version_id: int | None
    scene_id: int | None
    scene_version: int | None
    room_id: str | None
    instance_id: str | None
    source_sku: str | None
    target_sku: str | None
    satisfaction_score: int | None
    created_at: datetime
