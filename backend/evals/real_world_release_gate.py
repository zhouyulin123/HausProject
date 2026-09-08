"""受控环境中的真实案例发布回归门禁。

普通 CI 只能调用 ``detect`` 判断当前变更是否需要证明。只有具备私有案例、
真实数据库运行绑定、受控 HTTPS 部署和两组独立密钥的 self-hosted 环境，才能
调用 ``verify`` 生成发布证明。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from app.core.config import settings
from app.services.generation_provenance import (
    canonical_digest,
    current_generation_rules_digest,
)
from app.services.llm_service import generation_prompt_snapshot
from evals.collect_real_world_evidence import main as collect_evidence_main
from evals.collect_security_access_evidence import main as collect_security_main
from evals.failure_triage import (
    build_failure_triage_report,
    build_failure_triage_sync_payload,
    derive_failure_triage_evidence,
    render_failure_triage_markdown,
)
from evals.real_world import (
    EvaluationInputError,
    EvaluationSplit,
    EvaluationVersions,
    RealWorldDataset,
    load_case_manifest,
)
from evals.release_change_detection import (
    SensitiveChanges,
    changed_paths_between,
    classify_release_sensitive_paths,
)
from evals.run_real_world_eval import (
    build_evaluation_report,
    compare_evaluation_reports,
    load_case_results,
)
from evals.trusted_evidence import EVIDENCE_SCHEMA_VERSION, VerifiedEvaluationEvidence


RELEASE_GATE_SCHEMA_VERSION = "1.0"
MIN_PRIVATE_REAL_CASES = 20
REQUIRED_SPLITS: tuple[EvaluationSplit, ...] = (
    "development",
    "regression",
    "blind",
)
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
@dataclass(frozen=True)
class ReleaseSplitConfig:
    manifest: Path
    asset_root: Path
    run_bindings: Path
    security_targets: Path
    baseline_evidence: Path
    deployment_base_url: str


@dataclass(frozen=True)
class VerifiedReleaseSplit:
    split: EvaluationSplit
    dataset: RealWorldDataset
    candidate: VerifiedEvaluationEvidence
    report: dict[str, Any]


def validate_release_event(
    event_name: str,
    splits: tuple[EvaluationSplit, ...],
) -> None:
    if event_name == "pull_request" and "blind" in splits:
        raise EvaluationInputError("PR 不得读取或执行 blind 真实案例评测")
    if event_name != "workflow_dispatch":
        raise EvaluationInputError("发布证明只能由受控 workflow_dispatch 签发")
    if splits != REQUIRED_SPLITS:
        raise EvaluationInputError("发布证明必须完整执行 development/regression/blind")


def validate_release_dataset(
    dataset: RealWorldDataset,
    *,
    split: EvaluationSplit,
) -> None:
    selected = [case for case in dataset.cases if case.split == split]
    if any(case.origin == "synthetic" for case in selected):
        raise EvaluationInputError(f"split={split} 含 synthetic 案例，不能作为发布证明")
    eligible = dataset.eligible_cases(split)
    if not eligible:
        raise EvaluationInputError(f"split={split} 没有准入真实案例，发布门禁失败关闭")
    if any(case.origin not in {"private_real", "public_reference"} for case in eligible):
        raise EvaluationInputError(f"split={split} 包含非真实来源案例")
    if not any(case.origin == "private_real" for case in eligible):
        raise EvaluationInputError(
            f"split={split} 缺少准入 private_real 案例，公开参考案例不能替代真实客户案例"
        )


def validate_release_cohort(
    datasets: Mapping[EvaluationSplit, RealWorldDataset],
) -> int:
    """验证三组发布案例构成，并按物理资产摘要跨清单去重。"""
    missing_splits = [split for split in REQUIRED_SPLITS if split not in datasets]
    if missing_splits:
        raise EvaluationInputError(
            f"发布案例队列缺少 split：{', '.join(missing_splits)}"
        )

    seen_assets: set[str] = set()
    for split in REQUIRED_SPLITS:
        dataset = datasets[split]
        private_cases = [
            case
            for case in dataset.eligible_cases(split)
            if case.origin == "private_real"
        ]
        if not private_cases:
            raise EvaluationInputError(
                f"split={split} 缺少准入 private_real 案例"
            )
        for case in private_cases:
            if case.asset_sha256 in seen_assets:
                raise EvaluationInputError("发布案例队列包含跨 split 重复物理案例")
            seen_assets.add(case.asset_sha256)

    if len(seen_assets) < MIN_PRIVATE_REAL_CASES:
        raise EvaluationInputError(
            "发布案例队列至少需要 "
            f"{MIN_PRIVATE_REAL_CASES} 个去重 private_real 案例，当前为 {len(seen_assets)} 个"
        )
    return len(seen_assets)


def validate_candidate_review_coverage(
    evidence: VerifiedEvaluationEvidence,
    *,
    split: EvaluationSplit,
    label: str = "候选",
) -> int:
    completed = [result for result in evidence.results if result.generation_succeeded]
    invalid = [result for result in completed if result.human_review_count != 1]
    if not completed or invalid:
        raise EvaluationInputError(
            f"split={split} {label}可信证据必须为每个成功运行绑定一份 execution_review"
        )
    return len(completed)


def _resolve_config_path(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationInputError(f"发布门禁配置缺少 {field}")
    path = Path(value.strip())
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _validate_https_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationInputError("发布门禁配置缺少 deployment_base_url")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise EvaluationInputError("受控评测部署必须使用无凭据、无查询参数的 HTTPS URL")
    return value.strip().rstrip("/")


def load_release_gate_config(path: Path | str) -> dict[EvaluationSplit, ReleaseSplitConfig]:
    config_path = Path(path).resolve()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationInputError("无法读取发布门禁私有配置") from exc
    if not isinstance(payload, dict):
        raise EvaluationInputError("发布门禁配置根节点必须是对象")
    unknown = sorted(set(payload) - {"schema_version", "splits"})
    if unknown:
        raise EvaluationInputError(f"发布门禁配置包含未知字段：{', '.join(unknown)}")
    if payload.get("schema_version") != RELEASE_GATE_SCHEMA_VERSION:
        raise EvaluationInputError("发布门禁配置 schema_version 不受支持")
    raw_splits = payload.get("splits")
    if not isinstance(raw_splits, dict) or tuple(raw_splits) != REQUIRED_SPLITS:
        raise EvaluationInputError("发布门禁配置必须按顺序完整包含三类 split")
    result: dict[EvaluationSplit, ReleaseSplitConfig] = {}
    expected_fields = {
        "manifest",
        "asset_root",
        "run_bindings",
        "security_targets",
        "baseline_evidence",
        "deployment_base_url",
    }
    for split in REQUIRED_SPLITS:
        raw = raw_splits.get(split)
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise EvaluationInputError(f"split={split} 配置字段不完整或包含未知字段")
        root = config_path.parent
        result[split] = ReleaseSplitConfig(
            manifest=_resolve_config_path(root, raw["manifest"], "manifest"),
            asset_root=_resolve_config_path(root, raw["asset_root"], "asset_root"),
            run_bindings=_resolve_config_path(root, raw["run_bindings"], "run_bindings"),
            security_targets=_resolve_config_path(
                root, raw["security_targets"], "security_targets"
            ),
            baseline_evidence=_resolve_config_path(
                root, raw["baseline_evidence"], "baseline_evidence"
            ),
            deployment_base_url=_validate_https_url(raw["deployment_base_url"]),
        )
    return result


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise EvaluationInputError(f"受控发布门禁缺少环境变量 {name}")
    return value


def _validate_build_digest(value: str) -> str:
    if not _DIGEST_PATTERN.fullmatch(value):
        raise EvaluationInputError("APP_BUILD_DIGEST 必须是 sha256:<64 hex>")
    return value


def _evidence_build_digest(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        security = payload["security_access_attestation"]
        value = security["app_build_digest"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise EvaluationInputError("基线缺少独立安全构建绑定") from exc
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise EvaluationInputError("基线独立安全构建绑定不合法")
    return value


def validate_release_evidence(
    evidence: VerifiedEvaluationEvidence,
    *,
    expected_build_digest: str,
    label: str,
) -> None:
    if evidence.schema_version != EVIDENCE_SCHEMA_VERSION:
        raise EvaluationInputError(
            f"{label}不是 trusted evidence {EVIDENCE_SCHEMA_VERSION}"
        )
    if evidence.signature_verified is not True:
        raise EvaluationInputError(f"{label}评测证据未通过签名验证")
    if (
        evidence.security_evidence_digest is None
        or evidence.security_key_id is None
        or evidence.app_build_digest != expected_build_digest
    ):
        raise EvaluationInputError(f"{label}缺少匹配构建的独立安全证明")


def validate_candidate_runtime_versions(
    versions: EvaluationVersions,
    *,
    expected_model: str,
    expected_prompt: str,
    expected_rules: str,
) -> None:
    expected = {
        "model": expected_model,
        "prompt": expected_prompt,
        "rules": expected_rules,
    }
    actual = asdict(versions)
    labels = {"model": "模型", "prompt": "Prompt", "rules": "规则"}
    for field, expected_value in expected.items():
        if actual[field] != expected_value:
            raise EvaluationInputError(
                f"候选{labels[field]}版本与目标提交或受控部署配置不一致"
            )


def _collector_args(config: ReleaseSplitConfig, split: EvaluationSplit) -> list[str]:
    return [
        "--manifest",
        str(config.manifest),
        "--split",
        split,
        "--asset-root",
        str(config.asset_root),
    ]


def _generate_candidate_failure_triage_artifacts(
    *,
    dataset: RealWorldDataset,
    evidence: VerifiedEvaluationEvidence,
    split: EvaluationSplit,
    output_dir: Path,
    candidate_version: str,
    anonymization_salt: str,
    salt_id: str,
    signing_key_id: str,
    signing_key: str,
) -> dict[str, Any]:
    """从已验签候选证据生成脱敏且签名的受控发布制品。"""
    if evidence.split != split:
        raise EvaluationInputError("失败分诊候选证据与目标 split 不一致")
    triage_evidence = derive_failure_triage_evidence(
        evidence=evidence,
        dataset=dataset,
    )
    report = build_failure_triage_report(
        dataset=dataset,
        evidence=triage_evidence,
        anonymization_salt=anonymization_salt,
        salt_id=salt_id,
    )
    report["sync_payload"] = build_failure_triage_sync_payload(
        report,
        report_id=f"release-{candidate_version}-{split}",
        candidate_version=candidate_version,
        signing_key_id=signing_key_id,
        signing_key=signing_key,
    )
    markdown = render_failure_triage_markdown(report)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{split}.failure_triage.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / f"{split}.failure_triage.md").write_text(
            markdown,
            encoding="utf-8",
        )
    except OSError as exc:
        raise EvaluationInputError(
            f"split={split} 失败分诊制品写入失败"
        ) from exc
    return {
        "schema_version": report["schema_version"],
        "taxonomy_version": report["input"]["taxonomy_version"],
        "failure_count": report["summary"]["failure_count"],
        "affected_case_count": report["summary"]["affected_case_count"],
        "report_digest": canonical_digest(report),
        "signature_key_id": signing_key_id,
    }


def _clear_failure_triage_artifacts(output_dir: Path) -> None:
    triage_dir = output_dir / "failure-triage"
    if not triage_dir.exists():
        return
    try:
        shutil.rmtree(triage_dir)
    except OSError as exc:
        raise EvaluationInputError("无法清理旧失败分诊制品") from exc


def _publish_failure_triage_artifacts(
    *,
    verified_splits: tuple[VerifiedReleaseSplit, ...],
    output_dir: Path,
    candidate_version: str,
    anonymization_salt: str,
    salt_id: str,
    signing_key_id: str,
    signing_key: str,
) -> dict[EvaluationSplit, dict[str, Any]]:
    """三组全部生成成功后，将 staging 目录一次发布到 artifact 路径。"""
    if tuple(item.split for item in verified_splits) != REQUIRED_SPLITS:
        raise EvaluationInputError("失败分诊必须按顺序完整覆盖三类 split")
    output_dir.mkdir(parents=True, exist_ok=True)
    final_dir = output_dir / "failure-triage"
    if final_dir.exists():
        raise EvaluationInputError("失败分诊发布目录必须在运行开始前清空")
    summaries: dict[EvaluationSplit, dict[str, Any]] = {}
    try:
        with tempfile.TemporaryDirectory(
            prefix=".failure-triage-staging-",
            dir=output_dir,
        ) as raw_staging:
            staging_dir = Path(raw_staging)
            for item in verified_splits:
                summaries[item.split] = _generate_candidate_failure_triage_artifacts(
                    dataset=item.dataset,
                    evidence=item.candidate,
                    split=item.split,
                    output_dir=staging_dir,
                    candidate_version=candidate_version,
                    anonymization_salt=anonymization_salt,
                    salt_id=salt_id,
                    signing_key_id=signing_key_id,
                    signing_key=signing_key,
                )
            staging_dir.replace(final_dir)
    except OSError as exc:
        raise EvaluationInputError("失败分诊制品原子发布失败") from exc
    return summaries


def _verify_split(
    config: ReleaseSplitConfig,
    *,
    split: EvaluationSplit,
    dataset: RealWorldDataset | None = None,
    work_dir: Path,
    app_build_digest: str,
    eval_keys: Mapping[str, str],
    security_keys: Mapping[str, str],
) -> VerifiedReleaseSplit:
    dataset = dataset or load_case_manifest(
        config.manifest,
        asset_root=config.asset_root,
    )
    validate_release_dataset(dataset, split=split)
    security_output = work_dir / f"{split}.security.evidence.json"
    candidate_output = work_dir / f"{split}.candidate.evidence.json"
    security_exit = collect_security_main(
        [
            *_collector_args(config, split),
            "--targets",
            str(config.security_targets),
            "--base-url",
            config.deployment_base_url,
            "--app-build-digest",
            app_build_digest,
            "--output",
            str(security_output),
        ]
    )
    if security_exit != 0:
        raise EvaluationInputError(f"split={split} 独立 HTTP 安全回归失败")
    evidence_exit = collect_evidence_main(
        [
            *_collector_args(config, split),
            "--run-bindings",
            str(config.run_bindings),
            "--security-evidence",
            str(security_output),
            "--output",
            str(candidate_output),
        ]
    )
    if evidence_exit != 0:
        raise EvaluationInputError(f"split={split} trusted evidence 签发失败")

    candidate = load_case_results(
        candidate_output,
        dataset=dataset,
        split=split,
        verification_keys=eval_keys,
        security_verification_keys=security_keys,
        expected_app_build_digest=app_build_digest,
    )
    baseline_build_digest = _evidence_build_digest(config.baseline_evidence)
    baseline = load_case_results(
        config.baseline_evidence,
        dataset=dataset,
        split=split,
        verification_keys=eval_keys,
        security_verification_keys=security_keys,
        expected_app_build_digest=baseline_build_digest,
    )
    validate_release_evidence(
        candidate,
        expected_build_digest=app_build_digest,
        label="候选",
    )
    validate_release_evidence(
        baseline,
        expected_build_digest=baseline_build_digest,
        label="基线",
    )
    execution_review_count = validate_candidate_review_coverage(
        candidate,
        split=split,
    )
    baseline_execution_review_count = validate_candidate_review_coverage(
        baseline,
        split=split,
        label="基线",
    )
    if candidate.evidence_digest == baseline.evidence_digest:
        raise EvaluationInputError(f"split={split} 候选不得重放基线证据")
    candidate_report = build_evaluation_report(
        dataset=dataset,
        split=split,
        evidence=candidate,
    )
    baseline_report = build_evaluation_report(
        dataset=dataset,
        split=split,
        evidence=baseline,
    )
    comparison = compare_evaluation_reports(candidate_report, baseline_report)
    report = {
        "split": split,
        "dataset_fingerprint": candidate.dataset_fingerprint,
        "eligible_case_count": len(dataset.eligible_cases(split)),
        "origin_counts": candidate_report["dataset"]["origin_counts"],
        "execution_review_count": execution_review_count,
        "baseline_execution_review_count": baseline_execution_review_count,
        "candidate_versions": asdict(candidate.versions),
        "baseline_versions": asdict(baseline.versions),
        "candidate_evidence_digest": candidate.evidence_digest,
        "baseline_evidence_digest": baseline.evidence_digest,
        "absolute_gate_passed": candidate_report["gate_passed"],
        "regression_passed": comparison["passed"],
        "comparison_items": comparison["items"],
    }
    return VerifiedReleaseSplit(
        split=split,
        dataset=dataset,
        candidate=candidate,
        report=report,
    )


def _write_report(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "real_world_release_gate.json"
    markdown_path = output_dir / "real_world_release_gate.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# 真实案例发布门禁",
        "",
        f"- 结论：{'PASS' if report.get('overall_passed') else 'FAIL'}",
        f"- 状态：{report['status']}",
        f"- 提交：{report.get('commit_sha', 'unknown')}",
        f"- 构建：{report.get('app_build_digest', 'unknown')}",
    ]
    for item in report.get("splits", []):
        lines.append(
            f"- {item['split']}：绝对门禁="
            f"{'PASS' if item['absolute_gate_passed'] else 'FAIL'}，回归="
            f"{'PASS' if item['regression_passed'] else 'FAIL'}，"
            f"真实案例={item['eligible_case_count']}"
        )
        triage = item.get("failure_triage")
        if isinstance(triage, dict):
            lines.append(
                f"  - 脱敏失败分诊：失败记录={triage['failure_count']}，"
                f"受影响案例={triage['affected_case_count']}"
            )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _change_summary(changes: SensitiveChanges) -> dict[str, Any]:
    return {
        "required": changes.required,
        "status": changes.status,
        "category_counts": {
            category: len(paths) for category, paths in changes.by_category.items()
        },
    }


def _verify(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    commit_sha = ""
    app_build_digest = ""
    changes: SensitiveChanges | None = None
    try:
        _clear_failure_triage_artifacts(output_dir)
        commit_sha = _required_environment("GITHUB_SHA").lower()
        base_ref = _required_environment("REAL_WORLD_BASE_REF")
        event_name = _required_environment("GITHUB_EVENT_NAME")
        if not _COMMIT_PATTERN.fullmatch(commit_sha):
            raise EvaluationInputError("GITHUB_SHA 不是完整提交摘要")
        validate_release_event(event_name, REQUIRED_SPLITS)
        app_build_digest = _validate_build_digest(_required_environment("APP_BUILD_DIGEST"))
        paths = changed_paths_between(
            Path(args.repo_root).resolve(),
            base_ref=base_ref,
            head_ref=commit_sha,
        )
        changes = classify_release_sensitive_paths(paths)
        config = load_release_gate_config(
            _required_environment("REAL_WORLD_RELEASE_GATE_CONFIG_PATH")
        )
        datasets = {
            split: load_case_manifest(
                config[split].manifest,
                asset_root=config[split].asset_root,
            )
            for split in REQUIRED_SPLITS
        }
        for split in REQUIRED_SPLITS:
            validate_release_dataset(datasets[split], split=split)
        private_real_case_count = validate_release_cohort(datasets)
        eval_key_id = _required_environment("EVAL_EVIDENCE_KEY_ID")
        eval_key = _required_environment("EVAL_EVIDENCE_HMAC_KEY")
        security_key_id = _required_environment("SECURITY_EVIDENCE_KEY_ID")
        security_key = _required_environment("SECURITY_EVIDENCE_HMAC_KEY")
        if eval_key_id == security_key_id or eval_key == security_key:
            raise EvaluationInputError("评测证据与安全证据必须使用独立密钥域")
        anonymization_salt = _required_environment("EVAL_CASE_ID_SALT")
        salt_id = _required_environment("EVAL_CASE_ID_SALT_ID")
        triage_signing_key_id = _required_environment("EVAL_REPORT_SIGNING_KEY_ID")
        triage_signing_key = _required_environment("EVAL_REPORT_SIGNING_KEY")
        if len({eval_key_id, security_key_id, triage_signing_key_id, salt_id}) != 4:
            raise EvaluationInputError("评测、安全、分诊签名与脱敏必须使用独立密钥标识")
        if len({eval_key, security_key, triage_signing_key, anonymization_salt}) != 4:
            raise EvaluationInputError("评测、安全、分诊签名与脱敏必须使用独立密钥域")
        expected_model = settings.llm_model
        expected_prompt = canonical_digest(generation_prompt_snapshot())
        expected_rules = current_generation_rules_digest()
        with tempfile.TemporaryDirectory(prefix="real-world-release-gate-") as raw_dir:
            work_dir = Path(raw_dir)
            verified_splits = tuple(
                _verify_split(
                    config[split],
                    split=split,
                    dataset=datasets[split],
                    work_dir=work_dir,
                    app_build_digest=app_build_digest,
                    eval_keys={eval_key_id: eval_key},
                    security_keys={security_key_id: security_key},
                )
                for split in REQUIRED_SPLITS
            )
        split_reports = [item.report for item in verified_splits]
        versions = {
            tuple(sorted(item["candidate_versions"].items())) for item in split_reports
        }
        if len(versions) != 1:
            raise EvaluationInputError("三类 split 的候选模型/Prompt/规则/数据版本不一致")
        for item in split_reports:
            validate_candidate_runtime_versions(
                EvaluationVersions(**item["candidate_versions"]),
                expected_model=expected_model,
                expected_prompt=expected_prompt,
                expected_rules=expected_rules,
            )
        triage_summaries = _publish_failure_triage_artifacts(
            verified_splits=verified_splits,
            output_dir=output_dir,
            candidate_version=commit_sha,
            anonymization_salt=anonymization_salt,
            salt_id=salt_id,
            signing_key_id=triage_signing_key_id,
            signing_key=triage_signing_key,
        )
        for item in split_reports:
            item["failure_triage"] = triage_summaries[item["split"]]
        passed = all(
            item["absolute_gate_passed"] and item["regression_passed"]
            for item in split_reports
        )
        report = {
            "schema_version": RELEASE_GATE_SCHEMA_VERSION,
            "proof_type": "real_world_release_regression",
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "status": "passed" if passed else "quality_regression",
            "overall_passed": passed,
            "commit_sha": commit_sha,
            "app_build_digest": app_build_digest,
            "change_detection": _change_summary(changes),
            "private_real_case_count": private_real_case_count,
            "splits": split_reports,
        }
        _write_report(output_dir, report)
        print(f"REAL_WORLD_RELEASE_GATE={'PASS' if passed else 'FAIL'}")
        return 0 if passed else 1
    except (EvaluationInputError, OSError, ValueError):
        try:
            _clear_failure_triage_artifacts(output_dir)
        except EvaluationInputError:
            pass
        report = {
            "schema_version": RELEASE_GATE_SCHEMA_VERSION,
            "proof_type": "real_world_release_regression",
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "status": "invalid_or_missing_evidence",
            "error_code": "release_gate_input_invalid",
            "overall_passed": False,
            "commit_sha": commit_sha or "unknown",
            "app_build_digest": app_build_digest or "unknown",
            "change_detection": _change_summary(changes) if changes else None,
            "splits": [],
        }
        _write_report(output_dir, report)
        print("REAL_WORLD_RELEASE_GATE_ERROR=release_gate_input_invalid")
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="真实案例发布回归门禁")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return _verify(args)
    except (EvaluationInputError, ValueError):
        print("REAL_WORLD_RELEASE_GATE_ERROR=release_gate_input_invalid")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
