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


def _quote_versions(plans: list[dict[str, Any]], field_name: str) -> list[str]:
    values: set[str] = set()
    for plan in plans:
        quote = plan.get("shopQuote") if isinstance(plan, dict) else None
        value = quote.get(field_name) if isinstance(quote, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"方案缺少服务端确定性报价版本 {field_name}")
        values.add(value.strip())
    if not plans:
        raise ValueError("没有可生成版本摘要的方案")
    if len(values) != 1:
        raise ValueError(f"同一运行的 {field_name} 必须使用同一版本")
    return sorted(values)


def build_generation_provenance(
    *,
    prompt_snapshot: str,
    catalog_context: str,
    plans: list[dict[str, Any]],
) -> dict[str, str]:
    """从本次实际执行输入和确定性报价产物构造不可变版本摘要。"""
    if not isinstance(prompt_snapshot, str) or not prompt_snapshot:
        raise ValueError("Prompt 快照不能为空")
    if not isinstance(catalog_context, str):
        raise ValueError("商品目录上下文不合法")
    rule_versions = _quote_versions(plans, "ruleVersion")
    catalog_versions = _quote_versions(plans, "catalogVersion")
    return {
        "prompt_digest": canonical_digest(prompt_snapshot),
        "rules_digest": canonical_digest(
            {
                "source_artifacts": _source_artifact_digests(),
                "quote_rule_versions": rule_versions,
            }
        ),
        "data_digest": canonical_digest(
            {
                "catalog_context_digest": canonical_digest(catalog_context),
                "catalog_versions": catalog_versions,
            }
        ),
    }
