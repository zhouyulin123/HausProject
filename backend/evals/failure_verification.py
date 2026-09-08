"""受保护环境生成完整三切分失败簇复测证明。"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.failure_triage_service import failure_fingerprint
from app.services.failure_triage_signature import (
    sign_failure_triage_payload,
    verify_failure_triage_signature,
)
from app.services.generation_provenance import canonical_digest
from app.schemas.failure_triage import FailureTriageReportRequest


SPLITS: tuple[str, ...] = ("blind", "development", "regression")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
_MAX_JSON_BYTES = 2 * 1024 * 1024
_REPORT_SCHEMA_VERSION = "1.0"
_REPORT_TYPE = "failure_verification"


def _read_json(path: Path | str, *, label: str) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        if source.stat().st_size > _MAX_JSON_BYTES:
            raise ValueError(f"{label} 文件过大")
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取{label}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} 必须是对象")
    return payload


def _digest(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} 不是合法 sha256 摘要")
    return value


def _sorted_unique_digests(values: Sequence[Any], *, field: str) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field} 必须是摘要列表")
    result = [_digest(value, field=field) for value in values]
    if result != sorted(set(result)):
        raise ValueError(f"{field} 必须排序去重")
    return result


def _load_targets(path: Path | str) -> list[dict[str, str]]:
    payload = _read_json(path, label="受控失败簇目标列表")
    if set(payload) != {"schema_version", "verified_clusters"} or payload.get(
        "schema_version"
    ) != _REPORT_SCHEMA_VERSION:
        raise ValueError("受控失败簇目标列表 schema 不合法")
    raw_targets = payload.get("verified_clusters")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError("受控失败簇目标列表必须显式提供 verified_clusters")
    targets: list[dict[str, str]] = []
    seen: set[str] = set()
    for target in raw_targets:
        if not isinstance(target, dict) or set(target) != {"fingerprint", "fixed_version"}:
            raise ValueError("受控失败簇目标字段不合法")
        fingerprint = target.get("fingerprint")
        fixed_version = target.get("fixed_version")
        if (
            not isinstance(fingerprint, str)
            or _FINGERPRINT_PATTERN.fullmatch(fingerprint) is None
            or not isinstance(fixed_version, str)
            or not fixed_version.strip()
            or len(fixed_version.strip()) > 100
        ):
            raise ValueError("受控失败簇目标 fingerprint 或 fixed_version 不合法")
        if fingerprint in seen:
            raise ValueError("受控失败簇目标包含重复 fingerprint")
        seen.add(fingerprint)
        targets.append(
            {"fingerprint": fingerprint, "fixed_version": fixed_version.strip()}
        )
    return sorted(targets, key=lambda item: item["fingerprint"])


def _triage_details(
    report: Mapping[str, Any],
    *,
    split: str,
    signing_key: str,
) -> tuple[dict[str, str], set[str], list[str]]:
    if not isinstance(report.get("input"), dict):
        raise ValueError(f"split={split} 分诊报告缺少 input")
    report_input = report["input"]
    sync_payload = report.get("sync_payload")
    if not isinstance(sync_payload, dict):
        raise ValueError(f"split={split} 分诊报告缺少签名 sync_payload")
    try:
        sync = FailureTriageReportRequest.model_validate(sync_payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"split={split} 分诊 sync_payload 不合法") from exc
    if not verify_failure_triage_signature(sync_payload, signing_key=signing_key):
        raise ValueError(f"split={split} 分诊 sync_payload 签名无效")
    input_digests = {
        "manifest_digest": _digest(report_input.get("manifest_digest"), field="manifest_digest"),
        "evidence_digest": _digest(report_input.get("evidence_digest"), field="evidence_digest"),
    }
    if sync.manifest_digest != input_digests["manifest_digest"]:
        raise ValueError(f"split={split} 分诊 manifest 摘要不一致")
    if sync.evidence_digest != input_digests["evidence_digest"]:
        raise ValueError(f"split={split} 分诊 evidence 摘要不一致")
    if report_input.get("taxonomy_version") != sync.taxonomy_version:
        raise ValueError(f"split={split} 分诊 taxonomy 版本不一致")
    if report_input.get("data_version") != sync.data_version:
        raise ValueError(f"split={split} 分诊 data 版本不一致")
    output_digests = _sorted_unique_digests(
        report_input.get("output_digests"),
        field=f"split={split} output_digests",
    )
    if sync.output_digests != output_digests:
        raise ValueError(f"split={split} 分诊 output 摘要不一致")
    fingerprints = {
        failure_fingerprint(
            taxonomy_version=sync.taxonomy_version,
            data_version=sync.data_version,
            failure_type=item.failure_type,
            code=item.code,
        )
        for item in sync.failures
    }
    return (
        {
            "taxonomy_version": sync.taxonomy_version,
            "data_version": sync.data_version,
            "candidate_version": sync.candidate_version,
            **input_digests,
        },
        fingerprints,
        output_digests,
    )


def build_failure_verification_report(
    *,
    release_gate_report: Mapping[str, Any],
    triage_reports: Mapping[str, Mapping[str, Any]],
    targets: Sequence[Mapping[str, str]],
    signing_key: str,
    signing_key_id: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """仅从完整三 split 受控输入签发匿名失败簇复测证明。"""
    if (
        release_gate_report.get("schema_version") != "1.0"
        or release_gate_report.get("proof_type") != "real_world_release_regression"
        or release_gate_report.get("status") != "passed"
        or release_gate_report.get("overall_passed") is not True
    ):
        raise ValueError("真实案例发布门禁报告身份或状态不合法")
    commit_sha = release_gate_report.get("commit_sha")
    if not isinstance(commit_sha, str) or _COMMIT_PATTERN.fullmatch(commit_sha) is None:
        raise ValueError("真实案例发布门禁提交摘要不合法")
    raw_splits = release_gate_report.get("splits")
    if not isinstance(raw_splits, list) or {
        item.get("split") for item in raw_splits if isinstance(item, dict)
    } != set(SPLITS):
        raise ValueError("发布门禁必须完整覆盖三 split")
    if len(raw_splits) != len(SPLITS):
        raise ValueError("发布门禁包含重复或额外 split")
    split_by_name = {item["split"]: item for item in raw_splits}
    if set(triage_reports) != set(SPLITS):
        raise ValueError("失败分诊必须完整覆盖三 split")
    if not isinstance(signing_key, str) or len(signing_key.encode("utf-8")) < 32:
        raise ValueError("失败复测证明签名密钥至少需要 32 字节")
    if not isinstance(signing_key_id, str) or not signing_key_id.strip():
        raise ValueError("失败复测证明签名 key_id 缺失")
    if _IDENTIFIER_PATTERN.fullmatch(signing_key_id.strip()) is None:
        raise ValueError("失败复测证明签名 key_id 不合法")

    manifest_digests: list[str] = []
    evidence_digests: list[str] = []
    baseline_digests: list[str] = []
    output_digests: set[str] = set()
    versions: set[tuple[str, str, str]] = set()
    candidate_fingerprints: dict[str, set[str]] = {}
    for split in SPLITS:
        triage_report = triage_reports[split]
        if not isinstance(triage_report, Mapping):
            raise ValueError(f"split={split} 分诊报告必须是对象")
        gate_item = split_by_name[split]
        if gate_item.get("absolute_gate_passed") is not True or gate_item.get(
            "regression_passed"
        ) is not True:
            raise ValueError(f"split={split} 发布门禁未通过")
        manifest_digests.append(_digest(gate_item.get("dataset_fingerprint"), field="manifest_digest"))
        evidence_digests.append(_digest(gate_item.get("candidate_evidence_digest"), field="evidence_digest"))
        baseline_digests.append(
            _digest(gate_item.get("baseline_evidence_digest"), field="baseline_evidence_digest")
        )
        details, fingerprints, split_outputs = _triage_details(
            triage_report,
            split=split,
            signing_key=signing_key,
        )
        if details["manifest_digest"] != manifest_digests[-1]:
            raise ValueError(f"split={split} 分诊与门禁 manifest 摘要不一致")
        if details["evidence_digest"] != evidence_digests[-1]:
            raise ValueError(f"split={split} 分诊与门禁 evidence 摘要不一致")
        raw_clusters = triage_report.get("clusters")
        if not isinstance(raw_clusters, list):
            raise ValueError(f"split={split} 分诊报告缺少 clusters")
        report_fingerprints: set[str] = set()
        for cluster in raw_clusters:
            if not isinstance(cluster, Mapping):
                raise ValueError(f"split={split} 分诊聚类不合法")
            failure_type = cluster.get("failure_type")
            code = cluster.get("code")
            if not isinstance(failure_type, str) or not isinstance(code, str):
                raise ValueError(f"split={split} 分诊聚类缺少失败类型")
            report_fingerprints.add(
                failure_fingerprint(
                    taxonomy_version=details["taxonomy_version"],
                    data_version=details["data_version"],
                    failure_type=failure_type,
                    code=code,
                )
            )
        if report_fingerprints != fingerprints:
            raise ValueError(f"split={split} 分诊聚类与签名摘要不一致")
        triage_summary = gate_item.get("failure_triage")
        if not isinstance(triage_summary, dict) or triage_summary.get(
            "report_digest"
        ) != canonical_digest(triage_report):
            raise ValueError(f"split={split} 分诊报告摘要不匹配")
        versions.add(
            (details["taxonomy_version"], details["data_version"], details["candidate_version"])
        )
        output_digests.update(split_outputs)
        candidate_fingerprints[split] = fingerprints
    if len(set(manifest_digests)) != len(SPLITS):
        raise ValueError("三 split manifest 摘要必须分别唯一")
    if len(set(evidence_digests)) != len(SPLITS):
        raise ValueError("三 split evidence 摘要必须分别唯一")
    if len(set(baseline_digests)) != len(SPLITS):
        raise ValueError("三 split baseline evidence 摘要必须分别唯一")
    if len(versions) != 1:
        raise ValueError("三 split 版本上下文不一致")
    taxonomy_version, data_version, candidate_version = next(iter(versions))
    if candidate_version != commit_sha:
        raise ValueError("三 split 候选版本与门禁提交不一致")
    if not output_digests:
        raise ValueError("失败复测证明缺少 output 摘要")
    if not targets:
        raise ValueError("失败复测证明必须显式提供 verified_clusters")
    normalized_targets = []
    seen_targets: set[str] = set()
    for target in targets:
        if not isinstance(target, Mapping) or set(target) != {
            "fingerprint",
            "fixed_version",
        }:
            raise ValueError("verified_clusters 字段不合法")
        fingerprint = target.get("fingerprint")
        fixed_version = target.get("fixed_version")
        if (
            not isinstance(fingerprint, str)
            or _FINGERPRINT_PATTERN.fullmatch(fingerprint) is None
            or not isinstance(fixed_version, str)
            or not fixed_version.strip()
            or len(fixed_version.strip()) > 100
            or fingerprint in seen_targets
        ):
            raise ValueError("verified_clusters 目标不合法或重复")
        seen_targets.add(fingerprint)
        normalized_targets.append(
            {"fingerprint": fingerprint, "fixed_version": fixed_version.strip()}
        )
    normalized_targets.sort(key=lambda item: item["fingerprint"])
    for target in normalized_targets:
        recurring = [
            split for split in SPLITS if target["fingerprint"] in candidate_fingerprints[split]
        ]
        if recurring:
            raise ValueError(
                f"目标失败簇在候选三 split 中复现：{','.join(recurring)}"
            )
    target_digest = canonical_digest(normalized_targets).removeprefix("sha256:")

    timestamp = generated_at or datetime.now(timezone.utc)
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
        raise ValueError("generated_at 必须包含时区")
    unsigned: dict[str, Any] = {
        "schema_version": _REPORT_SCHEMA_VERSION,
        "report_type": _REPORT_TYPE,
        "report_id": f"failure-verification-{commit_sha}-{target_digest[:12]}",
        "taxonomy_version": taxonomy_version,
        "data_version": data_version,
        "candidate_version": candidate_version,
        "release_gate_report_digest": canonical_digest(release_gate_report),
        "manifest_digests": sorted(manifest_digests),
        "evidence_digests": sorted(evidence_digests),
        "baseline_evidence_digests": sorted(baseline_digests),
        "output_digests": sorted(output_digests),
        "covered_splits": list(SPLITS),
        "verified_clusters": normalized_targets,
        "signature_algorithm": "hmac-sha256",
        "signature_key_id": signing_key_id.strip(),
        "generated_at": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    unsigned["signature"] = sign_failure_triage_payload(
        unsigned,
        signing_key=signing_key,
    )
    return unsigned


def write_failure_verification_report(
    *,
    release_gate_report_path: Path | str,
    triage_dir: Path | str,
    targets_path: Path | str,
    output_path: Path | str,
    signing_key: str,
    signing_key_id: str,
) -> dict[str, Any]:
    gate = _read_json(release_gate_report_path, label="发布门禁报告")
    root = Path(triage_dir).resolve()
    triage_reports = {
        split: _read_json(
            root / f"{split}.failure_triage.json",
            label=f"split={split} 失败分诊报告",
        )
        for split in SPLITS
    }
    targets = _load_targets(targets_path)
    report = build_failure_verification_report(
        release_gate_report=gate,
        triage_reports=triage_reports,
        targets=targets,
        signing_key=signing_key,
        signing_key_id=signing_key_id,
    )
    destination = Path(output_path).resolve()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(destination)
    except OSError as exc:
        raise ValueError("失败复测证明写入失败") from exc
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成三切分失败簇复测证明")
    parser.add_argument("--release-gate-report", type=Path, required=True)
    parser.add_argument("--triage-dir", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--signing-key-env",
        default="FAILURE_VERIFICATION_SIGNING_KEY",
    )
    parser.add_argument(
        "--signing-key-id-env",
        default="FAILURE_VERIFICATION_SIGNING_KEY_ID",
    )
    args = parser.parse_args(argv)
    try:
        write_failure_verification_report(
            release_gate_report_path=args.release_gate_report,
            triage_dir=args.triage_dir,
            targets_path=args.targets,
            output_path=args.output,
            signing_key=os.environ.get(args.signing_key_env, ""),
            signing_key_id=os.environ.get(args.signing_key_id_env, ""),
        )
    except (OSError, ValueError):
        print("REAL_WORLD_FAILURE_VERIFICATION_ERROR=invalid_or_incomplete_input")
        return 2
    print("REAL_WORLD_FAILURE_VERIFICATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
