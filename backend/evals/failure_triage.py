"""基于结构化失败证据的确定性分诊报告。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from base64 import b32encode
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from evals.real_world import RealWorldDataset


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

FAILURE_TRIAGE_SCHEMA_VERSION = "1.0"
FAILURE_TAXONOMY_VERSION = "1.0"

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
_TOKEN_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_ROOT_FIELDS = {
    "schema_version",
    "taxonomy_version",
    "data_version",
    "failures",
}
_FAILURE_FIELDS = {
    "case_id",
    "code",
    "failure_type",
    "severity",
    "tags",
    "metrics",
}


class FailureTriageInputError(ValueError):
    """失败分诊输入不满足版本或结构约束。"""


@dataclass(frozen=True)
class FailureRecord:
    case_id: str
    code: str
    failure_type: FailureType
    severity: FailureSeverity
    tags: tuple[str, ...]
    metrics: tuple[str, ...]


@dataclass(frozen=True)
class FailureTriageEvidence:
    schema_version: str
    taxonomy_version: str
    data_version: str
    failures: tuple[FailureRecord, ...]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailureTriageInputError(f"无法读取失败分诊输入：{exc}") from exc
    if not isinstance(payload, dict):
        raise FailureTriageInputError("失败分诊输入根节点必须是对象")
    return payload


def _validate_token(value: Any, *, field: str, index: int) -> str:
    if not isinstance(value, str) or not _TOKEN_PATTERN.fullmatch(value):
        raise FailureTriageInputError(
            f"第 {index + 1} 条失败记录的 {field} 必须是结构化标识符"
        )
    return value


def _validate_token_list(value: Any, *, field: str, index: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise FailureTriageInputError(f"第 {index + 1} 条失败记录的 {field} 必须是数组")
    tokens = tuple(_validate_token(item, field=field, index=index) for item in value)
    if len(set(tokens)) != len(tokens):
        raise FailureTriageInputError(f"第 {index + 1} 条失败记录的 {field} 包含重复值")
    return tuple(sorted(tokens))


def _build_failure(raw: Any, *, index: int) -> FailureRecord:
    if not isinstance(raw, dict):
        raise FailureTriageInputError(f"第 {index + 1} 条失败记录必须是对象")
    unknown = sorted(set(raw) - _FAILURE_FIELDS)
    if unknown:
        raise FailureTriageInputError(
            f"第 {index + 1} 条失败记录含未知字段：{', '.join(unknown)}"
        )
    missing = sorted(_FAILURE_FIELDS - set(raw))
    if missing:
        raise FailureTriageInputError(
            f"第 {index + 1} 条失败记录缺少字段：{', '.join(missing)}"
        )

    case_id = raw["case_id"]
    if not isinstance(case_id, str) or not case_id.strip():
        raise FailureTriageInputError(f"第 {index + 1} 条失败记录的 case_id 不能为空")
    failure_type = raw["failure_type"]
    if not isinstance(failure_type, str) or failure_type not in _FAILURE_TYPES:
        raise FailureTriageInputError(
            f"第 {index + 1} 条失败记录的 failure_type 不合法"
        )
    severity = raw["severity"]
    if severity not in _SEVERITIES:
        raise FailureTriageInputError(f"第 {index + 1} 条失败记录的 severity 不合法")
    return FailureRecord(
        case_id=case_id.strip(),
        code=_validate_token(raw["code"], field="code", index=index),
        failure_type=failure_type,
        severity=severity,
        tags=_validate_token_list(raw["tags"], field="tags", index=index),
        metrics=_validate_token_list(raw["metrics"], field="metrics", index=index),
    )


def load_failure_triage_evidence(
    input_path: Path | str,
    *,
    dataset: RealWorldDataset,
) -> FailureTriageEvidence:
    """读取独立的 1.0 失败证据，且只接受已准入案例。"""
    payload = _read_json(Path(input_path).resolve())
    unknown = sorted(set(payload) - _ROOT_FIELDS)
    if unknown:
        raise FailureTriageInputError(f"失败分诊输入含未知字段：{', '.join(unknown)}")
    if payload.get("schema_version") != FAILURE_TRIAGE_SCHEMA_VERSION:
        raise FailureTriageInputError(
            f"不支持的 schema_version：{payload.get('schema_version')}"
        )
    if payload.get("taxonomy_version") != FAILURE_TAXONOMY_VERSION:
        raise FailureTriageInputError(
            f"不支持的 taxonomy_version：{payload.get('taxonomy_version')}"
        )
    data_version = payload.get("data_version")
    if data_version != dataset.dataset_version:
        raise FailureTriageInputError(
            f"数据版本不一致：输入={data_version}，清单={dataset.dataset_version}"
        )
    raw_failures = payload.get("failures")
    if not isinstance(raw_failures, list):
        raise FailureTriageInputError("failures 必须是数组")

    failures = tuple(
        _build_failure(raw, index=index) for index, raw in enumerate(raw_failures)
    )
    eligible_ids = {case.id for case in dataset.eligible_cases()}
    invalid_ids = sorted({item.case_id for item in failures} - eligible_ids)
    if invalid_ids:
        raise FailureTriageInputError(
            f"失败记录引用了未准入或不存在的案例：{', '.join(invalid_ids)}"
        )
    pairs = [(item.case_id, item.code) for item in failures]
    if len(set(pairs)) != len(pairs):
        raise FailureTriageInputError("输入包含重复失败记录（case_id + code）")
    return FailureTriageEvidence(
        schema_version=FAILURE_TRIAGE_SCHEMA_VERSION,
        taxonomy_version=FAILURE_TAXONOMY_VERSION,
        data_version=dataset.dataset_version,
        failures=failures,
    )


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
            "failure_count": len(grouped[value]),
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
                "failure_count": len(records),
                "affected_case_count": len({item.case_id for item in records}),
                "splits": sorted(
                    {case_splits[item.case_id] for item in records},
                    key=lambda value: (_SPLITS.index(value), value),
                ),
                "case_ids": sorted({aliases[item.case_id] for item in records}),
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
            "failure_count": len(grouped[token]),
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
            "failure_count": len(by_split[split]),
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
        },
        "anonymization": {
            "algorithm": "hmac-sha256-80",
            "salt_id": salt_id.strip(),
        },
        "summary": {
            "eligible_case_count": len(eligible),
            "failure_count": len(failures),
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
