"""基于结构化失败证据的确定性分诊报告。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from base64 import b32encode
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

from evals.real_world import RealWorldDataset
from evals.real_world import EvaluationInputError, EvaluationSplit
from evals.trusted_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    VerifiedEvaluationEvidence,
    _case_fingerprint,
    verify_trusted_evidence,
)
from app.services.failure_triage_signature import sign_failure_triage_payload


FailureType = Literal[
    "requirement",
    "space_fact",
    "catalog",
    "quote",
    "budget",
    "layout",
    "style",
    "generation",
    "security",
    "orchestration",
    "human_feedback",
]
FailureSeverity = Literal["critical", "high", "medium", "low"]

FAILURE_TRIAGE_SCHEMA_VERSION = "2.0"
FAILURE_TAXONOMY_VERSION = "2.0"

_FAILURE_TYPES = {
    "requirement",
    "space_fact",
    "catalog",
    "quote",
    "budget",
    "layout",
    "style",
    "generation",
    "security",
    "orchestration",
    "human_feedback",
}
_SEVERITIES = ("critical", "high", "medium", "low")
_SPLITS = ("development", "regression", "blind")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_EXECUTION_REF_PATTERN = re.compile(r"^exec-hmac-sha256:[0-9a-f]{64}$")


class FailureTriageInputError(ValueError):
    """失败分诊输入不满足版本或结构约束。"""


@dataclass(frozen=True)
class FailureRecord:
    case_id: str
    execution_ref: str
    output_digest: str | None
    code: str
    failure_type: FailureType
    severity: FailureSeverity
    tags: tuple[str, ...]
    metrics: tuple[str, ...]
    occurrence_count: int = 1


@dataclass(frozen=True)
class FailureTriageEvidence:
    schema_version: str
    taxonomy_version: str
    data_version: str
    manifest_digest: str
    evidence_digest: str
    output_digests: tuple[str, ...]
    failures: tuple[FailureRecord, ...]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailureTriageInputError(f"无法读取可信评测证据：{exc}") from exc
    if not isinstance(payload, dict):
        raise FailureTriageInputError("可信评测证据根节点必须是对象")
    return payload


_METRIC_FAILURES = (
    (
        "requirement_correct",
        "requirement_total",
        "requirement_mismatch",
        "requirement",
        "high",
        "requirement_accuracy",
    ),
    (
        "space_fact_correct",
        "space_fact_total",
        "space_fact_mismatch",
        "space_fact",
        "high",
        "space_fact_accuracy",
    ),
    (
        "low_confidence_confirmed",
        "low_confidence_facts",
        "low_confidence_unconfirmed",
        "space_fact",
        "high",
        "low_confidence_confirmation_rate",
    ),
    (
        "valid_skus",
        "recommended_skus",
        "invalid_sku",
        "catalog",
        "critical",
        "valid_sku_rate",
    ),
    (
        "product_match_accepted",
        "product_match_checks",
        "product_match_rejected",
        "catalog",
        "medium",
        "product_match_acceptance_rate",
    ),
    (
        "quote_consistent",
        "quote_checks",
        "quote_mismatch",
        "quote",
        "critical",
        "quote_consistency_rate",
    ),
    (
        "budget_within_limit",
        "budget_checks",
        "budget_exceeded",
        "budget",
        "high",
        "budget_compliance_rate",
    ),
    (
        "layout_hard_passes",
        "layout_checks",
        "layout_hard_constraint_failed",
        "layout",
        "critical",
        "layout_hard_constraint_pass_rate",
    ),
    (
        "style_consistent",
        "style_checks",
        "style_mismatch",
        "style",
        "medium",
        "style_consistency_rate",
    ),
)


def _derived_failures(
    evidence: VerifiedEvaluationEvidence,
) -> tuple[FailureRecord, ...]:
    failures: list[FailureRecord] = []
    if len(evidence.results) != len(evidence.executions):
        raise FailureTriageInputError("可信评测结果与执行来源数量不一致")
    for result, execution in zip(evidence.results, evidence.executions, strict=True):
        common = {
            "case_id": result.case_id,
            "execution_ref": execution.execution_ref,
            "output_digest": execution.output_digest,
        }
        if execution.status != "completed":
            failures.append(
                FailureRecord(
                    **common,
                    code=f"generation_{execution.status}",
                    failure_type="generation",
                    severity=(
                        "critical" if execution.status == "dead_letter" else "high"
                    ),
                    tags=(f"status.{execution.status}",),
                    metrics=("generation_success_rate",),
                )
            )
            continue
        for numerator, denominator, code, failure_type, severity, metric in _METRIC_FAILURES:
            missing_count = getattr(result, denominator) - getattr(result, numerator)
            if missing_count > 0:
                failures.append(
                    FailureRecord(
                        **common,
                        code=code,
                        failure_type=failure_type,
                        severity=severity,
                        tags=(failure_type,),
                        metrics=(metric,),
                        occurrence_count=missing_count,
                    )
                )
        if result.severe_cross_user_access:
            failures.append(
                FailureRecord(
                    **common,
                    code="severe_cross_user_access",
                    failure_type="security",
                    severity="critical",
                    tags=("authorization",),
                    metrics=("severe_cross_user_access",),
                )
            )
        if result.unbounded_retry_detected:
            failures.append(
                FailureRecord(
                    **common,
                    code="unbounded_retry",
                    failure_type="orchestration",
                    severity="critical",
                    tags=("retry",),
                    metrics=("unbounded_retry_cases",),
                )
            )
    return tuple(
        sorted(
            failures,
            key=lambda item: (item.case_id, item.failure_type, item.code),
        )
    )


def derive_failure_triage_evidence(
    *,
    evidence: VerifiedEvaluationEvidence,
    dataset: RealWorldDataset,
) -> FailureTriageEvidence:
    """只从已验签可信证据中的结构化终态与指标派生失败。"""
    if not evidence.signature_verified:
        raise FailureTriageInputError("失败分诊只接受已验签可信评测证据")
    if evidence.schema_version != EVIDENCE_SCHEMA_VERSION:
        raise FailureTriageInputError("失败分诊只接受 trusted evidence v5")
    if len(evidence.results) != len(evidence.executions):
        raise FailureTriageInputError("可信评测结果与执行来源数量不一致")
    eligible_ids = {case.id for case in dataset.eligible_cases(evidence.split)}
    result_ids = {result.case_id for result in evidence.results}
    if result_ids != eligible_ids:
        raise FailureTriageInputError("可信证据与当前数据集准入案例不一致")
    execution_refs = [execution.execution_ref for execution in evidence.executions]
    if (
        len(execution_refs) != len(set(execution_refs))
        or any(not _EXECUTION_REF_PATTERN.fullmatch(item) for item in execution_refs)
    ):
        raise FailureTriageInputError("可信证据包含非法或重复 execution_ref")
    for result, execution in zip(evidence.results, evidence.executions, strict=True):
        expected_case = _case_fingerprint(
            evidence.dataset_fingerprint,
            result.case_id,
        )
        if execution.case_fingerprint != expected_case:
            raise FailureTriageInputError("可信证据的案例与执行来源顺序不一致")
        if execution.status == "completed":
            if (
                execution.output_digest is None
                or not _SHA256_PATTERN.fullmatch(execution.output_digest)
            ):
                raise FailureTriageInputError("成功执行缺少可信 output_digest")
        elif execution.output_digest is not None:
            raise FailureTriageInputError("失败执行不得包含 output_digest")
    for digest_name, digest in (
        ("manifest_digest", evidence.dataset_fingerprint),
        ("evidence_digest", evidence.evidence_digest),
    ):
        if not _SHA256_PATTERN.fullmatch(digest):
            raise FailureTriageInputError(f"{digest_name} 不合法")
    output_digests = tuple(
        sorted(
            {
                execution.output_digest
                for execution in evidence.executions
                if execution.output_digest is not None
            }
        )
    )
    return FailureTriageEvidence(
        schema_version=evidence.schema_version,
        taxonomy_version=FAILURE_TAXONOMY_VERSION,
        data_version=dataset.dataset_version,
        manifest_digest=evidence.dataset_fingerprint,
        evidence_digest=evidence.evidence_digest,
        output_digests=output_digests,
        failures=_derived_failures(evidence),
    )


def load_trusted_failure_evidence(
    input_path: Path | str,
    *,
    dataset: RealWorldDataset,
    split: EvaluationSplit,
    verification_keys: Mapping[str, str],
) -> FailureTriageEvidence:
    payload = _read_json(Path(input_path).resolve())
    try:
        verified = verify_trusted_evidence(
            payload,
            dataset=dataset,
            split=split,
            verification_keys=verification_keys,
        )
    except EvaluationInputError as exc:
        raise FailureTriageInputError(f"可信评测证据不合法：{exc}") from exc
    return derive_failure_triage_evidence(evidence=verified, dataset=dataset)


def load_failure_triage_evidence(*args: Any, **kwargs: Any) -> FailureTriageEvidence:
    """拒绝历史可独立伪造的 self-reported failure 文件。"""
    del args, kwargs
    raise FailureTriageInputError("失败分诊不再接受自报失败文件，请提供可信评测证据")


def _case_alias(case_id: str, *, data_version: str, salt: str) -> str:
    digest = hmac.new(
        salt.encode("utf-8"),
        f"{data_version}\0{case_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    digest = b32encode(digest).decode("ascii")[:16]
    return f"case-{digest}"


def _aggregate_dimension(
    failures: tuple[FailureRecord, ...],
    *,
    field: str,
    aliases: dict[str, str],
    order: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[FailureRecord]] = {}
    for failure in failures:
        grouped.setdefault(str(getattr(failure, field)), []).append(failure)
    rank = {value: index for index, value in enumerate(order or ())}
    values = sorted(grouped, key=lambda value: (rank.get(value, len(rank)), value))
    return [
        {
            field: value,
            "failure_count": sum(item.occurrence_count for item in grouped[value]),
            "affected_case_count": len({failure.case_id for failure in grouped[value]}),
            "case_ids": sorted(
                {aliases[failure.case_id] for failure in grouped[value]}
            ),
        }
        for value in values
    ]


def _clusters(
    failures: tuple[FailureRecord, ...],
    *,
    aliases: dict[str, str],
    case_splits: dict[str, str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[FailureRecord]] = {}
    for failure in failures:
        key = (failure.failure_type, failure.severity, failure.code)
        grouped.setdefault(key, []).append(failure)
    severity_rank = {value: index for index, value in enumerate(_SEVERITIES)}
    keys = sorted(
        grouped,
        key=lambda key: (severity_rank[key[1]], key[0], key[2]),
    )
    result: list[dict[str, Any]] = []
    for failure_type, severity, code in keys:
        records = grouped[(failure_type, severity, code)]
        tags = Counter(tag for item in records for tag in item.tags)
        metrics = Counter(metric for item in records for metric in item.metrics)
        result.append(
            {
                "failure_type": failure_type,
                "severity": severity,
                "code": code,
                "failure_count": sum(item.occurrence_count for item in records),
                "affected_case_count": len({item.case_id for item in records}),
                "splits": sorted(
                    {case_splits[item.case_id] for item in records},
                    key=lambda value: (_SPLITS.index(value), value),
                ),
                "case_ids": sorted({aliases[item.case_id] for item in records}),
                "execution_refs": sorted(
                    {item.execution_ref for item in records}
                ),
                "output_digests": sorted(
                    {
                        item.output_digest
                        for item in records
                        if item.output_digest is not None
                    }
                ),
                "tag_counts": dict(sorted(tags.items())),
                "metric_counts": dict(sorted(metrics.items())),
            }
        )
    return result


def _aggregate_tokens(
    failures: tuple[FailureRecord, ...],
    *,
    source_field: str,
    output_field: str,
    aliases: dict[str, str],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[FailureRecord]] = {}
    for failure in failures:
        for token in getattr(failure, source_field):
            grouped.setdefault(token, []).append(failure)
    return [
        {
            output_field: token,
            "failure_count": sum(item.occurrence_count for item in grouped[token]),
            "affected_case_count": len({failure.case_id for failure in grouped[token]}),
            "case_ids": sorted(
                {aliases[failure.case_id] for failure in grouped[token]}
            ),
        }
        for token in sorted(grouped)
    ]


def build_failure_triage_report(
    *,
    dataset: RealWorldDataset,
    evidence: FailureTriageEvidence,
    anonymization_salt: str,
    salt_id: str,
) -> dict[str, Any]:
    """生成不含原始 case_id 的可复现结构化报告。"""
    if evidence.data_version != dataset.dataset_version:
        raise FailureTriageInputError("失败证据与案例清单的数据版本不一致")
    if evidence.schema_version != EVIDENCE_SCHEMA_VERSION:
        raise FailureTriageInputError("失败分诊只接受 trusted evidence v5")
    if evidence.taxonomy_version != FAILURE_TAXONOMY_VERSION:
        raise FailureTriageInputError("失败分诊 taxonomy_version 不受支持")
    if not isinstance(anonymization_salt, str) or len(anonymization_salt) < 16:
        raise FailureTriageInputError("case_id 脱敏密钥至少需要 16 个字符")
    if not isinstance(salt_id, str) or not salt_id.strip():
        raise FailureTriageInputError("salt_id 不能为空")

    eligible = dataset.eligible_cases()
    eligible_ids = {case.id for case in eligible}
    invalid_ids = {item.case_id for item in evidence.failures} - eligible_ids
    if invalid_ids:
        raise FailureTriageInputError("失败证据包含未准入案例")
    aliases = {
        case.id: _case_alias(
            case.id,
            data_version=dataset.dataset_version,
            salt=anonymization_salt,
        )
        for case in eligible
    }
    case_splits = {case.id: case.split for case in eligible}
    failures = evidence.failures

    by_split: dict[str, list[FailureRecord]] = {}
    for failure in failures:
        by_split.setdefault(case_splits[failure.case_id], []).append(failure)
    split_items = [
        {
            "split": split,
            "failure_count": sum(
                item.occurrence_count for item in by_split[split]
            ),
            "affected_case_count": len(
                {failure.case_id for failure in by_split[split]}
            ),
            "case_ids": sorted(
                {aliases[failure.case_id] for failure in by_split[split]}
            ),
        }
        for split in _SPLITS
        if split in by_split
    ]
    return {
        "schema_version": FAILURE_TRIAGE_SCHEMA_VERSION,
        "input": {
            "schema_version": evidence.schema_version,
            "taxonomy_version": evidence.taxonomy_version,
            "data_version": evidence.data_version,
            "manifest_digest": evidence.manifest_digest,
            "evidence_digest": evidence.evidence_digest,
            "output_digests": list(evidence.output_digests),
        },
        "anonymization": {
            "algorithm": "hmac-sha256-80",
            "salt_id": salt_id.strip(),
        },
        "summary": {
            "eligible_case_count": len(eligible),
            "failure_count": sum(item.occurrence_count for item in failures),
            "affected_case_count": len({failure.case_id for failure in failures}),
        },
        "by_failure_type": _aggregate_dimension(
            failures, field="failure_type", aliases=aliases
        ),
        "by_severity": _aggregate_dimension(
            failures,
            field="severity",
            aliases=aliases,
            order=_SEVERITIES,
        ),
        "by_split": split_items,
        "by_code": _aggregate_dimension(failures, field="code", aliases=aliases),
        "by_tag": _aggregate_tokens(
            failures,
            source_field="tags",
            output_field="tag",
            aliases=aliases,
        ),
        "by_metric": _aggregate_tokens(
            failures,
            source_field="metrics",
            output_field="metric",
            aliases=aliases,
        ),
        "clusters": _clusters(
            failures,
            aliases=aliases,
            case_splits=case_splits,
        ),
    }


def build_failure_triage_sync_payload(
    report: dict[str, Any],
    *,
    report_id: str,
    candidate_version: str,
    signing_key_id: str,
    signing_key: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """把已验证匿名报告转换成可由管理 API 验签的最小载荷。"""
    report_input = report.get("input")
    clusters = report.get("clusters")
    if not isinstance(report_input, dict) or not isinstance(clusters, list):
        raise FailureTriageInputError("失败分诊报告缺少 input 或 clusters")

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    severity_rank = {value: index for index, value in enumerate(reversed(_SEVERITIES))}
    for cluster in clusters:
        if not isinstance(cluster, dict):
            raise FailureTriageInputError("失败分诊报告包含非法聚类")
        key = (str(cluster.get("failure_type") or ""), str(cluster.get("code") or ""))
        severity = str(cluster.get("severity") or "")
        aliases = cluster.get("case_ids")
        failure_count = cluster.get("failure_count")
        if (
            not all(key)
            or severity not in _SEVERITIES
            or not isinstance(aliases, list)
            or any(not isinstance(alias, str) for alias in aliases)
            or not isinstance(failure_count, int)
            or failure_count < 1
        ):
            raise FailureTriageInputError("失败分诊报告聚类字段不合法")
        current = grouped.setdefault(
            key,
            {
                "failure_type": key[0],
                "code": key[1],
                "severity": severity,
                "occurrence_count": 0,
                "aliases": set(),
            },
        )
        current["occurrence_count"] += failure_count
        current["aliases"].update(aliases)
        if severity_rank[severity] > severity_rank[current["severity"]]:
            current["severity"] = severity

    timestamp = generated_at or datetime.now(timezone.utc)
    generated_text = timestamp.astimezone(timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )
    payload: dict[str, Any] = {
        "schema_version": FAILURE_TRIAGE_SCHEMA_VERSION,
        "report_id": report_id.strip(),
        "taxonomy_version": str(report_input.get("taxonomy_version") or "").strip(),
        "data_version": str(report_input.get("data_version") or "").strip(),
        "manifest_digest": report_input.get("manifest_digest"),
        "evidence_digest": report_input.get("evidence_digest"),
        "output_digests": report_input.get("output_digests"),
        "candidate_version": candidate_version.strip(),
        "signature_algorithm": "hmac-sha256",
        "signature_key_id": signing_key_id.strip(),
        "generated_at": generated_text,
        "failures": [
            {
                "failure_type": item["failure_type"],
                "code": item["code"],
                "severity": item["severity"],
                "occurrence_count": item["occurrence_count"],
                "affected_count": len(item["aliases"]),
            }
            for _, item in sorted(grouped.items())
        ],
    }
    for field_name in (
        "report_id",
        "taxonomy_version",
        "data_version",
        "candidate_version",
        "signature_key_id",
    ):
        if not payload[field_name]:
            raise FailureTriageInputError(f"{field_name} 不能为空")
    for field_name in ("manifest_digest", "evidence_digest"):
        if not isinstance(payload[field_name], str) or not _SHA256_PATTERN.fullmatch(
            payload[field_name]
        ):
            raise FailureTriageInputError(f"{field_name} 不合法")
    output_digests = payload["output_digests"]
    if (
        not isinstance(output_digests, list)
        or output_digests != sorted(set(output_digests))
        or any(
            not isinstance(item, str) or not _SHA256_PATTERN.fullmatch(item)
            for item in output_digests
        )
    ):
        raise FailureTriageInputError("output_digests 不合法")
    try:
        payload["signature"] = sign_failure_triage_payload(
            payload,
            signing_key=signing_key,
        )
    except ValueError as exc:
        raise FailureTriageInputError(str(exc)) from exc
    return payload


def _markdown_table(headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> list[str]:
    lines = [
        f"| {' | '.join(headers)} |",
        f"| {' | '.join('---' for _ in headers)} |",
    ]
    lines.extend(f"| {' | '.join(map(str, row))} |" for row in rows)
    return lines


def render_failure_triage_markdown(report: dict[str, Any]) -> str:
    """把结构化报告渲染为便于离线审阅的 Markdown。"""
    summary = report["summary"]
    lines = [
        "# 失败样本分诊报告",
        "",
        f"- 准入案例数：{summary['eligible_case_count']}",
        f"- 失败记录数：{summary['failure_count']}",
        f"- 受影响案例数：{summary['affected_case_count']}",
    ]
    dimensions = (
        ("失败类型", "by_failure_type", "failure_type"),
        ("严重度", "by_severity", "severity"),
        ("数据切分", "by_split", "split"),
    )
    for title, report_key, value_key in dimensions:
        lines.extend(["", f"## {title}", ""])
        rows = [
            (
                item[value_key],
                item["failure_count"],
                item["affected_case_count"],
            )
            for item in report[report_key]
        ]
        lines.extend(
            _markdown_table(
                (title, "失败记录数", "受影响案例数"),
                rows,
            )
        )
    lines.extend(["", "## 聚类", ""])
    cluster_rows = [
        (
            item["code"],
            item["failure_type"],
            item["severity"],
            item["failure_count"],
            item["affected_case_count"],
            ", ".join(item["case_ids"]),
        )
        for item in report["clusters"]
    ]
    lines.extend(
        _markdown_table(
            ("code", "失败类型", "严重度", "记录数", "案例数", "脱敏案例"),
            cluster_rows,
        )
    )
    return "\n".join(lines) + "\n"
