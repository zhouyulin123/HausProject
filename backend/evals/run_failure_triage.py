"""阶段 4 结构化失败样本分诊 CLI。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from evals.failure_triage import (
    FailureTriageInputError,
    build_failure_triage_report,
    build_failure_triage_sync_payload,
    load_failure_triage_evidence,
    render_failure_triage_markdown,
)
from evals.real_world import DatasetValidationError, load_case_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成结构化失败样本分诊报告")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--failures", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument(
        "--case-id-salt-env",
        default="EVAL_CASE_ID_SALT",
        help="提供 case_id 脱敏密钥的环境变量名",
    )
    parser.add_argument(
        "--salt-id",
        default="default",
        help="写入报告的密钥版本标识，不得包含密钥本身",
    )
    parser.add_argument(
        "--signing-key-env",
        default="EVAL_REPORT_SIGNING_KEY",
        help="提供报告 HMAC 签名密钥的环境变量名",
    )
    parser.add_argument(
        "--signing-key-id",
        required=True,
        help="写入同步载荷的签名密钥版本，不得包含密钥本身",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        salt = os.environ.get(args.case_id_salt_env)
        if not salt:
            raise FailureTriageInputError(f"环境变量 {args.case_id_salt_env} 未配置")
        signing_key = os.environ.get(args.signing_key_env)
        if not signing_key:
            raise FailureTriageInputError(
                f"环境变量 {args.signing_key_env} 未配置"
            )
        dataset = load_case_manifest(args.manifest, asset_root=args.asset_root)
        if not dataset.eligible_cases():
            raise FailureTriageInputError("案例清单中没有已准入案例")
        evidence = load_failure_triage_evidence(args.failures, dataset=dataset)
        report = build_failure_triage_report(
            dataset=dataset,
            evidence=evidence,
            anonymization_salt=salt,
            salt_id=args.salt_id,
        )
        report["sync_payload"] = build_failure_triage_sync_payload(
            report,
            report_id=args.report_id,
            candidate_version=args.candidate_version,
            signing_key_id=args.signing_key_id,
            signing_key=signing_key,
        )
        markdown = render_failure_triage_markdown(report)
    except (FailureTriageInputError, DatasetValidationError) as exc:
        print(f"failure triage input error: {exc}")
        return 2

    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "failure_triage.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (args.output_dir / "failure_triage.md").write_text(
            markdown,
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"failure triage output error: {exc}")
        return 2

    failure_count = report["summary"]["failure_count"]
    print(f"failure triage records: {failure_count}")
    return 1 if failure_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
