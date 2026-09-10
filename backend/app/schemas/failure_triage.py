"""管理员失败簇闭环的匿名、严格数据契约。"""

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FailureSeverity = Literal["low", "medium", "high", "critical"]
FailureStatus = Literal["open", "in_progress", "resolved", "verified"]
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


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

    schema_version: Literal["2.0"]
    report_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    taxonomy_version: str = Field(min_length=1, max_length=100)
    data_version: str = Field(min_length=1, max_length=100)
    manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    output_digests: list[str] = Field(max_length=500)
    candidate_version: str = Field(min_length=1, max_length=100)
    signature_algorithm: Literal["hmac-sha256"]
    signature_key_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    signature: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    generated_at: datetime
    failures: list[FailureTriageItem] = Field(max_length=500)

    @field_validator("taxonomy_version", "data_version", "candidate_version")
    @classmethod
    def normalize_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("版本不能为空")
        return normalized

    @field_validator("output_digests")
    @classmethod
    def validate_output_digests(cls, value: list[str]) -> list[str]:
        pattern = r"^sha256:[0-9a-f]{64}$"
        if any(re.fullmatch(pattern, item) is None for item in value):
            raise ValueError("output_digests 包含非法摘要")
        if value != sorted(set(value)):
            raise ValueError("output_digests 必须去重并排序")
        return value

    @model_validator(mode="after")
    def reject_duplicate_clusters(self) -> "FailureTriageReportRequest":
        keys = [(item.failure_type, item.code) for item in self.failures]
        if len(keys) != len(set(keys)):
            raise ValueError("报告包含重复失败项")
        return self


class FailureVerificationCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixed_version: str = Field(min_length=1, max_length=100)

    @field_validator("fixed_version")
    @classmethod
    def normalize_fixed_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("fixed_version 不能为空")
        return normalized


class FailureVerificationReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    report_type: Literal["failure_verification"]
    report_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    taxonomy_version: str = Field(min_length=1, max_length=100)
    data_version: str = Field(min_length=1, max_length=100)
    candidate_version: str = Field(min_length=1, max_length=100)
    release_gate_report_digest: str = Field(pattern=_SHA256_PATTERN)
    manifest_digests: list[str] = Field(min_length=3, max_length=3)
    evidence_digests: list[str] = Field(min_length=3, max_length=3)
    baseline_evidence_digests: list[str] = Field(min_length=3, max_length=3)
    output_digests: list[str] = Field(min_length=1, max_length=500)
    covered_splits: list[Literal["blind", "development", "regression"]]
    verified_clusters: list[FailureVerificationCluster] = Field(
        min_length=1,
        max_length=500,
    )
    signature_algorithm: Literal["hmac-sha256"]
    signature_key_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    generated_at: datetime
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("taxonomy_version", "data_version", "candidate_version")
    @classmethod
    def normalize_verification_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("版本不能为空")
        return normalized

    @field_validator(
        "manifest_digests",
        "evidence_digests",
        "baseline_evidence_digests",
        "output_digests",
    )
    @classmethod
    def validate_digest_list(cls, value: list[str]) -> list[str]:
        if any(re.fullmatch(_SHA256_PATTERN, item) is None for item in value):
            raise ValueError("摘要列表包含非法 sha256")
        if value != sorted(set(value)):
            raise ValueError("摘要列表必须排序去重")
        return value

    @field_validator("covered_splits")
    @classmethod
    def validate_covered_splits(cls, value: list[str]) -> list[str]:
        if value != ["blind", "development", "regression"]:
            raise ValueError(
                "covered_splits 必须精确为 blind/development/regression"
            )
        return value

    @field_validator("generated_at")
    @classmethod
    def require_aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generated_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def reject_duplicate_verified_clusters(self) -> "FailureVerificationReportRequest":
        fingerprints = [item.fingerprint for item in self.verified_clusters]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("verified_clusters 包含重复 fingerprint")
        return self


class FailureClusterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
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
        if not (self.model_fields_set - {"expected_version"}):
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
    record_version: int
    occurrence_count: int
    affected_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    detected_version: str
    fixed_version: str | None
    verified_version: str | None
    verification_report_id: str | None = None
    report_digest: str | None = None
    coverage_digest: str | None = None
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


class FailureVerificationSyncResponse(BaseModel):
    imported: bool
    cluster_count: int = Field(ge=0)
    report_digest: str
    coverage_digest: str
    clusters: list[FailureClusterResponse]
