"""真实案例人工标注资产的严格、可冻结数据契约。"""

from __future__ import annotations

from hashlib import sha256
import hmac
import json
import math
from pathlib import Path
import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)


ANNOTATION_SCHEMA_VERSION = "1.0"
ANNOTATION_TYPE = "real_world_case_annotation"
MAX_ANNOTATION_BYTES = 2 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
_FACT_PATH_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_-]*)+$"
)
_DOCUMENT_FIELDS = {
    "schema_version",
    "annotation_type",
    "case_id",
    "label_version",
    "source_asset_sha256",
    "requirements",
    "space_facts",
    "allowed_skus",
    "budget",
    "layout_hard_constraints",
    "style_tags",
    "human_evaluation",
}
_PII_OR_FREE_TEXT_FIELDS = {
    "address",
    "annotator",
    "annotator_name",
    "comment",
    "conversation",
    "email",
    "free_text",
    "id_card",
    "message",
    "name",
    "note",
    "notes",
    "phone",
    "prompt",
    "raw_text",
    "raw_user_input",
    "reviewer",
    "reviewer_name",
    "transcript",
    "wechat",
}


class AnnotationValidationError(ValueError):
    """标注文件不满足版本、来源、结构或隐私约束。"""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ScalarValue = StrictBool | StrictInt | StrictFloat | StrictStr
NumericValue = StrictInt | StrictFloat


def _label(value: str, field_name: str, *, identifier: bool = False) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空")
    if len(normalized) > 100 or any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{field_name} 不是合法短标签")
    if identifier and not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} 必须是结构化标识符")
    return normalized


class RequirementFact(_StrictModel):
    field: Literal[
        "space_type",
        "primary_use",
        "delivery_region",
        "occupant_count",
        "room_count",
        "has_children",
        "has_pets",
        "accessibility_required",
        "storage_priority",
    ]
    value: ScalarValue

    @model_validator(mode="after")
    def validate_value_for_field(self) -> "RequirementFact":
        label_fields = {
            "space_type",
            "primary_use",
            "delivery_region",
            "storage_priority",
        }
        count_fields = {"occupant_count", "room_count"}
        boolean_fields = {
            "has_children",
            "has_pets",
            "accessibility_required",
        }
        if self.field in label_fields:
            if not isinstance(self.value, str):
                raise ValueError(f"requirements.{self.field} 必须是标签")
            _label(self.value, f"requirements.{self.field}")
        elif self.field in count_fields:
            if (
                isinstance(self.value, bool)
                or not isinstance(self.value, int)
                or self.value <= 0
            ):
                raise ValueError(f"requirements.{self.field} 必须是正整数")
        elif self.field in boolean_fields and not isinstance(self.value, bool):
            raise ValueError(f"requirements.{self.field} 必须是布尔值")
        return self


class SpaceFact(_StrictModel):
    fact_path: StrictStr
    value: ScalarValue
    confidence: Annotated[StrictFloat, Field(ge=0, le=1)]
    requires_confirmation: StrictBool

    @field_validator("fact_path")
    @classmethod
    def validate_fact_path(cls, value: str) -> str:
        normalized = value.strip()
        if not _FACT_PATH_PATTERN.fullmatch(normalized):
            raise ValueError("space_facts.fact_path 必须是结构化事实路径")
        return normalized

    @field_validator("value")
    @classmethod
    def validate_fact_value(cls, value: ScalarValue) -> ScalarValue:
        if isinstance(value, str):
            return _label(value, "space_facts.value")
        return value


