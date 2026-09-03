"""从数据库中的已完成系统运行签发真实案例评测证据。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from typing import Any

from app.db.database import SessionLocal
from evals.real_world import (
    EvaluationInputError,
    EvaluationSplit,
    load_case_manifest,
)
from evals.trusted_evidence import RunBinding, collect_trusted_evidence


def _read_bindings(
    path: Path,
    *,
    split: EvaluationSplit,
) -> tuple[RunBinding, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationInputError(f"无法读取运行绑定：{exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") not in {
        "2.0",
        "3.0",
    }:
        raise EvaluationInputError("运行绑定 schema_version 必须为 2.0 或 3.0")
    if set(payload) != {"schema_version", "split", "bindings"}:
        raise EvaluationInputError("运行绑定包含未知字段")
    if payload.get("split") != split:
        raise EvaluationInputError("运行绑定 split 与命令行 split 不一致")
    raw_bindings = payload.get("bindings")
    if not isinstance(raw_bindings, list):
        raise EvaluationInputError("bindings 必须是数组")
    bindings: list[RunBinding] = []
    for index, raw in enumerate(raw_bindings):
        required_fields = {
            "case_id",
            "task_id",
            "system_run_id",
        }
        if payload["schema_version"] == "3.0":
            required_fields |= {
                "execution_review_path",
                "execution_review_sha256",
            }
        if not isinstance(raw, dict) or set(raw) != required_fields:
            raise EvaluationInputError(f"第 {index + 1} 条运行绑定字段不合法")
        case_id = raw.get("case_id")
        task_id = raw.get("task_id")
        run_id = raw.get("system_run_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise EvaluationInputError(f"第 {index + 1} 条运行绑定缺少 case_id")
        if (
            isinstance(task_id, bool)
            or not isinstance(task_id, int)
            or task_id <= 0
            or isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or run_id <= 0
        ):
            raise EvaluationInputError(f"第 {index + 1} 条运行绑定 ID 不合法")
        review_path = raw.get("execution_review_path")
        review_digest = raw.get("execution_review_sha256")
        if (review_path is None) != (review_digest is None):
            raise EvaluationInputError(
                f"第 {index + 1} 条人工评审路径与摘要必须成对提供"
            )
        if review_path is not None and (
            not isinstance(review_path, str)
            or not review_path.strip()
            or not isinstance(review_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", review_digest)
        ):
            raise EvaluationInputError(f"第 {index + 1} 条人工评审引用不合法")
        bindings.append(
            RunBinding(
                case_id.strip(),
                task_id,
                run_id,
                review_path.strip() if isinstance(review_path, str) else None,
                review_digest,
            )
        )
    return tuple(bindings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="签发真实系统执行评测证据")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--split",
        choices=("development", "regression", "blind"),
        required=True,
    )
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--run-bindings", type=Path, required=True)
    parser.add_argument(
        "--security-evidence",
        type=Path,
        help="独立跨用户 HTTP 安全回归签名制品",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        signing_key = os.getenv("EVAL_EVIDENCE_HMAC_KEY", "")
        key_id = os.getenv("EVAL_EVIDENCE_KEY_ID", "")
        if not signing_key or not key_id:
            raise EvaluationInputError(
                "缺少签名密钥：必须配置 EVAL_EVIDENCE_HMAC_KEY 和 EVAL_EVIDENCE_KEY_ID"
            )
        dataset = load_case_manifest(args.manifest, asset_root=args.asset_root)
        dataset_root = (
            args.asset_root.resolve()
            if args.asset_root is not None
            else args.manifest.resolve().parent
        )
        bindings = _read_bindings(args.run_bindings.resolve(), split=args.split)
        security_bundle = None
        security_keys: dict[str, str] = {}
        app_build_digest = None
        if args.security_evidence is not None:
            try:
                security_bundle = json.loads(
                    args.security_evidence.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise EvaluationInputError("无法读取独立安全证据") from exc
            if not isinstance(security_bundle, dict):
                raise EvaluationInputError("独立安全证据根节点必须是对象")
            security_key = os.getenv("SECURITY_EVIDENCE_HMAC_KEY", "")
            security_key_id = os.getenv("SECURITY_EVIDENCE_KEY_ID", "")
            app_build_digest = os.getenv("APP_BUILD_DIGEST", "")
            if not security_key or not security_key_id or not app_build_digest:
                raise EvaluationInputError(
                    "验证独立安全证据必须配置安全验签密钥和 APP_BUILD_DIGEST"
                )
            security_keys = {security_key_id: security_key}
        with SessionLocal() as db:
            bundle = collect_trusted_evidence(
                db,
                dataset=dataset,
                split=args.split,
                bindings=bindings,
                dataset_root=dataset_root,
                signing_key=signing_key,
                key_id=key_id,
                security_access_attestation=security_bundle,
                security_verification_keys=security_keys,
                expected_app_build_digest=app_build_digest,
            )
    except (EvaluationInputError, ValueError) as exc:
        print(f"EVAL_EVIDENCE_ERROR: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"EVIDENCE_JSON={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
