"""真实案例数据契约与阶段 4 确定性质量门禁。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


CaseSplit = Literal["development", "regression", "blind", "unassigned"]
CaseOrigin = Literal["private_real", "public_reference", "synthetic"]
ConsentStatus = Literal["granted", "not_required", "pending", "denied"]
AnnotationStatus = Literal["ready", "pending", "rejected"]


class DatasetValidationError(ValueError):
    """案例清单不满足来源、权限或结构约束。"""


@dataclass(frozen=True)
class EvaluationVersions:
    model: str
    prompt: str
    rules: str
    data: str

    def __post_init__(self) -> None:
        missing = [
            name
            for name, value in (
                ("model", self.model),
                ("prompt", self.prompt),
                ("rules", self.rules),
                ("data", self.data),
            )
            if not value.strip()
        ]
        if missing:
            raise ValueError(f"评测版本不能为空：{', '.join(missing)}")


@dataclass(frozen=True)
class RealWorldCase:
    id: str
    name: str
    split: CaseSplit
    origin: CaseOrigin
    asset_path: Path
    consent_status: ConsentStatus
    annotation_status: AnnotationStatus
    label_version: str | None
    allowed_purposes: tuple[str, ...]
    failure_tags: tuple[str, ...]

    def ineligible_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.consent_status not in {"granted", "not_required"}:
            reasons.append("consent_not_granted")
        if self.annotation_status != "ready" or not self.label_version:
            reasons.append("annotation_not_ready")
        if "offline_evaluation" not in self.allowed_purposes:
            reasons.append("purpose_not_allowed")
        if self.split == "unassigned":
            reasons.append("split_not_assigned")
        return reasons


@dataclass(frozen=True)
class RealWorldDataset:
    schema_version: str
    dataset_version: str
    cases: tuple[RealWorldCase, ...]

    def eligible_cases(self, split: CaseSplit | None = None) -> list[RealWorldCase]:
        return [
            case
            for case in self.cases
            if not case.ineligible_reasons()
            and (split is None or case.split == split)
        ]

    @property
    def ineligible_reasons(self) -> dict[str, list[str]]:
        return {
            case.id: reasons
            for case in self.cases
            if (reasons := case.ineligible_reasons())
        }


def _required_text(raw: dict[str, Any], field_name: str, case_id: str) -> str:
    value = raw.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise DatasetValidationError(f"案例 {case_id} 缺少 {field_name}")
    return value.strip()


def _enum_value(
    raw: dict[str, Any],
    field_name: str,
    allowed: set[str],
    case_id: str,
) -> str:
    value = _required_text(raw, field_name, case_id)
    if value not in allowed:
        raise DatasetValidationError(
            f"案例 {case_id} 的 {field_name} 不合法：{value}"
        )
    return value


def _string_list(raw: dict[str, Any], field_name: str, case_id: str) -> tuple[str, ...]:
    value = raw.get(field_name)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise DatasetValidationError(f"案例 {case_id} 的 {field_name} 必须是字符串数组")
    return tuple(dict.fromkeys(item.strip() for item in value))


def _resolve_asset(asset_root: Path, raw_path: str, case_id: str) -> Path:
    root = asset_root.resolve()
    resolved = (root / raw_path).resolve()
    if not resolved.is_relative_to(root):
        raise DatasetValidationError(f"案例 {case_id} 的资产位于数据集目录之外")
    if not resolved.is_file():
        raise DatasetValidationError(f"案例 {case_id} 的资产不存在：{raw_path}")
    return resolved


def load_case_manifest(
    manifest_path: Path | str,
    *,
    asset_root: Path | str | None = None,
) -> RealWorldDataset:
    """读取并验证案例清单；默认只允许引用清单目录内的资产。"""
    path = Path(manifest_path).resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(f"无法读取案例清单：{exc}") from exc
    if not isinstance(payload, dict):
        raise DatasetValidationError("案例清单根节点必须是对象")
    schema_version = payload.get("schema_version")
    dataset_version = payload.get("dataset_version")
    if schema_version != "1.0":
        raise DatasetValidationError(f"不支持的 schema_version：{schema_version}")
    if not isinstance(dataset_version, str) or not dataset_version.strip():
        raise DatasetValidationError("dataset_version 不能为空")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise DatasetValidationError("cases 必须是数组")

    root = Path(asset_root).resolve() if asset_root is not None else path.parent
    errors: list[str] = []
    seen_ids: set[str] = set()
    cases: list[RealWorldCase] = []
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            errors.append(f"第 {index + 1} 个案例必须是对象")
            continue
        case_id = str(raw.get("id") or f"index-{index}").strip()
        if case_id in seen_ids:
            errors.append(f"重复案例 ID：{case_id}")
        seen_ids.add(case_id)
        try:
            split = _enum_value(
                raw,
                "split",
                {"development", "regression", "blind", "unassigned"},
                case_id,
            )
            origin = _enum_value(
                raw,
                "origin",
                {"private_real", "public_reference", "synthetic"},
                case_id,
            )
            consent_status = _enum_value(
                raw,
                "consent_status",
                {"granted", "not_required", "pending", "denied"},
                case_id,
            )
            annotation_status = _enum_value(
                raw,
                "annotation_status",
                {"ready", "pending", "rejected"},
                case_id,
            )
            if split == "blind" and origin == "synthetic":
                raise DatasetValidationError(
                    f"案例 {case_id}：盲测集不能包含 synthetic 案例"
                )
            raw_asset_path = _required_text(raw, "asset_path", case_id)
            asset_path = _resolve_asset(root, raw_asset_path, case_id)
            label_version = raw.get("label_version")
            if label_version is not None and (
                not isinstance(label_version, str) or not label_version.strip()
            ):
                raise DatasetValidationError(
                    f"案例 {case_id} 的 label_version 不合法"
                )
            cases.append(
                RealWorldCase(
                    id=_required_text(raw, "id", case_id),
                    name=_required_text(raw, "name", case_id),
                    split=split,  # type: ignore[arg-type]
                    origin=origin,  # type: ignore[arg-type]
                    asset_path=asset_path,
                    consent_status=consent_status,  # type: ignore[arg-type]
                    annotation_status=annotation_status,  # type: ignore[arg-type]
                    label_version=(label_version or None),
                    allowed_purposes=_string_list(
                        raw, "allowed_purposes", case_id
                    ),
                    failure_tags=_string_list(raw, "failure_tags", case_id),
                )
            )
        except DatasetValidationError as exc:
            errors.append(str(exc))
    if errors:
        raise DatasetValidationError("；".join(errors))
    return RealWorldDataset(
        schema_version=schema_version,
        dataset_version=dataset_version.strip(),
        cases=tuple(cases),
    )


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    requirement_correct: int = 0
    requirement_total: int = 0
    space_fact_correct: int = 0
    space_fact_total: int = 0
    low_confidence_facts: int = 0
    low_confidence_confirmed: int = 0
    recommended_skus: int = 0
    valid_skus: int = 0
    product_match_checks: int = 0
    product_match_accepted: int = 0
    quote_checks: int = 0
    quote_consistent: int = 0
    budget_checks: int = 0
    budget_within_limit: int = 0
    layout_checks: int = 0
    layout_hard_passes: int = 0
    style_checks: int = 0
    style_consistent: int = 0
    human_rating_count: int = 0
    human_rating_sum: int = 0
    generation_succeeded: bool = False
    cross_user_access_checks: int = 0
    severe_cross_user_access: int = 0
    retry_bound_checks: int = 0
    unbounded_retry_detected: bool = False

    def __post_init__(self) -> None:
        counters = (
            self.requirement_correct,
            self.requirement_total,
            self.space_fact_correct,
            self.space_fact_total,
            self.low_confidence_facts,
            self.low_confidence_confirmed,
            self.recommended_skus,
            self.valid_skus,
            self.product_match_checks,
            self.product_match_accepted,
            self.quote_checks,
            self.quote_consistent,
            self.budget_checks,
            self.budget_within_limit,
            self.layout_checks,
            self.layout_hard_passes,
            self.style_checks,
            self.style_consistent,
            self.human_rating_count,
            self.human_rating_sum,
            self.cross_user_access_checks,
            self.severe_cross_user_access,
            self.retry_bound_checks,
        )
        if any(value < 0 for value in counters):
            raise ValueError("评测计数不能为负数")
        pairs = (
            (self.requirement_correct, self.requirement_total),
            (self.space_fact_correct, self.space_fact_total),
            (self.low_confidence_confirmed, self.low_confidence_facts),
            (self.valid_skus, self.recommended_skus),
            (self.product_match_accepted, self.product_match_checks),
            (self.quote_consistent, self.quote_checks),
            (self.budget_within_limit, self.budget_checks),
            (self.layout_hard_passes, self.layout_checks),
            (self.style_consistent, self.style_checks),
        )
        if any(numerator > denominator for numerator, denominator in pairs):
            raise ValueError("评测命中数不能大于检查总数")
        if not (
            self.human_rating_count <= self.human_rating_sum
            <= self.human_rating_count * 5
        ):
            raise ValueError("人工满意度总分必须落在 1 到 5 分量表范围内")
        if self.severe_cross_user_access > self.cross_user_access_checks:
            raise ValueError("跨用户访问问题缺少对应检查证据")
        if self.unbounded_retry_detected and self.retry_bound_checks == 0:
            raise ValueError("无限重试问题缺少对应检查证据")


@dataclass(frozen=True)
class QualityReport:
    versions: EvaluationVersions
    case_count: int
    metrics: dict[str, float | int | None]


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def aggregate_quality_metrics(
    results: list[CaseResult],
    *,
    versions: EvaluationVersions,
) -> QualityReport:
    if len({result.case_id for result in results}) != len(results):
        raise ValueError("评测结果包含重复 case_id")
    totals = {
        "requirement_correct": sum(r.requirement_correct for r in results),
        "requirement_total": sum(r.requirement_total for r in results),
        "space_fact_correct": sum(r.space_fact_correct for r in results),
        "space_fact_total": sum(r.space_fact_total for r in results),
        "low_confidence_confirmed": sum(
            r.low_confidence_confirmed for r in results
        ),
        "low_confidence_facts": sum(r.low_confidence_facts for r in results),
        "valid_skus": sum(r.valid_skus for r in results),
        "recommended_skus": sum(r.recommended_skus for r in results),
        "product_match_accepted": sum(
            r.product_match_accepted for r in results
        ),
        "product_match_checks": sum(r.product_match_checks for r in results),
        "quote_consistent": sum(r.quote_consistent for r in results),
        "quote_checks": sum(r.quote_checks for r in results),
        "budget_within_limit": sum(r.budget_within_limit for r in results),
        "budget_checks": sum(r.budget_checks for r in results),
        "layout_hard_passes": sum(r.layout_hard_passes for r in results),
        "layout_checks": sum(r.layout_checks for r in results),
        "style_consistent": sum(r.style_consistent for r in results),
        "style_checks": sum(r.style_checks for r in results),
        "human_rating_sum": sum(r.human_rating_sum for r in results),
        "human_rating_count": sum(r.human_rating_count for r in results),
        "cross_user_access_checks": sum(
            r.cross_user_access_checks for r in results
        ),
        "retry_bound_checks": sum(r.retry_bound_checks for r in results),
    }
    metrics: dict[str, float | int | None] = {
        "requirement_accuracy": _rate(
            totals["requirement_correct"], totals["requirement_total"]
        ),
        "space_fact_accuracy": _rate(
            totals["space_fact_correct"], totals["space_fact_total"]
        ),
        "low_confidence_confirmation_rate": _rate(
            totals["low_confidence_confirmed"], totals["low_confidence_facts"]
        ),
        "valid_sku_rate": _rate(totals["valid_skus"], totals["recommended_skus"]),
        "product_match_acceptance_rate": _rate(
            totals["product_match_accepted"], totals["product_match_checks"]
        ),
        "quote_consistency_rate": _rate(
            totals["quote_consistent"], totals["quote_checks"]
        ),
        "budget_compliance_rate": _rate(
            totals["budget_within_limit"], totals["budget_checks"]
        ),
        "layout_hard_constraint_pass_rate": _rate(
            totals["layout_hard_passes"], totals["layout_checks"]
        ),
        "style_consistency_rate": _rate(
            totals["style_consistent"], totals["style_checks"]
        ),
        "human_satisfaction_mean": _rate(
            totals["human_rating_sum"], totals["human_rating_count"]
        ),
        "human_satisfaction_count": totals["human_rating_count"],
        "generation_success_rate": _rate(
            sum(1 for r in results if r.generation_succeeded), len(results)
        ),
        "cross_user_access_checks": totals["cross_user_access_checks"],
        "severe_cross_user_access": (
            sum(r.severe_cross_user_access for r in results)
            if totals["cross_user_access_checks"]
            else None
        ),
        "retry_bound_checks": totals["retry_bound_checks"],
        "unbounded_retry_cases": (
            sum(1 for r in results if r.unbounded_retry_detected)
            if totals["retry_bound_checks"]
            else None
        ),
    }
    return QualityReport(
        versions=versions,
        case_count=len(results),
        metrics=metrics,
    )


@dataclass(frozen=True)
class QualityThresholds:
    requirement_accuracy: float = 0.95
    low_confidence_confirmation_rate: float = 1.0
    valid_sku_rate: float = 1.0
    quote_consistency_rate: float = 1.0
    layout_hard_constraint_pass_rate: float = 0.95
    generation_success_rate: float = 0.95
    severe_cross_user_access: int = 0
    unbounded_retry_cases: int = 0


@dataclass(frozen=True)
class QualityGateItem:
    metric: str
    actual: float | int | None
    target: float | int
    operator: Literal[">=", "=="]
    passed: bool


@dataclass(frozen=True)
class QualityGateResult:
    passed: bool
    items: tuple[QualityGateItem, ...] = field(default_factory=tuple)


def evaluate_quality_gates(
    report: QualityReport,
    thresholds: QualityThresholds,
) -> QualityGateResult:
    minimum_metrics = (
        "requirement_accuracy",
        "low_confidence_confirmation_rate",
        "valid_sku_rate",
        "quote_consistency_rate",
        "layout_hard_constraint_pass_rate",
        "generation_success_rate",
    )
    items: list[QualityGateItem] = []
    for name in minimum_metrics:
        actual = report.metrics[name]
        target = getattr(thresholds, name)
        items.append(
            QualityGateItem(
                metric=name,
                actual=actual,
                target=target,
                operator=">=",
                passed=actual is not None and actual >= target,
            )
        )
    for name in ("severe_cross_user_access", "unbounded_retry_cases"):
        actual = report.metrics[name]
        target = getattr(thresholds, name)
        items.append(
            QualityGateItem(
                metric=name,
                actual=actual,
                target=target,
                operator="==",
                passed=actual == target,
            )
        )
    return QualityGateResult(
        passed=all(item.passed for item in items),
        items=tuple(items),
    )
