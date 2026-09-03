"""在受控部署上运行独立跨用户 HTTP 安全回归并签发证据。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from evals.real_world import (
    EvaluationInputError,
    EvaluationSplit,
    EvaluationVersions,
    load_case_manifest,
)
from evals.security_access_attestation import (
    AccessTarget,
    UrllibHttpTransport,
    collect_security_access_attestation,
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationInputError("无法读取安全回归目标文件") from exc
    if not isinstance(value, dict):
        raise EvaluationInputError("安全回归目标根节点必须是对象")
    return value


def _read_targets(
    path: Path,
    *,
    split: EvaluationSplit,
) -> tuple[tuple[AccessTarget, ...], EvaluationVersions]:
    payload = _read_json(path)
    if set(payload) != {"schema_version", "split", "versions", "targets"}:
        raise EvaluationInputError("安全回归目标文件字段不合法")
    if payload.get("schema_version") != "1.0" or payload.get("split") != split:
        raise EvaluationInputError("安全回归目标 schema 或 split 不一致")
    raw_versions = payload.get("versions")
    if not isinstance(raw_versions, dict) or set(raw_versions) != {
        "model",
        "prompt",
        "rules",
        "data",
    }:
        raise EvaluationInputError("安全回归目标 versions 不合法")
    try:
        versions = EvaluationVersions(**raw_versions)
    except (TypeError, ValueError) as exc:
        raise EvaluationInputError("安全回归目标 versions 不合法") from exc
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, list):
        raise EvaluationInputError("安全回归 targets 必须是数组")
    targets: list[AccessTarget] = []
    expected_fields = {
        "case_id",
        "task_id",
        "foreign_control_task_id",
        "owner_session_env",
        "foreign_session_env",
    }
    for index, raw in enumerate(raw_targets, start=1):
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise EvaluationInputError(f"第 {index} 条安全回归目标字段不合法")
        try:
            targets.append(AccessTarget(**raw))
        except TypeError as exc:
            raise EvaluationInputError(
                f"第 {index} 条安全回归目标不合法"
            ) from exc
    return tuple(targets), versions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行独立跨用户 HTTP 安全回归")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--split",
        choices=("development", "regression", "blind"),
        required=True,
    )
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--app-build-digest", required=True)
    parser.add_argument("--ttl-seconds", type=int, default=900)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        signing_key = os.getenv("SECURITY_EVIDENCE_HMAC_KEY", "")
        key_id = os.getenv("SECURITY_EVIDENCE_KEY_ID", "")
        if not signing_key or not key_id:
            raise EvaluationInputError(
                "缺少独立安全证据签名密钥或 key_id"
            )
        dataset = load_case_manifest(args.manifest, asset_root=args.asset_root)
        targets, versions = _read_targets(args.targets, split=args.split)
        credential_names = {
            name
            for target in targets
            for name in (target.owner_session_env, target.foreign_session_env)
        }
        credentials = {name: os.getenv(name, "") for name in credential_names}
        bundle = collect_security_access_attestation(
            dataset=dataset,
            split=args.split,
            targets=targets,
            versions=versions,
            base_url=args.base_url,
            app_build_digest=args.app_build_digest,
            credentials=credentials,
            transport=UrllibHttpTransport(timeout_seconds=args.timeout_seconds),
            signing_key=signing_key,
            key_id=key_id,
            ttl_seconds=args.ttl_seconds,
        )
    except (EvaluationInputError, ValueError) as exc:
        print(f"SECURITY_EVIDENCE_ERROR: {exc}")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"SECURITY_EVIDENCE_JSON={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
