"""GenerationRun 与不可变方案版本之间的可信输出绑定。"""

from __future__ import annotations

from hashlib import sha256
import hmac
import json
import math
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import DesignPlanVersion, DesignRevision, GenerationRun


OUTPUT_SCHEMA_VERSION = 1
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNORDERED_LIST_FIELDS = {
    "customLineItems",
    "furnitureSuggestions",
    "layoutConstraintResults",
    "lineItems",
}


class GenerationOutputValidationError(RuntimeError):
    """生成输出缺失、归属错误或不满足不可变版本契约。"""


def _normalized_json(
    value: Any,
    *,
    path: str,
    sort_list: bool = False,
) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GenerationOutputValidationError(f"{path} 包含非有限数值")
        return value
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise GenerationOutputValidationError(f"{path} 包含非字符串键")
        return {
            key: _normalized_json(
                value[key],
                path=f"{path}.{key}",
                sort_list=key in _UNORDERED_LIST_FIELDS,
            )
            for key in sorted(value)
        }
    if isinstance(value, (list, tuple)):
        normalized = [
            _normalized_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
        if sort_list:
            normalized.sort(
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
        return normalized
    raise GenerationOutputValidationError(f"{path} 包含不可序列化类型")


def _load_revision(db: Session, revision_id: int) -> DesignRevision:
    revision = db.scalars(
        select(DesignRevision)
        .options(
            selectinload(DesignRevision.plans).selectinload(
                DesignPlanVersion.quote_snapshot
            )
        )
        .where(DesignRevision.id == revision_id)
    ).one_or_none()
    if revision is None:
        raise GenerationOutputValidationError("生成输出 revision 不存在")
    if revision.status != "completed" or not revision.plans:
        raise GenerationOutputValidationError("生成输出 revision 未完成或没有方案")
    return revision


def revision_output_payload(
    db: Session,
    *,
    revision_id: int,
) -> dict[str, Any]:
    """读取仅由不可变版本表组成的规范化业务输出。"""
    revision = _load_revision(db, revision_id)
    plans: list[dict[str, Any]] = []
    # 关系按持久化 ID 排序；该顺序就是用户看到的推荐顺序，属于输出语义。
    for plan in revision.plans:
        quote = plan.quote_snapshot
        if quote is None:
            raise GenerationOutputValidationError(
                f"方案 {plan.plan_key} 缺少不可变报价快照"
            )
        plans.append(
            {
                "plan_key": plan.plan_key,
                "plan_name": plan.plan_name,
                "style": plan.style,
                "plan": _normalized_json(
                    plan.plan_json,
                    path=f"plans.{plan.plan_key}.plan",
                ),
                "quote": {
                    "currency": quote.currency,
                    "furniture_total": quote.furniture_total,
                    "custom_total": quote.custom_total,
                    "grand_total": quote.grand_total,
                    "quote": _normalized_json(
                        quote.quote_json,
                        path=f"plans.{plan.plan_key}.quote",
                    ),
                    "catalog_version": quote.catalog_version,
                    "price_version": quote.price_version,
                    "rule_version": quote.rule_version,
                    "sku_versions": _normalized_json(
                        quote.sku_versions_json,
                        path=f"plans.{plan.plan_key}.sku_versions",
                        sort_list=True,
                    ),
                },
            }
        )
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "revision": {
            "requirement": _normalized_json(
                revision.requirement_snapshot,
                path="revision.requirement",
            ),
            "image_context": _normalized_json(
                revision.image_context_snapshot,
                path="revision.image_context",
            ),
            "workflow_trace": _normalized_json(
                revision.workflow_trace_snapshot,
                path="revision.workflow_trace",
            ),
            "generator": revision.generator,
            "status": revision.status,
        },
        "plans": plans,
    }


def revision_output_digest(db: Session, *, revision_id: int) -> str:
    payload = revision_output_payload(db, revision_id=revision_id)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def bind_run_output(
    db: Session,
    *,
    run: GenerationRun,
    revision_id: int,
    generator: str,
) -> str:
    revision = _load_revision(db, revision_id)
    if revision.task_id != run.task_id:
        raise GenerationOutputValidationError("生成输出 revision 不属于运行任务")
    if revision.generator != generator:
        raise GenerationOutputValidationError("生成输出来源与运行来源不一致")
    other_run_id = db.scalar(
        select(GenerationRun.id).where(
            GenerationRun.result_revision_id == revision_id,
            GenerationRun.id != run.id,
        )
    )
    if other_run_id is not None:
        raise GenerationOutputValidationError("生成输出 revision 已绑定其他运行")
    digest = revision_output_digest(db, revision_id=revision_id)
    run.result_revision_id = revision_id
    run.output_digest = digest
    return digest


def validated_run_output(
    db: Session,
    *,
    run: GenerationRun,
) -> dict[str, Any]:
    if run.result_revision_id is None or not isinstance(run.output_digest, str):
        raise GenerationOutputValidationError("成功运行缺少不可变输出绑定")
    if not _DIGEST_PATTERN.fullmatch(run.output_digest):
        raise GenerationOutputValidationError("成功运行的输出摘要格式不合法")
    revision = _load_revision(db, run.result_revision_id)
    if revision.task_id != run.task_id:
        raise GenerationOutputValidationError("生成输出 revision 不属于运行任务")
    if revision.generator != run.generator:
        raise GenerationOutputValidationError("生成输出来源与运行来源不一致")
    payload = revision_output_payload(db, revision_id=revision.id)
    actual_digest = revision_output_digest(db, revision_id=revision.id)
    if not hmac.compare_digest(run.output_digest, actual_digest):
        raise GenerationOutputValidationError("生成运行的输出摘要不一致")
    return payload
