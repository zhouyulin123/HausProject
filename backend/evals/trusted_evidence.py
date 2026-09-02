"""真实系统执行证据的签发与验证。

签名密钥是信任边界，只应存在于受控 Worker/CI 环境。离线报告只保存摘要，
不保存案例别名、资产路径、Prompt、输入或模型输出原文。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DesignTask, EvaluationRunBinding, GenerationRun
from app.services import (
    catalog_service,
    evaluation_binding_service,
    generation_output_service,
    generation_run_service,
    llm_service,
    prediction_evidence_service,
)
from app.services.evaluation_binding_service import EvaluationBindingSpec
from app.services.generation_provenance import (
    GENERATION_PROVENANCE_SCHEMA_VERSION,
    build_generation_provenance,
    canonical_digest,
)
from evals.annotations import (
    AnnotationValidationError,
    ExecutionReview,
    load_execution_review,
)
from evals.layout_constraints import evaluate_layout_constraint
from app.schemas.scenes import SceneDocument
from evals.real_world import (
    CaseResult,
    EvaluationInputError,
    EvaluationSplit,
    EvaluationVersions,
    RealWorldCase,
    RealWorldDataset,
    validate_evaluation_split,
)


EVIDENCE_SCHEMA_VERSION = "5.0"
EVIDENCE_TYPE = "system_execution"
ATTESTATION_ALGORITHM = "HMAC-SHA256"
TRUSTED_GENERATOR = "llm"
REQUIRED_RUN_NODES = frozenset(
    {"prepare_context", "generate_plans", "calculate_quote", "validate_quality"}
)
REQUIRED_NODE_SOURCES = {
    "generate_plans": "llm",
    "calculate_quote": "deterministic",
    "validate_quality": "deterministic",
}
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_EXECUTION_REF_PATTERN = re.compile(r"^exec-hmac-sha256:[0-9a-f]{64}$")
TRUSTED_TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "failed",
        "dead_letter",
        "cost_limit_exceeded",
        "provider_unavailable",
        "cancelled",
    }
)
TRUSTED_TASK_STATUS_BY_RUN = {
    "completed": "completed",
    "failed": "failed",
    "dead_letter": "failed",
    "cost_limit_exceeded": "needs_human",
    "provider_unavailable": "needs_human",
    "cancelled": "cancelled",
}


@dataclass(frozen=True)
class RunBinding:
    case_id: str
    task_id: int
    system_run_id: int
    execution_review_path: Path | str | None = None
    execution_review_sha256: str | None = None


@dataclass(frozen=True)
class ExecutionProvenance:
    case_fingerprint: str
    execution_ref: str
    source: str
    generator: str
    status: str
    model: str
    prompt_digest: str
    rules_digest: str
    data_digest: str
    input_digest: str
    prediction_digest: str
    output_digest: str | None
    result_digest: str


@dataclass(frozen=True)
class VerifiedEvaluationEvidence:
    schema_version: str
    versions: EvaluationVersions
    dataset_fingerprint: str
    evidence_digest: str
    split: EvaluationSplit
    results: tuple[CaseResult, ...]
    executions: tuple[ExecutionProvenance, ...]
    key_id: str
    signature_verified: bool = True


def _canonical_json(value: Any) -> bytes:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EvaluationInputError(f"证据包含不可摘要的值：{exc}") from exc
    return serialized.encode("utf-8")


def _digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(value)).hexdigest()}"


def _file_digest(case: RealWorldCase) -> str:
    digest = hashlib.sha256()
    try:
        with case.asset_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise EvaluationInputError(f"案例资产无法读取：{case.id}") from exc
    return f"sha256:{digest.hexdigest()}"


def dataset_fingerprint(
    dataset: RealWorldDataset,
    *,
    split: EvaluationSplit,
) -> str:
    """绑定准入治理元数据和资产字节，不把路径或名称写入证据。"""
    if dataset.schema_version != "2.0":
        raise EvaluationInputError("可信评测只接受带冻结标注资产的 manifest 2.0")
    normalized_split = validate_evaluation_split(split)
    eligible = dataset.eligible_cases(normalized_split)
    if not eligible:
        raise EvaluationInputError(f"split={normalized_split} 没有可评测案例")
    for case in eligible:
        if (
            case.annotation is None
            or not case.annotation_sha256
            or case.annotation.file_sha256 != case.annotation_sha256
        ):
            raise EvaluationInputError(f"案例 {case.id} 缺少冻结且已验证的结构化标注")
    cases = [
        {
            "id": case.id,
            "split": case.split,
            "origin": case.origin,
            "consent_status": case.consent_status,
            "annotation_status": case.annotation_status,
            "label_version": case.label_version,
            "annotation_sha256": case.annotation_sha256,
            "annotation_fingerprint": case.annotation.content_fingerprint,
            "allowed_purposes": sorted(case.allowed_purposes),
            "failure_tags": sorted(case.failure_tags),
            "asset_digest": _file_digest(case),
            "task_input_digest": (
                evaluation_binding_service.expected_task_input_digest(
                    case.task_input
                )
                if case.task_input is not None
                else None
            ),
        }
        for case in sorted(eligible, key=lambda item: item.id)
    ]
    return _digest(
        {
            "schema_version": dataset.schema_version,
            "dataset_version": dataset.dataset_version,
            "split": normalized_split,
            "cases": cases,
        }
    )


def _case_fingerprint(dataset_digest: str, case_id: str) -> str:
    return _digest({"dataset_fingerprint": dataset_digest, "case_id": case_id})


def _evaluation_binding_spec(
    db: Session,
    *,
    dataset: RealWorldDataset,
    split: EvaluationSplit,
    case_id: str,
    task: DesignTask,
) -> EvaluationBindingSpec:
    normalized_split = validate_evaluation_split(split)
    eligible = {
        case.id: case for case in dataset.eligible_cases(normalized_split)
    }
    case = eligible.get(case_id)
    if case is None:
        raise EvaluationInputError("只能绑定指定 split 的已准入真实评测案例")
    if case.task_input is None:
        raise EvaluationInputError("评测案例缺少规范化 task_input")
    dataset_digest = dataset_fingerprint(dataset, split=normalized_split)
    case_digest = _case_fingerprint(dataset_digest, case.id)
    task_payload = evaluation_binding_service.task_input_payload(db, task)
    expected_task_digest = evaluation_binding_service.expected_task_input_digest(
        case.task_input
    )
    if canonical_digest(task_payload) != expected_task_digest:
        raise EvaluationInputError("当前任务输入与评测案例不一致")
    case_asset_digest = _file_digest(case)
    asset_digests = evaluation_binding_service.task_asset_digests(
        db,
        task_id=task.id,
    )
    if len(asset_digests) != 1 or asset_digests[0] != case_asset_digest:
        raise EvaluationInputError("当前任务绑定的案例资产不唯一或不一致")
    requirement = task_payload.get("confirmed_requirement")
    if not isinstance(requirement, dict) or not requirement:
        raise EvaluationInputError("正式评测必须在绑定前冻结 confirmed_requirement")
    requirement_for_llm = dict(requirement)
    image_context = task_payload.get("image_context") or []
    if image_context:
        requirement_for_llm["image_analysis"] = list(image_context)
    catalog_context = catalog_service.build_catalog_context(db)
    prompt_snapshot = llm_service.generation_prompt_snapshot()
    input_snapshot = llm_service.generation_input_snapshot(
        requirement_for_llm,
        catalog_context,
    )
    provenance = build_generation_provenance(
        prompt_snapshot=prompt_snapshot,
        input_snapshot=input_snapshot,
        catalog_context=catalog_context,
    )
    try:
        prediction_snapshot, parse_result_id, uploaded_image_id = (
            prediction_evidence_service.build_prediction_snapshot(db, task=task)
        )
    except prediction_evidence_service.PredictionEvidenceError as exc:
        raise EvaluationInputError(str(exc)) from exc
    return EvaluationBindingSpec(
        case_fingerprint=case_digest,
        asset_digest=case_asset_digest,
        task_input_digest=expected_task_digest,
        dataset_split=normalized_split,
        model=settings.llm_model,
        prompt_snapshot=prompt_snapshot,
        prompt_digest=provenance["prompt_digest"],
        rules_digest=provenance["rules_digest"],
        data_digest=provenance["data_digest"],
        input_snapshot=input_snapshot,
        input_digest=provenance["input_digest"],
        provenance_schema_version=GENERATION_PROVENANCE_SCHEMA_VERSION,
        requirement_parse_result_id=parse_result_id,
        uploaded_image_id=uploaded_image_id,
        prediction_snapshot=prediction_snapshot,
        prediction_digest=canonical_digest(prediction_snapshot),
    )


def evaluation_run_idempotency_key(
    db: Session,
    *,
    dataset: RealWorldDataset,
    split: EvaluationSplit,
    case_id: str,
    task: DesignTask,
) -> str:
    """复算案例、split 和执行前版本共同绑定的幂等键。"""
    spec = _evaluation_binding_spec(
        db,
        dataset=dataset,
        split=split,
        case_id=case_id,
        task=task,
    )
    return evaluation_binding_service.evaluation_idempotency_key(spec)


def bind_evaluation_run(
    db: Session,
    *,
    dataset: RealWorldDataset,
    split: EvaluationSplit,
    case_id: str,
    task: DesignTask,
    max_attempts: int = 3,
    request_id: str | None = None,
) -> GenerationRun:
    """在正式 Worker 可领取前，原子创建运行和冻结案例输入绑定。"""
    spec = _evaluation_binding_spec(
        db,
        dataset=dataset,
        split=split,
        case_id=case_id,
        task=task,
    )
    try:
        return generation_run_service.create_run(
            db,
            task=task,
            idempotency_key=evaluation_binding_service.evaluation_idempotency_key(
                spec
            ),
            max_attempts=max_attempts,
            request_id=request_id,
            request_digest=evaluation_binding_service.evaluation_execution_digest(
                spec
            ),
            evaluation_binding=spec,
        )
    except evaluation_binding_service.EvaluationBindingError as exc:
        raise EvaluationInputError(str(exc)) from exc


def _normalized_key(signing_key: str) -> bytes:
    if not isinstance(signing_key, str) or len(signing_key.encode("utf-8")) < 32:
        raise EvaluationInputError("评测证据签名密钥缺失或少于 32 字节")
    return signing_key.encode("utf-8")


def _signature(payload: Mapping[str, Any], signing_key: str) -> str:
    return hmac.new(
        _normalized_key(signing_key),
        _canonical_json(payload),
        hashlib.sha256,
    ).hexdigest()


def _execution_ref(*, task_id: int, run_id: int, deployment_key: str) -> str:
    """生成不暴露可枚举数据库主键的部署域稳定执行引用。"""
    message = f"trusted-evidence/execution-ref/v1\0{task_id}\0{run_id}".encode(
        "ascii"
    )
    digest = hmac.new(
        _normalized_key(deployment_key),
        message,
        hashlib.sha256,
    ).hexdigest()
    return f"exec-hmac-sha256:{digest}"


def _validate_versions(versions: EvaluationVersions) -> None:
    for field_name in ("prompt", "rules", "data"):
        value = getattr(versions, field_name)
        if not _SHA256_PATTERN.fullmatch(value):
            raise EvaluationInputError(f"{field_name} 版本必须是实际制品 SHA-256 摘要")


def _validate_binding_sets(
    *,
    bindings: tuple[RunBinding, ...],
    dataset: RealWorldDataset,
    split: EvaluationSplit,
) -> dict[str, RealWorldCase]:
    run_ids = [binding.system_run_id for binding in bindings]
    if len(run_ids) != len(set(run_ids)):
        raise EvaluationInputError("同一 system_run_id 不能重复绑定或跨案例重放")
    case_ids = [binding.case_id for binding in bindings]
    if len(case_ids) != len(set(case_ids)):
        raise EvaluationInputError("同一案例包含重复绑定")
    eligible = {case.id: case for case in dataset.eligible_cases(split)}
    if not eligible:
        raise EvaluationInputError(f"split={split} 没有可评测案例")
    provided = set(case_ids)
    missing = sorted(set(eligible) - provided)
    unknown = sorted(provided - set(eligible))
    problems: list[str] = []
    if missing:
        problems.append(f"缺少案例运行：{', '.join(missing)}")
    if unknown:
        problems.append(f"未知或未准入案例：{', '.join(unknown)}")
    if problems:
        raise EvaluationInputError("；".join(problems))
    return eligible


def _validate_system_run(
    db: Session,
    *,
    binding: RunBinding,
    expected_case_fingerprint: str,
    expected_split: EvaluationSplit,
) -> tuple[GenerationRun, dict[str, Any] | None, EvaluationRunBinding]:
    run = db.get(GenerationRun, binding.system_run_id)
    if run is None:
        raise EvaluationInputError(f"系统运行不存在：{binding.system_run_id}")
    if run.task_id != binding.task_id:
        raise EvaluationInputError(
            f"系统运行 {run.id} 不属于任务 {binding.task_id}"
        )
    try:
        persisted_binding = evaluation_binding_service.validate_persisted_binding(
            db,
            run=run,
        )
    except evaluation_binding_service.EvaluationBindingError as exc:
        raise EvaluationInputError(str(exc)) from exc
    expected_case = expected_case_fingerprint
    if persisted_binding.case_fingerprint != expected_case:
        raise EvaluationInputError(
            f"系统运行 {run.id} 的持久化评测绑定不属于当前案例"
        )
    if persisted_binding.dataset_split != expected_split:
        raise EvaluationInputError(
            f"系统运行 {run.id} 的持久化评测绑定属于其他 split"
        )
    task = db.get(DesignTask, binding.task_id)
    if task is None:
        raise EvaluationInputError(f"设计任务不存在：{binding.task_id}")
    if run.status not in TRUSTED_TERMINAL_STATUSES:
        raise EvaluationInputError(f"系统运行 {run.id} 不是可信终态")
    expected_task_status = TRUSTED_TASK_STATUS_BY_RUN[run.status]
    if task.status != expected_task_status:
        raise EvaluationInputError(
            f"系统运行 {run.id} 与任务终态不一致："
            f"{run.status} 要求 task={expected_task_status}"
        )
    if run.generator != TRUSTED_GENERATOR:
        raise EvaluationInputError(
            f"系统运行 {run.id} 使用不可信的执行来源：{run.generator or 'unknown'}"
        )
    if (
        run.completed_at is None
        or (
            run.status != "cancelled"
            and (run.attempt_count < 1 or run.started_at is None)
        )
        or not run.prompt_snapshot
        or run.input_snapshot is None
        or run.input_digest is None
        or run.provenance_schema_version != GENERATION_PROVENANCE_SCHEMA_VERSION
    ):
        raise EvaluationInputError(f"系统运行 {run.id} 缺少完整执行快照")
    version_values = (
        run.model,
        run.prompt_digest,
        run.rules_digest,
        run.data_digest,
    )
    if any(not isinstance(value, str) or not value.strip() for value in version_values):
        raise EvaluationInputError(f"系统运行 {run.id} 缺少可信版本摘要")
    for digest_name in (
        "prompt_digest",
        "rules_digest",
        "data_digest",
        "input_digest",
    ):
        if not _SHA256_PATTERN.fullmatch(getattr(run, digest_name)):
            raise EvaluationInputError(f"系统运行 {run.id} 的 {digest_name} 不合法")
    if run.prompt_digest != canonical_digest(run.prompt_snapshot):
        raise EvaluationInputError(f"系统运行 {run.id} 的 Prompt 摘要与快照不一致")
    if run.input_digest != canonical_digest(run.input_snapshot):
        raise EvaluationInputError(f"系统运行 {run.id} 的输入摘要与快照不一致")
    if run.status != "completed":
        if any(
            value is not None
            for value in (
                run.result_revision_id,
                run.output_digest,
                run.output_snapshot,
            )
        ):
            raise EvaluationInputError(f"失败运行 {run.id} 不得携带生成输出")
        return run, None, persisted_binding
    try:
        output = generation_output_service.validated_run_output(db, run=run)
    except generation_output_service.GenerationOutputValidationError as exc:
        raise EvaluationInputError(
            f"系统运行 {run.id} 的不可变输出不可信：{exc}"
        ) from exc
    completed_nodes = {
        event.node for event in run.events if event.status == "completed"
    }
    missing_nodes = sorted(REQUIRED_RUN_NODES - completed_nodes)
    if missing_nodes:
        raise EvaluationInputError(
            f"系统运行 {run.id} 缺少 Worker 节点：{', '.join(missing_nodes)}"
        )
    completed_sources = {
        event.node: event.source
        for event in run.events
        if event.status == "completed" and event.node in REQUIRED_NODE_SOURCES
    }
    if any(
        completed_sources.get(node) != source
        for node, source in REQUIRED_NODE_SOURCES.items()
    ):
        raise EvaluationInputError(f"系统运行 {run.id} 的 Worker 节点来源不可信")
    return run, output, persisted_binding


def _quote_is_consistent(quote: dict[str, Any]) -> bool:
    raw = quote.get("quote")
    if not isinstance(raw, dict):
        return False
    line_items = raw.get("lineItems")
    custom_items = raw.get("customLineItems")
    if (
        not isinstance(line_items, list)
        or not isinstance(custom_items, list)
        or any(not isinstance(item, dict) for item in [*line_items, *custom_items])
    ):
        return False
    try:
        furniture_values = [
            (item["unitPrice"], item["quantity"]) for item in line_items
        ]
        custom_values = [
            (
                item.get("subtotal"),
                item.get("unitPrice"),
                item.get("quantity"),
            )
            for item in custom_items
        ]
        numbers = [value for pair in furniture_values for value in pair]
        numbers.extend(value for row in custom_values for value in row if value is not None)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in numbers
        ):
            return False
        furniture_total = sum(price * quantity for price, quantity in furniture_values)
        custom_total = sum(
            subtotal
            if subtotal is not None
            else round(unit_price * quantity)
            for subtotal, unit_price, quantity in custom_values
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return (
        furniture_total == quote.get("furniture_total")
        and custom_total == quote.get("custom_total")
        and furniture_total + custom_total == quote.get("grand_total")
    )


_MISSING = object()
_LOW_CONFIDENCE_THRESHOLD = 0.7


def _fact_value(payload: Any, path: str) -> Any:
    """只沿对象键精确寻址；不对数组或单房间做推断。"""
    current = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _same_scalar(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(float(left)) and math.isfinite(float(right)) and left == right
    return type(left) is type(right) and left == right


def _space_fact_confidence(room_model: dict[str, Any], path: str) -> float | None:
    parts = path.split(".")
    if (
        len(parts) == 3
        and parts[0] == "rooms"
        and parts[2] in {"width_m", "depth_m", "ceiling_height"}
    ):
        scale = room_model.get("scale")
        if isinstance(scale, dict):
            scale_confidence = scale.get("confidence")
            if (
                isinstance(scale_confidence, (int, float))
                and not isinstance(scale_confidence, bool)
                and math.isfinite(float(scale_confidence))
                and 0 <= scale_confidence <= 1
            ):
                return float(scale_confidence)
    parent_path = path.rsplit(".", 1)[0] if "." in path else ""
    parent = _fact_value(room_model, parent_path) if parent_path else room_model
    if isinstance(parent, dict):
        confidence = parent.get("confidence")
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and math.isfinite(float(confidence))
            and 0 <= confidence <= 1
        ):
            return float(confidence)
    confidence = room_model.get("confidence")
    if (
        isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and math.isfinite(float(confidence))
        and 0 <= confidence <= 1
    ):
        return float(confidence)
    return None


def _prediction_metrics(
    case: RealWorldCase,
    prediction: dict[str, Any],
) -> tuple[int, int, int, int, int, int]:
    annotation = case.annotation
    if annotation is None:
        raise EvaluationInputError(f"案例 {case.id} 缺少结构化标注")

    requirement = prediction.get("requirement")
    parsed = (
        requirement.get("parsed")
        if isinstance(requirement, dict)
        and requirement.get("available") is True
        and requirement.get("source") == "llm"
        and isinstance(requirement.get("parsed"), dict)
        else {}
    )
    requirement_correct = sum(
        _same_scalar(_fact_value(parsed, fact.field), fact.value)
        for fact in annotation.requirements
    )

    space = prediction.get("space")
    room_model = (
        space.get("room_model")
        if isinstance(space, dict)
        and space.get("available") is True
        and space.get("source") == "vl"
        and isinstance(space.get("room_model"), dict)
        else {}
    )
    confirmations = prediction.get("confirmations")
    confirmation_rows = confirmations if isinstance(confirmations, list) else []
    requires_confirmation = room_model.get("requires_confirmation")
    required_paths = (
        set(requires_confirmation)
        if isinstance(requires_confirmation, list)
        and all(isinstance(item, str) for item in requires_confirmation)
        else set()
    )
    space_correct = 0
    low_confidence_facts = 0
    low_confidence_confirmed = 0
    for fact in annotation.space_facts:
        predicted = _fact_value(room_model, fact.fact_path)
        if predicted is not _MISSING and _same_scalar(predicted, fact.value):
            space_correct += 1
        if predicted is _MISSING:
            continue
        confidence = _space_fact_confidence(room_model, fact.fact_path)
        is_low_confidence = (
            fact.fact_path in required_paths
            or (confidence is not None and confidence < _LOW_CONFIDENCE_THRESHOLD)
        )
        if not is_low_confidence:
            continue
        low_confidence_facts += 1
        if any(
            isinstance(row, dict)
            and row.get("fact_path") == fact.fact_path
            and _same_scalar(row.get("previous_value"), predicted)
            and _same_scalar(row.get("previous_confidence"), confidence)
            for row in confirmation_rows
        ):
            low_confidence_confirmed += 1
    return (
        requirement_correct,
        len(annotation.requirements),
        space_correct,
        len(annotation.space_facts),
        low_confidence_confirmed,
        low_confidence_facts,
    )


def _runtime_result(
    case: RealWorldCase,
    run: GenerationRun,
    output: dict[str, Any] | None,
    review: ExecutionReview | None,
    prediction: dict[str, Any],
) -> CaseResult:
    """从不可变业务输出和冻结标注确定性计算逐例指标。"""
    if run.status != "completed":
        return CaseResult(case_id=case.id, generation_succeeded=False)
    if output is None or case.annotation is None:
        raise EvaluationInputError(f"系统运行 {run.id} 缺少不可变输出或案例标注")
    plans = output.get("plans")
    if not isinstance(plans, list) or not plans:
        raise EvaluationInputError(f"系统运行 {run.id} 的不可变输出结构不完整")

    recommended_skus = 0
    valid_skus = 0
    quote_consistent = 0
    budget_within_limit = 0
    layout_passes = 0
    style_consistent = 0
    allowed_skus = set(case.annotation.allowed_skus)
    expected_constraints = case.annotation.layout_hard_constraints
    layout_no_evidence = 0
    for record in plans:
        if not isinstance(record, dict) or not isinstance(record.get("plan"), dict):
            raise EvaluationInputError(f"系统运行 {run.id} 包含不合法的方案版本")
        plan = record["plan"]
        suggestions = plan.get("furnitureSuggestions")
        if not isinstance(suggestions, list):
            suggestions = []
        recommended_skus += len(suggestions)
        for suggestion in suggestions:
            sku = None
            if isinstance(suggestion, dict):
                sku = suggestion.get("sku") or suggestion.get("id")
            if isinstance(sku, str) and sku in allowed_skus:
                valid_skus += 1
        quote = record.get("quote")
        if isinstance(quote, dict):
            if _quote_is_consistent(quote):
                quote_consistent += 1
            total = quote.get("grand_total")
            if (
                isinstance(total, int)
                and not isinstance(total, bool)
                and case.annotation.budget.minimum
                <= total
                <= case.annotation.budget.maximum
            ):
                budget_within_limit += 1
        scene_record = record.get("scene")
        document = (
            scene_record.get("document")
            if isinstance(scene_record, dict)
            else None
        )
        if not isinstance(document, dict):
            raise EvaluationInputError(
                f"系统运行 {run.id} 的方案缺少冻结 SceneDocument"
            )
        try:
            scene = SceneDocument.model_validate(document)
        except ValueError as exc:
            raise EvaluationInputError(
                f"系统运行 {run.id} 的冻结 SceneDocument 不合法"
            ) from exc
        for constraint in expected_constraints:
            evidence = evaluate_layout_constraint(scene, constraint)
            if evidence.status == "passed":
                layout_passes += 1
            if evidence.status == "no_evidence":
                layout_no_evidence += 1
        if record.get("style") in set(case.annotation.style_tags):
            style_consistent += 1

    actions = [edit.action for edit in review.edit_facts] if review else []
    (
        requirement_correct,
        requirement_total,
        space_fact_correct,
        space_fact_total,
        low_confidence_confirmed,
        low_confidence_facts,
    ) = _prediction_metrics(case, prediction)
    return CaseResult(
        case_id=case.id,
        requirement_correct=requirement_correct,
        requirement_total=requirement_total,
        space_fact_correct=space_fact_correct,
        space_fact_total=space_fact_total,
        low_confidence_facts=low_confidence_facts,
        low_confidence_confirmed=low_confidence_confirmed,
        recommended_skus=recommended_skus,
        valid_skus=valid_skus,
        product_match_checks=recommended_skus,
        product_match_accepted=valid_skus,
        quote_checks=len(plans),
        quote_consistent=quote_consistent,
        budget_checks=len(plans),
        budget_within_limit=budget_within_limit,
        # 缺少几何表达也是未满足真实标注，不能通过缩小分母抬高通过率。
        layout_checks=len(expected_constraints) * len(plans),
        layout_hard_passes=layout_passes,
        layout_no_evidence=layout_no_evidence,
        style_checks=len(plans),
        style_consistent=style_consistent,
        human_rating_count=1 if review else 0,
        human_rating_sum=review.overall_rating if review else 0,
        human_review_count=1 if review else 0,
        human_edit_count=len(actions),
        human_add_count=actions.count("add"),
        human_remove_count=actions.count("remove"),
        human_move_count=actions.count("move"),
        human_replace_count=actions.count("replace"),
        generation_succeeded=True,
    )


def _execution_review(
    *,
    binding: RunBinding,
    dataset: RealWorldDataset,
    dataset_root: Path | str | None,
    output_digest: str,
) -> ExecutionReview | None:
    path = binding.execution_review_path
    file_digest = binding.execution_review_sha256
    if path is None and file_digest is None:
        return None
    if path is None or file_digest is None:
        raise EvaluationInputError("人工评审路径与文件摘要必须成对提供")
    if dataset_root is None:
        raise EvaluationInputError("加载人工评审必须提供数据集根目录")
    try:
        return load_execution_review(
            path,
            dataset=dataset,
            dataset_root=dataset_root,
            expected_output_digest=output_digest,
            expected_sha256=file_digest,
        )
    except AnnotationValidationError as exc:
        raise EvaluationInputError(f"人工评审不可信：{exc}") from exc


def collect_trusted_evidence(
    db: Session,
    *,
    dataset: RealWorldDataset,
    split: EvaluationSplit,
    bindings: tuple[RunBinding, ...],
    dataset_root: Path | str | None = None,
    signing_key: str,
    key_id: str,
) -> dict[str, Any]:
    """从持久化系统运行签发匿名证据包，不接受调用方提交 CaseResult。"""
    _normalized_key(signing_key)
    if not isinstance(key_id, str) or not key_id.strip():
        raise EvaluationInputError("评测证据 key_id 不能为空")
    normalized_split = validate_evaluation_split(split)
    eligible = _validate_binding_sets(
        bindings=bindings,
        dataset=dataset,
        split=normalized_split,
    )
    dataset_digest = dataset_fingerprint(dataset, split=normalized_split)
    executions: list[dict[str, Any]] = []
    version_candidates: set[tuple[str, str, str, str]] = set()
    for binding in bindings:
        case = eligible[binding.case_id]
        case_digest = _case_fingerprint(dataset_digest, case.id)
        run, output, persisted_binding = _validate_system_run(
            db,
            binding=binding,
            expected_case_fingerprint=case_digest,
            expected_split=normalized_split,
        )
        version_candidates.add(
            (
                run.model,
                run.prompt_digest,
                run.rules_digest,
                run.data_digest,
            )
        )
        review = None
        if run.status == "completed":
            review = _execution_review(
                binding=binding,
                dataset=dataset,
                dataset_root=dataset_root,
                output_digest=run.output_digest,
            )
        elif (
            binding.execution_review_path is not None
            or binding.execution_review_sha256 is not None
        ):
            raise EvaluationInputError("失败运行不能绑定人工输出评审")
        result = _runtime_result(
            case,
            run,
            output,
            review,
            persisted_binding.prediction_snapshot_json,
        )
        result_payload = asdict(result)
        result_payload.pop("case_id")
        executions.append(
            {
                "case_fingerprint": case_digest,
                "execution_ref": _execution_ref(
                    task_id=run.task_id,
                    run_id=run.id,
                    deployment_key=signing_key,
                ),
                "source": "generation_worker",
                "generator": run.generator,
                "status": run.status,
                "model": run.model,
                "prompt_digest": run.prompt_digest,
                "rules_digest": run.rules_digest,
                "data_digest": run.data_digest,
                "input_digest": run.input_digest,
                "prediction_digest": persisted_binding.prediction_digest,
                "output_digest": run.output_digest,
                "result": result_payload,
                "result_digest": _digest(result_payload),
            }
        )
    if len(version_candidates) != 1:
        raise EvaluationInputError("证据包内系统运行的模型或制品版本不一致")
    model, prompt_digest, rules_digest, data_digest = next(
        iter(version_candidates)
    )
    versions = EvaluationVersions(
        model=model,
        prompt=prompt_digest,
        rules=rules_digest,
        data=data_digest,
    )
    _validate_versions(versions)
    unsigned: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_type": EVIDENCE_TYPE,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "dataset_fingerprint": dataset_digest,
        "split": normalized_split,
        "versions": asdict(versions),
        "executions": sorted(
            executions,
            key=lambda item: item["case_fingerprint"],
        ),
    }
    return {
        **unsigned,
        "attestation": {
            "algorithm": ATTESTATION_ALGORITHM,
            "key_id": key_id.strip(),
            "signature": _signature(unsigned, signing_key),
        },
    }


def _required_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvaluationInputError(f"{field_name} 必须是对象")
    return value


def _parse_versions(raw: Any) -> EvaluationVersions:
    values = _required_mapping(raw, "versions")
    if set(values) != {"model", "prompt", "rules", "data"}:
        raise EvaluationInputError("versions 字段不合法")
    try:
        return EvaluationVersions(
            model=str(values.get("model") or ""),
            prompt=str(values.get("prompt") or ""),
            rules=str(values.get("rules") or ""),
            data=str(values.get("data") or ""),
        )
    except (TypeError, ValueError) as exc:
        raise EvaluationInputError(str(exc)) from exc


def _parse_result(raw: Any, *, case_id: str, index: int) -> CaseResult:
    values = _required_mapping(raw, f"第 {index + 1} 条 result")
    allowed = set(CaseResult.__dataclass_fields__) - {"case_id"}
    unknown = sorted(set(values) - allowed)
    if "case_id" in values:
        raise EvaluationInputError(f"第 {index + 1} 条 result 不得包含 case_id")
    if unknown:
        raise EvaluationInputError(
            f"第 {index + 1} 条 result 含未知字段：{', '.join(unknown)}"
        )
    try:
        return CaseResult(case_id=case_id, **values)
    except (TypeError, ValueError) as exc:
        raise EvaluationInputError(f"第 {index + 1} 条 result 不合法：{exc}") from exc


def verify_trusted_evidence(
    payload: dict[str, Any],
    *,
    dataset: RealWorldDataset,
    split: EvaluationSplit,
    verification_keys: Mapping[str, str],
) -> VerifiedEvaluationEvidence:
    if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        if payload.get("schema_version") == "1.0":
            raise EvaluationInputError("结果 schema 1.0 不接受手工结果，请使用系统证据收集器")
        if payload.get("schema_version") == "3.0":
            raise EvaluationInputError("结果 schema 3.0 未绑定不可变方案输出")
        if payload.get("schema_version") == "4.0":
            raise EvaluationInputError("结果 schema 4.0 未绑定真实模型预测证据")
        raise EvaluationInputError(
            f"不支持的结果 schema_version：{payload.get('schema_version')}"
        )
    normalized_split = validate_evaluation_split(split)
    allowed_top = {
        "schema_version",
        "evidence_type",
        "issued_at",
        "dataset_fingerprint",
        "split",
        "versions",
        "executions",
        "attestation",
    }
    unknown_top = sorted(set(payload) - allowed_top)
    if unknown_top:
        raise EvaluationInputError(f"证据包含未知字段：{', '.join(unknown_top)}")
    if payload.get("evidence_type") != EVIDENCE_TYPE:
        raise EvaluationInputError("证据包不是实际系统执行证据")
    if payload.get("split") != normalized_split:
        raise EvaluationInputError("证据包 split 与本次评测 split 不一致")
    issued_at = payload.get("issued_at")
    if not isinstance(issued_at, str):
        raise EvaluationInputError("证据包缺少 issued_at")
    try:
        issued_datetime = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvaluationInputError("证据包 issued_at 不合法") from exc
    if issued_datetime.tzinfo is None:
        raise EvaluationInputError("证据包 issued_at 必须包含时区")
    attestation = _required_mapping(payload.get("attestation"), "attestation")
    if set(attestation) != {"algorithm", "key_id", "signature"}:
        raise EvaluationInputError("attestation 字段不合法")
    if attestation.get("algorithm") != ATTESTATION_ALGORITHM:
        raise EvaluationInputError("证据签名算法不受支持")
    key_id = attestation.get("key_id")
    if not isinstance(key_id, str) or not key_id.strip():
        raise EvaluationInputError("证据缺少 key_id")
    signing_key = verification_keys.get(key_id)
    if not signing_key:
        raise EvaluationInputError(f"缺少验签密钥：{key_id}")
    supplied_signature = attestation.get("signature")
    if not isinstance(supplied_signature, str):
        raise EvaluationInputError("证据签名无效")
    unsigned = {key: value for key, value in payload.items() if key != "attestation"}
    expected_signature = _signature(unsigned, signing_key)
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise EvaluationInputError("证据签名无效，内容可能已被篡改")

    versions = _parse_versions(payload.get("versions"))
    _validate_versions(versions)
    expected_dataset_digest = dataset_fingerprint(
        dataset,
        split=normalized_split,
    )
    if payload.get("dataset_fingerprint") != expected_dataset_digest:
        raise EvaluationInputError("证据绑定的数据集指纹与当前清单不一致")
    raw_executions = payload.get("executions")
    if not isinstance(raw_executions, list):
        raise EvaluationInputError("executions 必须是数组")
    case_by_fingerprint = {
        _case_fingerprint(expected_dataset_digest, case.id): case
        for case in dataset.eligible_cases(normalized_split)
    }
    seen_cases: set[str] = set()
    seen_execution_refs: set[str] = set()
    results: list[CaseResult] = []
    provenances: list[ExecutionProvenance] = []
    allowed_execution_fields = {
        "case_fingerprint",
        "execution_ref",
        "source",
        "generator",
        "status",
        "model",
        "prompt_digest",
        "rules_digest",
        "data_digest",
        "input_digest",
        "prediction_digest",
        "output_digest",
        "result",
        "result_digest",
    }
    for index, raw in enumerate(raw_executions):
        execution = _required_mapping(raw, f"第 {index + 1} 条 execution")
        if set(execution) != allowed_execution_fields:
            raise EvaluationInputError(f"第 {index + 1} 条 execution 字段不合法")
        case_digest = execution.get("case_fingerprint")
        if not isinstance(case_digest, str) or case_digest not in case_by_fingerprint:
            raise EvaluationInputError(f"第 {index + 1} 条 execution 案例指纹未知")
        if case_digest in seen_cases:
            raise EvaluationInputError("证据包含重复案例指纹")
        seen_cases.add(case_digest)
        execution_ref = execution.get("execution_ref")
        if (
            not isinstance(execution_ref, str)
            or not _EXECUTION_REF_PATTERN.fullmatch(execution_ref)
        ):
            raise EvaluationInputError(
                f"第 {index + 1} 条 execution_ref 不合法"
            )
        if execution_ref in seen_execution_refs:
            raise EvaluationInputError("同一 execution_ref 不能跨案例重放")
        seen_execution_refs.add(execution_ref)
        if (
            execution.get("source") != "generation_worker"
            or execution.get("generator") != TRUSTED_GENERATOR
            or execution.get("status") not in TRUSTED_TERMINAL_STATUSES
            or execution.get("model") != versions.model
            or execution.get("prompt_digest") != versions.prompt
            or execution.get("rules_digest") != versions.rules
            or execution.get("data_digest") != versions.data
        ):
            raise EvaluationInputError(f"第 {index + 1} 条 execution 不是可信终态运行")
        for digest_name in (
            "prompt_digest",
            "rules_digest",
            "data_digest",
            "input_digest",
            "prediction_digest",
            "result_digest",
        ):
            digest_value = execution.get(digest_name)
            if not isinstance(digest_value, str) or not _SHA256_PATTERN.fullmatch(
                digest_value
            ):
                raise EvaluationInputError(
                    f"第 {index + 1} 条 execution 缺少 {digest_name}"
                )
        output_digest = execution.get("output_digest")
        if execution.get("status") == "completed":
            if not isinstance(output_digest, str) or not _SHA256_PATTERN.fullmatch(
                output_digest
            ):
                raise EvaluationInputError(
                    f"第 {index + 1} 条成功 execution 缺少 output_digest"
                )
        elif output_digest is not None:
            raise EvaluationInputError(
                f"第 {index + 1} 条失败 execution 不得包含 output_digest"
            )
        result_payload = execution.get("result")
        if execution["result_digest"] != _digest(result_payload):
            raise EvaluationInputError(f"第 {index + 1} 条 result 摘要不一致")
        case = case_by_fingerprint[case_digest]
        result = _parse_result(result_payload, case_id=case.id, index=index)
        expected_success = execution.get("status") == "completed"
        if result.generation_succeeded is not expected_success:
            raise EvaluationInputError(
                f"第 {index + 1} 条 generation_succeeded 与运行终态不一致"
            )
        results.append(result)
        provenances.append(
            ExecutionProvenance(
                case_fingerprint=case_digest,
                execution_ref=execution_ref,
                source=execution["source"],
                generator=execution["generator"],
                status=execution["status"],
                model=execution["model"],
                prompt_digest=execution["prompt_digest"],
                rules_digest=execution["rules_digest"],
                data_digest=execution["data_digest"],
                input_digest=execution["input_digest"],
                prediction_digest=execution["prediction_digest"],
                output_digest=execution["output_digest"],
                result_digest=execution["result_digest"],
            )
        )
    missing = sorted(set(case_by_fingerprint) - seen_cases)
    if missing:
        raise EvaluationInputError(f"缺少已准入案例执行证据：{len(missing)} 条")
    return VerifiedEvaluationEvidence(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        versions=versions,
        dataset_fingerprint=expected_dataset_digest,
        evidence_digest=_digest(payload),
        split=normalized_split,
        results=tuple(results),
        executions=tuple(provenances),
        key_id=key_id,
    )
