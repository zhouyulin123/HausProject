"""生成任务实际使用的 Prompt、规则和数据制品摘要。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.generation_rule_artifacts import GENERATION_RULE_ARTIFACT_IDS


_APP_ROOT = Path(__file__).resolve().parents[1]
_RULE_ARTIFACTS: tuple[tuple[str, Path], ...] = tuple(
    (artifact_id, _APP_ROOT / Path(artifact_id).relative_to("app"))
    for artifact_id in GENERATION_RULE_ARTIFACT_IDS
)
GENERATION_PROVENANCE_SCHEMA_VERSION = 4


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def generation_rule_artifact_snapshot() -> list[dict[str, str]]:
    """返回与本机绝对路径无关的生成规则制品清单。"""
    snapshot: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for artifact_id, path in _RULE_ARTIFACTS:
        if (
            not artifact_id
            or artifact_id in seen_ids
            or "\\" in artifact_id
            or artifact_id.startswith("/")
            or ".." in Path(artifact_id).parts
        ):
            raise ValueError("生成规则制品标识不合法或重复")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"无法读取生成规则制品：{artifact_id}") from exc
        seen_ids.add(artifact_id)
        snapshot.append(
            {
                "artifact_id": artifact_id,
                "content_digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
            }
        )
    return snapshot


def current_generation_rules_digest() -> str:
    """复算当前检出代码的生成与布局规则版本。"""
    return canonical_digest(
        {
            "schema_version": GENERATION_PROVENANCE_SCHEMA_VERSION,
            "artifacts": generation_rule_artifact_snapshot(),
        }
    )


def build_generation_provenance(
    *,
    prompt_snapshot: str,
    input_snapshot: dict[str, Any],
    catalog_context: str,
) -> dict[str, str]:
    """在执行前从静态制品和完整模型上下文构造不可变版本摘要。"""
    if not isinstance(prompt_snapshot, str) or not prompt_snapshot:
        raise ValueError("Prompt 快照不能为空")
    if not isinstance(input_snapshot, dict) or not input_snapshot:
        raise ValueError("模型动态输入快照不能为空")
    if not isinstance(catalog_context, str):
        raise ValueError("商品目录上下文不合法")
    return {
        "prompt_digest": canonical_digest(prompt_snapshot),
        "input_digest": canonical_digest(input_snapshot),
        "rules_digest": current_generation_rules_digest(),
        "data_digest": canonical_digest(
            {
                "schema_version": GENERATION_PROVENANCE_SCHEMA_VERSION,
                "catalog_context": catalog_context,
            }
        ),
    }
