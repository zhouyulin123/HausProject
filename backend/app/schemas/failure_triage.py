"""管理员失败簇闭环的匿名、严格数据契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FailureSeverity = Literal["low", "medium", "high", "critical"]
FailureStatus = Literal["open", "in_progress", "resolved", "verified"]


class FailureTriageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_type: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9._:-]+$")
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9._:-]+$")
    severity: FailureSeverity
    occurrence_count: int = Field(ge=1)
    affected_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_counts(self) -> "FailureTriageItem":
        if self.affected_count > self.occurrence_count:
            raise ValueError("affected_count 不能大于 occurrence_count")
        return self


class FailureTriageReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    report_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    verification_status: Literal["verified"]
    taxonomy_version: str = Field(min_length=1, max_length=100)
    data_version: str = Field(min_length=1, max_length=100)
    candidate_version: str = Field(min_length=1, max_length=100)
    generated_at: datetime
    failures: list[FailureTriageItem] = Field(max_length=500)

    @field_validator("taxonomy_version", "data_version", "candidate_version")
    @classmethod
    def normalize_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("版本不能为空")
        return normalized

    @model_validator(mode="after")
    def reject_duplicate_clusters(self) -> "FailureTriageReportRequest":
        keys = [(item.failure_type, item.code) for item in self.failures]
        if len(keys) != len(set(keys)):
            raise ValueError("报告包含重复失败项")
        return self


class FailureClusterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: FailureStatus | None = None
    owner: str | None = Field(default=None, min_length=1, max_length=100)
    fixed_version: str | None = Field(default=None, min_length=1, max_length=100)
    verified_version: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("owner", "fixed_version", "verified_version")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized

    @model_validator(mode="after")
    def require_an_update(self) -> "FailureClusterUpdate":
        if not self.model_fields_set:
            raise ValueError("至少提供一个更新字段")
        return self


class FailureClusterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fingerprint: str
    taxonomy_version: str
    data_version: str
    failure_type: str
    code: str
    severity: FailureSeverity
    status: FailureStatus
    owner: str | None
    occurrence_count: int
    affected_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    detected_version: str
    fixed_version: str | None
    verified_version: str | None
    created_at: datetime
    updated_at: datetime


class FailureClusterSummary(BaseModel):
    total: int = Field(ge=0)
    by_status: dict[str, int]
    by_severity: dict[str, int]


class FailureClusterListResponse(BaseModel):
    items: list[FailureClusterResponse]
    summary: FailureClusterSummary


class FailureTriageSyncResponse(BaseModel):
    imported: bool
    cluster_count: int = Field(ge=0)
    clusters: list[FailureClusterResponse]