class BudgetAnnotation(_StrictModel):
    currency: Literal["CNY"]
    minimum: StrictInt = Field(alias="min", ge=0)
    maximum: StrictInt = Field(alias="max", gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> "BudgetAnnotation":
        if self.minimum > self.maximum:
            raise ValueError("budget.min 不能大于 budget.max")
        return self


class LayoutHardConstraint(_StrictModel):
    constraint_id: StrictStr
    type: Literal[
        "minimum_clearance",
        "inside_room",
        "no_overlap",
        "door_swing_clearance",
        "walkway_width",
        "wall_offset",
        "maximum_occupancy",
    ]
    room_id: StrictStr
    subject_id: StrictStr
    related_id: StrictStr | None
    operator: Literal["gte", "lte", "eq"]
    value: StrictBool | NumericValue
    unit: Literal["mm", "degree", "count", "boolean"]

    @field_validator("constraint_id", "room_id", "subject_id", "related_id")
    @classmethod
    def validate_identifier(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _label(value, f"layout_hard_constraints.{info.field_name}", identifier=True)

    @model_validator(mode="after")
    def validate_value_unit(self) -> "LayoutHardConstraint":
        if self.unit == "boolean":
            if not isinstance(self.value, bool) or self.operator != "eq":
                raise ValueError(
                    "layout_hard_constraints 的 boolean 值必须配合 eq"
                )
        elif isinstance(self.value, bool):
            raise ValueError("layout_hard_constraints 数值单位不能使用布尔值")
        return self


class HumanDimensionScore(_StrictModel):
    metric: Literal[
        "functional_fit",
        "style_match",
        "layout_quality",
        "budget_fit",
        "overall_satisfaction",
    ]
    score: StrictInt = Field(ge=1, le=5)


class HumanEditFact(_StrictModel):
    edit_id: StrictStr
    action: Literal[
        "add",
        "remove",
        "move",
        "rotate",
        "replace",
        "quantity",
        "resize",
    ]
    target_type: Literal["furniture", "room", "opening"]
    target_id: StrictStr
    axis: Literal["x", "y", "z"] | None
    delta_mm: NumericValue | None
    delta_degrees: NumericValue | None
    replacement_sku: StrictStr | None
    quantity_delta: StrictInt | None

    @field_validator("edit_id", "target_id")
    @classmethod
    def validate_identifier(cls, value: str, info) -> str:
        return _label(
            value,
            f"human_evaluation.edit_facts.{info.field_name}",
            identifier=True,
        )

    @field_validator("replacement_sku")
    @classmethod
    def validate_replacement_sku(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _label(
            value,
            "human_evaluation.edit_facts.replacement_sku",
            identifier=True,
        )

    @model_validator(mode="after")
    def validate_action_payload(self) -> "HumanEditFact":
        error = "human_evaluation.edit_facts 与 action 不匹配"
        if self.action in {"move", "resize"}:
            if (
                self.axis is None
                or self.delta_mm in (None, 0)
                or self.delta_degrees is not None
                or self.replacement_sku is not None
                or self.quantity_delta is not None
            ):
                raise ValueError(error)
        elif self.action == "rotate":
            if (
                self.axis is None
                or self.delta_degrees in (None, 0)
                or self.delta_mm is not None
                or self.replacement_sku is not None
                or self.quantity_delta is not None
            ):
                raise ValueError(error)
        elif self.action == "replace":
            if (
                self.replacement_sku is None
                or self.axis is not None
                or self.delta_mm is not None
                or self.delta_degrees is not None
                or self.quantity_delta is not None
            ):
                raise ValueError(error)
        elif self.action == "quantity":
            if (
                self.quantity_delta in (None, 0)
                or self.axis is not None
                or self.delta_mm is not None
                or self.delta_degrees is not None
                or self.replacement_sku is not None
            ):
                raise ValueError(error)
        elif self.action == "add":
            if (
                self.replacement_sku is None
                or self.quantity_delta is None
                or self.quantity_delta <= 0
                or self.axis is not None
                or self.delta_mm is not None
                or self.delta_degrees is not None
            ):
                raise ValueError(error)
        elif self.action == "remove" and any(
            value is not None
            for value in (
                self.axis,
                self.delta_mm,
                self.delta_degrees,
                self.replacement_sku,
                self.quantity_delta,
            )
        ):
            raise ValueError(error)
        return self


class HumanEvaluation(_StrictModel):
    overall_rating: StrictInt | None = Field(ge=1, le=5)
    dimension_scores: tuple[HumanDimensionScore, ...]
    edit_facts: tuple[HumanEditFact, ...]

    @model_validator(mode="after")
    def reject_duplicates(self) -> "HumanEvaluation":
        _reject_duplicate_values(
            [score.metric for score in self.dimension_scores],
            "human_evaluation.dimension_scores metric",
        )
        _reject_duplicate_values(
            [edit.edit_id for edit in self.edit_facts],
            "human_evaluation.edit_facts edit_id",
        )
        return self


class CaseAnnotation(_StrictModel):
    schema_version: Literal[ANNOTATION_SCHEMA_VERSION]
    annotation_type: Literal[ANNOTATION_TYPE]
    case_id: StrictStr
    label_version: StrictStr
    source_asset_sha256: StrictStr
    requirements: tuple[RequirementFact, ...] = Field(min_length=1)
    space_facts: tuple[SpaceFact, ...] = Field(min_length=1)
    allowed_skus: tuple[StrictStr, ...] = Field(min_length=1)
    budget: BudgetAnnotation
    layout_hard_constraints: tuple[LayoutHardConstraint, ...] = Field(
        min_length=1
    )
    style_tags: tuple[StrictStr, ...] = Field(min_length=1)
    human_evaluation: HumanEvaluation
    file_sha256: str = Field(default="", exclude=True)

    @field_validator("case_id", "label_version")
    @classmethod
    def validate_top_identifier(cls, value: str, info) -> str:
        return _label(value, info.field_name, identifier=True)

    @field_validator("source_asset_sha256")
    @classmethod
    def validate_source_digest(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("source_asset_sha256 必须是小写 SHA-256")
        return value

    @field_validator("allowed_skus")
    @classmethod
    def validate_skus(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(
            _label(value, "allowed_skus", identifier=True) for value in values
        )
        _reject_duplicate_values(normalized, "allowed_skus")
        return normalized

    @field_validator("style_tags")
    @classmethod
    def validate_style_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_label(value, "style_tags") for value in values)
        _reject_duplicate_values(normalized, "style_tags")
        return normalized

    @model_validator(mode="after")
    def reject_duplicate_facts(self) -> "CaseAnnotation":
        _reject_duplicate_values(
            [fact.field for fact in self.requirements],
            "requirements field",
        )
        _reject_duplicate_values(
            [fact.fact_path for fact in self.space_facts],
            "space_facts fact_path",
        )
        _reject_duplicate_values(
            [constraint.constraint_id for constraint in self.layout_hard_constraints],
            "layout_hard_constraints constraint_id",
        )
        return self

    @property
    def content_fingerprint(self) -> str:
        canonical = json.dumps(
            self.model_dump(
                mode="json",
                by_alias=True,
                exclude={"file_sha256"},
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return f"sha256:{sha256(canonical).hexdigest()}"


def _reject_duplicate_values(values: list[str] | tuple[str, ...], field: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field} 包含重复事实或标签")


class _DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"JSON 对象包含重复键：{key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise AnnotationValidationError(f"标注只允许有限数值：{value}")


def _validate_finite_numbers(value: Any, path: str = "root") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise AnnotationValidationError(f"{path} 只允许有限数值")
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_finite_numbers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_numbers(child, f"{path}[{index}]")


def _reject_pii_fields(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.strip().lower().replace("-", "_")
            if normalized in _PII_OR_FREE_TEXT_FIELDS:
                raise AnnotationValidationError(
                    f"{path}.{key} 是禁止的原始自由文本或 PII 字段"
                )
            _reject_pii_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_pii_fields(child, f"{path}[{index}]")


def _validation_message(error: ValidationError) -> str:
    details: list[str] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        if item["type"] == "extra_forbidden":
            details.append(f"未知字段：{location}")
        else:
            details.append(f"{location}: {item['msg']}")
    return "；".join(details)


def _resolve_annotation_path(path: Path | str, dataset_root: Path | str) -> Path:
    root = Path(dataset_root).resolve()
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(root):
        raise AnnotationValidationError("标注文件位于数据集目录之外")
    if not resolved.is_file():
        raise AnnotationValidationError("标注文件不存在或不是普通文件")
    return resolved


def _read_annotation(path: Path) -> tuple[dict[str, Any], str]:
    try:
        if path.stat().st_size > MAX_ANNOTATION_BYTES:
            raise AnnotationValidationError("标注文件超过 2 MiB 限制")
        content = path.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AnnotationValidationError(f"标注文件无法读取：{exc}") from exc
    digest = sha256(content).hexdigest()
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateKeyError as exc:
        raise AnnotationValidationError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise AnnotationValidationError(f"标注文件不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise AnnotationValidationError("标注文件根节点必须是对象")
    unknown_fields = sorted(set(payload) - _DOCUMENT_FIELDS)
    if unknown_fields:
        raise AnnotationValidationError(
            f"标注包含未知字段：{', '.join(unknown_fields)}"
        )
    _validate_finite_numbers(payload)
    _reject_pii_fields(payload)
    return payload, digest


def _manifest_case(dataset: Any, case_id: str) -> Any:
    matches = [case for case in getattr(dataset, "cases", ()) if case.id == case_id]
    if len(matches) != 1:
        raise AnnotationValidationError(f"annotation case_id 未在清单中唯一匹配：{case_id}")
    return matches[0]


def load_case_annotation(
    annotation_path: Path | str,
    *,
    dataset: Any,
    dataset_root: Path | str,
    expected_sha256: str | None = None,
) -> CaseAnnotation:
    """加载一个已准入案例的结构化标注，并冻结文件与来源资产摘要。"""
    path = _resolve_annotation_path(annotation_path, dataset_root)
    payload, file_digest = _read_annotation(path)
    if expected_sha256 is not None:
        if not _SHA256_PATTERN.fullmatch(expected_sha256):
            raise AnnotationValidationError("expected_sha256 必须是小写 SHA-256")
        if not hmac.compare_digest(file_digest, expected_sha256):
            raise AnnotationValidationError("标注文件 SHA-256 与冻结值不一致")
    try:
        annotation = CaseAnnotation.model_validate(payload)
    except ValidationError as exc:
        raise AnnotationValidationError(_validation_message(exc)) from exc

    case = _manifest_case(dataset, annotation.case_id)
    if getattr(case, "annotation_status", None) != "ready":
        raise AnnotationValidationError(
            f"案例 {annotation.case_id} 的清单标注状态尚未 ready"
        )
    if annotation.label_version != getattr(case, "label_version", None):
        raise AnnotationValidationError(
            f"案例 {annotation.case_id} 的 label_version 与清单不一致"
        )
    manifest_asset_digest = getattr(case, "asset_sha256", None)
    if (
        not isinstance(manifest_asset_digest, str)
        or not _SHA256_PATTERN.fullmatch(manifest_asset_digest)
        or not hmac.compare_digest(
            annotation.source_asset_sha256,
            manifest_asset_digest,
        )
    ):
        raise AnnotationValidationError(
            f"案例 {annotation.case_id} 的资产 SHA-256 与清单不一致"
        )

    return annotation.model_copy(
        update={
            "file_sha256": file_digest,
            "requirements": tuple(
                sorted(annotation.requirements, key=lambda item: item.field)
            ),
            "space_facts": tuple(
                sorted(annotation.space_facts, key=lambda item: item.fact_path)
            ),
            "layout_hard_constraints": tuple(
                sorted(
                    annotation.layout_hard_constraints,
                    key=lambda item: item.constraint_id,
                )
            ),
            "allowed_skus": tuple(sorted(annotation.allowed_skus)),
            "style_tags": tuple(sorted(annotation.style_tags)),
            "human_evaluation": annotation.human_evaluation.model_copy(
                update={
                    "dimension_scores": tuple(
                        sorted(
                            annotation.human_evaluation.dimension_scores,
                            key=lambda item: item.metric,
                        )
                    ),
                    "edit_facts": tuple(
                        sorted(
                            annotation.human_evaluation.edit_facts,
                            key=lambda item: item.edit_id,
                        )
                    ),
                }
            ),
        }
    )
