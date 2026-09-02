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

from app.db.models import (
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    GenerationRun,
    GenerationRunSceneEvidence,
)
from app.schemas.scenes import SceneDocument


OUTPUT_SCHEMA_VERSION = 2
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
            ),
            selectinload(DesignRevision.plans)
            .selectinload(DesignPlanVersion.scene)
            .selectinload(DesignScene.versions),
        )
        .where(DesignRevision.id == revision_id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if revision is None:
        raise GenerationOutputValidationError("生成输出 revision 不存在")
    if revision.status != "completed" or not revision.plans:
        raise GenerationOutputValidationError("生成输出 revision 未完成或没有方案")
    return revision


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _normalized_scene(
    scene_version: DesignSceneVersion,
    *,
    plan_key: str,
) -> tuple[dict[str, Any], str]:
    try:
        document = SceneDocument.model_validate(scene_version.scene_json)
    except ValueError as exc:
        raise GenerationOutputValidationError(
            f"方案 {plan_key} 的冻结场景不符合 SceneDocument 契约"
        ) from exc
    normalized = _normalized_json(
        document.model_dump(by_alias=True, mode="json"),
        path=f"plans.{plan_key}.scene",
    )
    return normalized, _canonical_digest(normalized)


def _current_scene_records(
    revision: DesignRevision,
) -> dict[int, tuple[DesignScene, DesignSceneVersion, dict[str, Any], str]]:
    records: dict[
        int,
        tuple[DesignScene, DesignSceneVersion, dict[str, Any], str],
    ] = {}
    for plan in revision.plans:
        scene = plan.scene
        if scene is None:
            raise GenerationOutputValidationError(
                f"方案 {plan.plan_key} 缺少冻结场景"
            )
        matches = [
            version
            for version in scene.versions
            if version.version == scene.current_version
        ]
        if len(matches) != 1:
            raise GenerationOutputValidationError(
                f"方案 {plan.plan_key} 的场景当前版本引用不一致"
            )
        version = matches[0]
        document, digest = _normalized_scene(version, plan_key=plan.plan_key)
        records[plan.id] = (scene, version, document, digest)
    return records


def _bound_scene_records(
    db: Session,
    *,
    run: GenerationRun,
    revision: DesignRevision,
) -> dict[int, tuple[DesignScene, DesignSceneVersion, dict[str, Any], str]]:
    evidence_rows = db.scalars(
        select(GenerationRunSceneEvidence)
        .where(GenerationRunSceneEvidence.generation_run_id == run.id)
        .order_by(GenerationRunSceneEvidence.plan_version_id)
    ).all()
    plans = {plan.id: plan for plan in revision.plans}
    if len(evidence_rows) != len(plans):
        raise GenerationOutputValidationError("生成运行的逐方案场景证据不完整")
    records: dict[
        int,
        tuple[DesignScene, DesignSceneVersion, dict[str, Any], str],
    ] = {}
    for evidence in evidence_rows:
        plan = plans.get(evidence.plan_version_id)
        if plan is None or evidence.plan_version_id in records:
            raise GenerationOutputValidationError("生成运行的场景证据方案引用不一致")
        scene = db.get(DesignScene, evidence.scene_id)
        version = db.get(DesignSceneVersion, evidence.scene_version_id)
        if (
            scene is None
            or version is None
            or scene.plan_version_id != plan.id
            or version.scene_id != scene.id
            or version.version != evidence.scene_version
        ):
            raise GenerationOutputValidationError(
                f"方案 {plan.plan_key} 的冻结场景版本引用不一致"
            )
        document, digest = _normalized_scene(version, plan_key=plan.plan_key)
        if not hmac.compare_digest(evidence.scene_digest, digest):
            raise GenerationOutputValidationError(
                f"方案 {plan.plan_key} 的冻结场景摘要不一致"
            )
        records[plan.id] = (scene, version, document, digest)
    return records


def _revision_output_payload(
    revision: DesignRevision,
    *,
    scene_records: dict[
        int,
        tuple[DesignScene, DesignSceneVersion, dict[str, Any], str],
    ],
) -> dict[str, Any]:
    plans: list[dict[str, Any]] = []
    for plan in revision.plans:
        quote = plan.quote_snapshot
        if quote is None:
            raise GenerationOutputValidationError(
                f"方案 {plan.plan_key} 缺少不可变报价快照"
            )
        scene_record = scene_records.get(plan.id)
        if scene_record is None:
            raise GenerationOutputValidationError(
                f"方案 {plan.plan_key} 缺少冻结场景证据"
            )
        _, scene_version, scene_document, scene_digest = scene_record
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
                "scene": {
                    "version": scene_version.version,
                    "content_digest": scene_digest,
                    "document": scene_document,
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


def revision_output_payload(
    db: Session,
    *,
    revision_id: int,
) -> dict[str, Any]:
    """读取仅由不可变版本表组成的规范化业务输出。"""
    revision = _load_revision(db, revision_id)
    return _revision_output_payload(
        revision,
        scene_records=_current_scene_records(revision),
    )


def revision_output_digest(db: Session, *, revision_id: int) -> str:
    payload = revision_output_payload(db, revision_id=revision_id)
    return _canonical_digest(payload)


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
    existing_evidence = db.scalar(
        select(GenerationRunSceneEvidence.id).where(
            GenerationRunSceneEvidence.generation_run_id == run.id
        )
    )
    if existing_evidence is not None:
        raise GenerationOutputValidationError("生成运行已经绑定场景证据")
    scene_records = _current_scene_records(revision)
    payload = _revision_output_payload(revision, scene_records=scene_records)
    digest = _canonical_digest(payload)
    for plan in revision.plans:
        scene, version, _, scene_digest = scene_records[plan.id]
        db.add(
            GenerationRunSceneEvidence(
                generation_run_id=run.id,
                plan_version_id=plan.id,
                scene_id=scene.id,
                scene_version_id=version.id,
                scene_version=version.version,
                scene_digest=scene_digest,
            )
        )
    db.flush()
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
    payload = _revision_output_payload(
        revision,
        scene_records=_bound_scene_records(db, run=run, revision=revision),
    )
    actual_digest = _canonical_digest(payload)
    if not hmac.compare_digest(run.output_digest, actual_digest):
        raise GenerationOutputValidationError("生成运行的输出摘要不一致")
    return payload
