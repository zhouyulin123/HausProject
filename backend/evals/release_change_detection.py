"""仅依赖标准库的发布敏感变更检测，供普通 CI 使用。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

from app.services.generation_rule_artifacts import GENERATION_RULE_ARTIFACT_IDS


_SAFE_GIT_REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@{}^~:+-]*")

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
}


@dataclass(frozen=True)
class SensitiveChanges:
    required: bool
    status: str
    by_category: dict[str, tuple[str, ...]]


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
    args = parser.parse_args(argv)
    try:
        paths = changed_paths_between(
            args.repo_root.resolve(),
            base_ref=args.base_ref,
            head_ref=args.head_ref,
        )
        changes = classify_release_sensitive_paths(paths)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"REAL_WORLD_CHANGE_DETECTION_ERROR: {exc}")
        return 2
    payload = {
        "schema_version": "1.0",
        "claim": "proof_required" if changes.required else "not_required",
        "change_detection": {
            "required": changes.required,
            "status": changes.status,
            "category_counts": {
                category: len(items)
                for category, items in changes.by_category.items()
            },
        },
    }
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"REAL_WORLD_REGRESSION_REQUIRED={str(changes.required).lower()}")
    print("普通 CI 未执行私有真实案例，因此不产生发布通过结论")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
