"""真实案例治理收件箱的严格 API 契约。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from evals.annotations import CaseAnnotation


_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")

CaseSplit = Literal["unassigned", "development", "regression", "blind"]
RedactionReview = Literal["pending", "reviewed", "rejected"]
ConsentDecision = Literal["granted", "denied", "revoked"]
ConsentLegalBasis = Literal[
    "explicit_consent",
    "contract",
    "withdrawal_request",
]
AllowedPurpose = Literal["offline_evaluation"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseImportRequest(_StrictModel):
    client_import_id: StrictStr = Field(min_length=1, max_length=100)
    task_id: int = Field(gt=0)
    uploaded_image_id: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_import_id(self) -> "CaseImportRequest":
        value = self.client_import_id.strip()
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("client_import_id 必须是结构化标识符")
        self.client_import_id = value
        return self


class CaseImportPreviewResponse(_StrictModel):
    task_input_ready: bool
    asset_available: bool
    duplicate_asset: bool


class CaseGovernanceUpdate(_StrictModel):
    expected_version: int = Field(ge=1)
    split: CaseSplit | None = None
    redaction_review: RedactionReview | None = None

    @model_validator(mode="after")
    def require_exactly_one_action(self) -> "CaseGovernanceUpdate":
        selected = sum(
            value is not None for value in (self.split, self.redaction_review)
        )
        if selected != 1:
            raise ValueError("每次只能更新 split 或 redaction_review 中的一项")
        return self


class ConsentDecisionCreate(_StrictModel):
    expected_version: int = Field(ge=1)
    decision: ConsentDecision
    legal_basis: ConsentLegalBasis
    allowed_purposes: list[AllowedPurpose]
    evidence_digest: StrictStr | None = None
    effective_at: datetime
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_decision_evidence(self) -> "ConsentDecisionCreate":
        self.allowed_purposes = list(dict.fromkeys(self.allowed_purposes))
        if self.evidence_digest is None or not _DIGEST_PATTERN.fullmatch(
            self.evidence_digest
        ):
            raise ValueError("evidence_digest 必须是 sha256 摘要")
        if self.effective_at.tzinfo is None:
            raise ValueError("effective_at 必须包含时区")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None:
                raise ValueError("expires_at 必须包含时区")
            if self.expires_at <= self.effective_at:
                raise ValueError("expires_at 必须晚于 effective_at")
        if self.decision == "granted":
            if self.legal_basis not in {"explicit_consent", "contract"}:
                raise ValueError("授权决定缺少合法依据")
            if "offline_evaluation" not in self.allowed_purposes:
                raise ValueError("授权决定必须允许 offline_evaluation")
        else:
            if self.allowed_purposes:
                raise ValueError("拒绝或撤回授权时 allowed_purposes 必须为空")
            if self.decision == "revoked" and self.legal_basis != "withdrawal_request":
                raise ValueError("撤回授权必须使用 withdrawal_request 依据")
            if self.decision == "denied" and self.legal_basis == "withdrawal_request":
                raise ValueError("拒绝授权不能使用 withdrawal_request 依据")
        return self


class AnnotationRevisionCreate(_StrictModel):
    expected_version: int = Field(ge=1)
    annotation: CaseAnnotation


class DatasetFreezeTarget(_StrictModel):
    case_ref: StrictStr = Field(min_length=1, max_length=40)
    expected_version: int = Field(ge=1)


class DatasetFreezeRequest(_StrictModel):
    dataset_version: StrictStr = Field(min_length=1, max_length=100)
    cases: list[DatasetFreezeTarget]

    @model_validator(mode="after")
    def validate_unique_targets(self) -> "DatasetFreezeRequest":
        normalized = self.dataset_version.strip()
        if not _IDENTIFIER_PATTERN.fullmatch(normalized):
            raise ValueError("dataset_version 必须是结构化标识符")
        self.dataset_version = normalized
        refs = [item.case_ref for item in self.cases]
        if len(refs) != len(set(refs)):
            raise ValueError("冻结目标包含重复 case_ref")
        return self


class RealWorldCaseResponse(_StrictModel):
    case_ref: str
    origin: Literal["private_real"]
    split: CaseSplit
    redaction_review: RedactionReview
    consent_status: Literal["pending", "granted", "denied", "revoked", "expired"]
    annotation_status: Literal["pending", "ready"]
    record_version: int = Field(ge=1)
    blockers: list[str]
    created_at: datetime
    updated_at: datetime


class RealWorldCaseListResponse(_StrictModel):
    items: list[RealWorldCaseResponse]
    total: int = Field(ge=0)


class CaseImportResponse(_StrictModel):
    created: bool
    case: RealWorldCaseResponse


class DatasetRevisionResponse(_StrictModel):
    revision_ref: str
    schema_version: Literal["2.0"]
    dataset_version: str
    manifest_digest: str
    case_count: int = Field(ge=20)
    split_counts: dict[str, int]
    created_at: datetime


RequestId = Annotated[
    str | None,
    Field(default=None, min_length=1, max_length=100),
]
