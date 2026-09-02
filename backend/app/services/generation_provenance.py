"""生成任务实际使用的 Prompt、规则和数据制品摘要。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


_RULE_ARTIFACTS = (
    Path(__file__).resolve().parents[1] / "agents" / "design_workflow.py",
    Path(__file__).resolve().parent / "catalog_service.py",
)
GENERATION_PROVENANCE_SCHEMA_VERSION = 2


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _source_artifact_digests() -> list[str]:
    digests: list[str] = []
    for path in _RULE_ARTIFACTS:
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"无法读取生成规则制品：{path.name}") from exc
        digests.append(f"sha256:{hashlib.sha256(content).hexdigest()}")
    return digests


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
        "rules_digest": canonical_digest(
            {
                "schema_version": GENERATION_PROVENANCE_SCHEMA_VERSION,
                "source_artifacts": _source_artifact_digests(),
            }
        ),
        "data_digest": canonical_digest(
            {
                "schema_version": GENERATION_PROVENANCE_SCHEMA_VERSION,
                "catalog_context": catalog_context,
            }
        ),
    }
