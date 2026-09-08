"""发布敏感变更检测与脱敏发布证明验签，供普通 CI 使用。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.services.generation_rule_artifacts import GENERATION_RULE_ARTIFACT_IDS


_SAFE_GIT_REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@{}^~:+-]*")
_COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_PROOF_SCHEMA_VERSION = "1.0"
_PROOF_TYPE = "real_world_release_proof"
_PROOF_ALGORITHM = "ed25519"
_MAX_PROOF_BYTES = 128 * 1024

# 这是发布契约，不根据文件内容猜测。新增生成链制品时必须同步更新映射和测试。
SENSITIVE_PATHS: Mapping[str, tuple[str, ...]] = {
    "model": (
        "backend/app/core/config.py",
        "backend/app/services/llm_service.py",
        "backend/app/services/sd_service.py",
    ),
    "prompt": (
        "backend/app/agents/",
        "backend/app/services/llm_service.py",
        "backend/app/services/plan_refine_service.py",
    ),
    "rules": tuple(f"backend/{path}" for path in GENERATION_RULE_ARTIFACT_IDS),
    "data": (
        "backend/data/",
        "backend/compile_active_catalog.py",
        "backend/import_products.py",
        "backend/app/services/catalog_service.py",
        "backend/app/services/custom_furniture_service.py",
        "backend/app/schemas/custom_furniture.py",
        "backend/migrations/versions/",
    ),
    "release": (
        "backend/evals/release_change_detection.py",
        "backend/evals/real_world_release_gate.py",
        ".github/workflows/quality.yml",
        ".github/workflows/real-world-release-gate.yml",
    ),
}


@dataclass(frozen=True)
class SensitiveChanges:
    required: bool
    status: str
    by_category: dict[str, tuple[str, ...]]


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode_key(value: str, *, field: str) -> bytes:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 缺失")
    try:
        decoded = base64.b64decode(value.strip(), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} 不是合法 base64") from exc
    if not decoded:
        raise ValueError(f"{field} 为空")
    return decoded


def _load_private_key(value: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(
            _decode_key(value, field="发布证明私钥"),
            password=None,
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("发布证明私钥不合法") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("发布证明私钥必须是 Ed25519")
    return key


def _load_public_key(value: str) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(
            _decode_key(value, field="发布证明公钥"),
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("发布证明公钥不合法") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("发布证明公钥必须是 Ed25519")
    return key


def _validated_commit_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是完整提交 SHA")
    normalized = value.strip().lower()
    if not _COMMIT_SHA_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} 必须是完整提交 SHA")
    return normalized


def build_signed_release_proof(
    report: Mapping[str, object],
    *,
    signing_key_b64: str,
    key_id: str,
) -> dict[str, object]:
    """从脱敏门禁报告派生只绑定提交的 detached proof。"""
    if report.get("status") != "passed" or report.get("overall_passed") is not True:
        raise ValueError("只有通过的真实案例门禁才能签发发布证明")
    commit_sha = _validated_commit_sha(report.get("commit_sha"), field="报告 commit_sha")
    issued_at = report.get("issued_at")
    if not isinstance(issued_at, str) or not issued_at.strip():
        raise ValueError("报告缺少 issued_at")
    if not isinstance(key_id, str) or not key_id.strip():
        raise ValueError("发布证明 key_id 缺失")
    unsigned: dict[str, object] = {
        "schema_version": _PROOF_SCHEMA_VERSION,
        "proof_type": _PROOF_TYPE,
        "gate_status": "passed",
        "commit_sha": commit_sha,
        "release_gate_report_digest": _digest_for_json(report),
        "issued_at": issued_at,
    }
    signature = _load_private_key(signing_key_b64).sign(_canonical_json(unsigned))
    return {
        **unsigned,
        "signature": {
            "algorithm": _PROOF_ALGORITHM,
            "key_id": key_id.strip(),
            "value": base64.b64encode(signature).decode("ascii"),
        },
    }


def _digest_for_json(payload: Mapping[str, object]) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(payload)).hexdigest()}"


def verify_release_proof(
    path: Path | str,
    *,
    expected_commit_sha: str,
    public_key_b64: str,
) -> dict[str, object]:
    """仅验签脱敏 proof，不加载 proof 以外的任何真实评测资源。"""
    proof_path = Path(path).resolve()
    try:
        if proof_path.stat().st_size > _MAX_PROOF_BYTES:
            raise ValueError("发布证明文件过大")
        payload = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("无法读取发布证明") from exc
    if not isinstance(payload, dict):
        raise ValueError("发布证明必须是对象")
    allowed = {
        "schema_version",
        "proof_type",
        "gate_status",
        "commit_sha",
        "release_gate_report_digest",
        "issued_at",
        "signature",
    }
    if set(payload) != allowed:
        raise ValueError("发布证明字段不合法")
    if payload["schema_version"] != _PROOF_SCHEMA_VERSION:
        raise ValueError("发布证明版本不受支持")
    if payload["proof_type"] != _PROOF_TYPE:
        raise ValueError("发布证明类型不合法")
    if payload["gate_status"] != "passed":
        raise ValueError("发布证明不是通过状态")
    commit_sha = _validated_commit_sha(payload["commit_sha"], field="proof commit_sha")
    if commit_sha != _validated_commit_sha(expected_commit_sha, field="目标 commit_sha"):
        raise ValueError("发布证明未绑定当前提交 SHA")
    report_digest = payload["release_gate_report_digest"]
    if (
        not isinstance(report_digest, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", report_digest)
    ):
        raise ValueError("发布证明报告摘要不合法")
    issued_at = payload["issued_at"]
    if not isinstance(issued_at, str):
        raise ValueError("发布证明 issued_at 不合法")
    try:
        parsed_issued_at = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("发布证明 issued_at 不合法") from exc
    if parsed_issued_at.tzinfo is None:
        raise ValueError("发布证明 issued_at 必须包含时区")
    signature = payload["signature"]
    if not isinstance(signature, dict) or set(signature) != {
        "algorithm",
        "key_id",
        "value",
    }:
        raise ValueError("发布证明签名字段不合法")
    if signature["algorithm"] != _PROOF_ALGORITHM:
        raise ValueError("发布证明签名算法不受支持")
    if not isinstance(signature["key_id"], str) or not signature["key_id"].strip():
        raise ValueError("发布证明签名 key_id 缺失")
    try:
        signature_value = base64.b64decode(signature["value"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("发布证明签名值不合法") from exc
    try:
        _load_public_key(public_key_b64).verify(
            signature_value,
            _canonical_json({key: payload[key] for key in allowed if key != "signature"}),
        )
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ValueError("发布证明签名无效") from exc
    return {
        "schema_version": payload["schema_version"],
        "proof_type": payload["proof_type"],
        "gate_status": payload["gate_status"],
        "commit_sha": commit_sha,
        "release_gate_report_digest": report_digest,
        "issued_at": issued_at,
        "signature_key_id": signature["key_id"],
    }


def _normalize_repo_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or normalized.startswith("./")
    ):
        raise ValueError("变更路径必须是规范的仓库相对路径")
    return path.as_posix()


def classify_release_sensitive_paths(paths: Iterable[str]) -> SensitiveChanges:
    normalized_paths = sorted({_normalize_repo_path(path) for path in paths})
    by_category: dict[str, tuple[str, ...]] = {}
    for category, policies in SENSITIVE_PATHS.items():
        matches = tuple(
            path
            for path in normalized_paths
            if any(
                path == policy or (policy.endswith("/") and path.startswith(policy))
                for policy in policies
            )
        )
        by_category[category] = matches
    required = any(by_category.values())
    return SensitiveChanges(
        required=required,
        status="proof_required" if required else "not_required",
        by_category=by_category,
    )


def _validate_ref(value: str, field: str) -> str:
    if value.startswith("-") or not _SAFE_GIT_REF_PATTERN.fullmatch(value):
        raise ValueError(f"{field} 不是安全的 git ref")
    return value


def changed_paths_between(repo_root: Path, *, base_ref: str, head_ref: str) -> list[str]:
    base = _validate_ref(base_ref, "base_ref")
    head = _validate_ref(head_ref, "head_ref")
    if re.fullmatch(r"0{40,64}", base):
        command = [
            "git",
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            head,
        ]
    else:
        command = ["git", "diff", "--name-only", base, head, "--"]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检测是否必须运行真实案例发布回归")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--proof-file", type=Path)
    parser.add_argument(
        "--detect-only",
        action="store_true",
        help="只分类变更，不读取或验证发布证明",
    )
    parser.add_argument(
        "--proof-public-key-env",
        default="REAL_WORLD_RELEASE_PROOF_PUBLIC_KEY_B64",
    )
    args = parser.parse_args(argv)
    try:
        paths = changed_paths_between(
            args.repo_root.resolve(),
            base_ref=args.base_ref,
            head_ref=args.head_ref,
        )
        changes = classify_release_sensitive_paths(paths)
        proof = None
        if changes.required and not args.detect_only:
            if args.proof_file is None:
                raise ValueError("敏感变更必须提供受保护环境签发的发布证明")
            proof = verify_release_proof(
                args.proof_file,
                expected_commit_sha=args.head_ref,
                public_key_b64=os.environ.get(args.proof_public_key_env, ""),
            )
    except (OSError, subprocess.CalledProcessError, ValueError):
        print("REAL_WORLD_CHANGE_DETECTION_ERROR=proof_missing_or_invalid")
        return 2
    payload = {
        "schema_version": "1.0",
        "claim": (
            "proof_required"
            if changes.required and args.detect_only
            else "proof_verified"
            if changes.required
            else "not_required"
        ),
        "change_detection": {
            "required": changes.required,
            "status": changes.status,
            "category_counts": {
                category: len(items)
                for category, items in changes.by_category.items()
            },
        },
        "proof": {
            "required": changes.required,
            "verified": proof is not None,
            "commit_sha": proof["commit_sha"] if proof else None,
            "signature_key_id": proof["signature_key_id"] if proof else None,
        },
    }
    try:
        if args.output:
            output = args.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except OSError:
        print("REAL_WORLD_CHANGE_DETECTION_ERROR=proof_missing_or_invalid")
        return 2
    print(f"REAL_WORLD_REGRESSION_REQUIRED={str(changes.required).lower()}")
    print(
        "敏感变更已校验受保护环境发布证明"
        if changes.required
        else "当前变更不触发真实案例发布证明"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
