"""正式评测运行的任务输入与资产绑定。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DesignTask,
    EvaluationRunBinding,
    GenerationRun,
    UploadedImage,
)
from app.services.generation_provenance import (
    GENERATION_PROVENANCE_SCHEMA_VERSION,
    canonical_digest,
)
from app.services import prediction_evidence_service


EVALUATION_IDEMPOTENCY_PREFIX = "eval-v1:"
_TASK_INPUT_FIELDS = frozenset(
    {
        "raw_user_input",
        "confirmed_requirement",
        "space_type",
        "style",
        "budget_min",
        "budget_max",
        "image_context",
    }
)


class EvaluationBindingError(ValueError):
    """评测运行没有绑定到冻结的案例任务输入。"""


@dataclass(frozen=True)
class EvaluationBindingSpec:
    case_fingerprint: str
    asset_digest: str
    task_input_digest: str
    dataset_split: str
    model: str
    prompt_snapshot: str
    prompt_digest: str
    rules_digest: str
    data_digest: str
    input_snapshot: dict[str, Any]
    input_digest: str
    provenance_schema_version: int
    requirement_parse_result_id: int | None
    uploaded_image_id: int
    prediction_snapshot: dict[str, Any]
    prediction_digest: str


def is_evaluation_idempotency_key(value: str | None) -> bool:
    return bool(value and value.startswith(EVALUATION_IDEMPOTENCY_PREFIX))


def evaluation_execution_digest(spec: EvaluationBindingSpec) -> str:
    return canonical_digest(
        {
            "case_fingerprint": spec.case_fingerprint,
            "dataset_split": spec.dataset_split,
            "model": spec.model,
            "prompt_digest": spec.prompt_digest,
            "rules_digest": spec.rules_digest,
            "data_digest": spec.data_digest,
            "prediction_digest": spec.prediction_digest,
        }
    )


def evaluation_idempotency_key(spec: EvaluationBindingSpec) -> str:
    digest = evaluation_execution_digest(spec)
    return EVALUATION_IDEMPOTENCY_PREFIX + digest.removeprefix("sha256:")


def normalize_task_input(value: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(value) - _TASK_INPUT_FIELDS)
    if unknown:
        raise EvaluationBindingError(
            f"评测任务输入包含未知字段：{', '.join(unknown)}"
        )
    raw_user_input = value.get("raw_user_input")
    confirmed_requirement = value.get("confirmed_requirement")
    if raw_user_input is not None and not isinstance(raw_user_input, str):
        raise EvaluationBindingError("raw_user_input 必须是字符串或 null")
    if confirmed_requirement is not None and not isinstance(
        confirmed_requirement, dict
    ):
        raise EvaluationBindingError("confirmed_requirement 必须是对象或 null")

    normalized: dict[str, Any] = {
        "raw_user_input": (
            raw_user_input.strip() if isinstance(raw_user_input, str) else None
        ),
        "confirmed_requirement": confirmed_requirement,
    }
    for field_name in ("space_type", "style"):
        field_value = value.get(field_name)
        if field_value is not None and not isinstance(field_value, str):
            raise EvaluationBindingError(f"{field_name} 必须是字符串或 null")
        normalized[field_name] = (
            field_value.strip() if isinstance(field_value, str) else None
        )
    for field_name in ("budget_min", "budget_max"):
        field_value = value.get(field_name)
        if isinstance(field_value, bool) or (
            field_value is not None and not isinstance(field_value, int)
        ):
            raise EvaluationBindingError(f"{field_name} 必须是整数或 null")
        if isinstance(field_value, int) and field_value < 0:
            raise EvaluationBindingError(f"{field_name} 不能为负数")
        normalized[field_name] = field_value
    if (
        normalized["budget_min"] is not None
        and normalized["budget_max"] is not None
        and normalized["budget_min"] > normalized["budget_max"]
    ):
        raise EvaluationBindingError("budget_min 不能大于 budget_max")
    image_context = value.get("image_context", [])
    if not isinstance(image_context, list) or any(
        not isinstance(item, str) or not item.strip() for item in image_context
    ):
        raise EvaluationBindingError("image_context 必须是非空字符串数组")
    normalized["image_context"] = [item.strip() for item in image_context]
    return normalized


def task_input_payload(db: Session, task: DesignTask) -> dict[str, Any]:
    images = db.scalars(
        select(UploadedImage)
        .where(UploadedImage.task_id == task.id)
        .order_by(UploadedImage.id)
    ).all()
    image_context: list[str] = []
    for image in images:
        analysis = image.analysis_json if isinstance(image.analysis_json, dict) else {}
        findings = analysis.get("findings")
        if isinstance(findings, list):
            image_context.extend(
                str(item).strip() for item in findings if str(item).strip()
            )
    return normalize_task_input(
        {
            "raw_user_input": task.raw_user_input,
            "confirmed_requirement": task.confirmed_requirement_json,
            "space_type": task.space_type,
            "style": task.style,
            "budget_min": task.budget_min,
            "budget_max": task.budget_max,
            "image_context": image_context,
        }
    )


def task_input_digest(db: Session, task: DesignTask) -> str:
    return canonical_digest(task_input_payload(db, task))


def expected_task_input_digest(value: Mapping[str, Any]) -> str:
    return canonical_digest(normalize_task_input(value))


def task_asset_digests(db: Session, *, task_id: int) -> list[str | None]:
    return list(
        db.scalars(
            select(UploadedImage.content_digest)
            .where(UploadedImage.task_id == task_id)
            .order_by(UploadedImage.id)
        ).all()
    )


def validate_spec_for_task(
    db: Session,
    *,
    task: DesignTask,
    spec: EvaluationBindingSpec,
) -> None:
    if spec.dataset_split not in {"development", "regression", "blind"}:
        raise EvaluationBindingError("评测绑定缺少合法 split")
    if not spec.model.strip() or not spec.prompt_snapshot:
        raise EvaluationBindingError("评测绑定缺少执行前模型或 Prompt 快照")
    if not isinstance(spec.input_snapshot, dict) or not spec.input_snapshot:
        raise EvaluationBindingError("评测绑定缺少执行前输入快照")
    if canonical_digest(spec.prompt_snapshot) != spec.prompt_digest:
        raise EvaluationBindingError("评测绑定的 Prompt 摘要不一致")
    if canonical_digest(spec.input_snapshot) != spec.input_digest:
        raise EvaluationBindingError("评测绑定的输入摘要不一致")
    if canonical_digest(spec.prediction_snapshot) != spec.prediction_digest:
        raise EvaluationBindingError("评测绑定的预测证据摘要不一致")
    if task.user_id is not None:
        raise EvaluationBindingError("评测任务不能依赖可变的用户画像")
    if task_input_digest(db, task) != spec.task_input_digest:
        raise EvaluationBindingError("当前任务输入与评测案例不一致")
    asset_digests = task_asset_digests(db, task_id=task.id)
    if len(asset_digests) != 1 or asset_digests[0] != spec.asset_digest:
        raise EvaluationBindingError("当前任务绑定的案例资产不唯一或不一致")


def validate_persisted_binding(
    db: Session,
    *,
    run: GenerationRun,
    validate_current_generation: bool = False,
) -> EvaluationRunBinding:
    binding = db.scalar(
        select(EvaluationRunBinding).where(
            EvaluationRunBinding.generation_run_id == run.id
        )
    )
    if binding is None:
        raise EvaluationBindingError("系统运行缺少持久化评测绑定")
    if binding.task_id != run.task_id:
        raise EvaluationBindingError("评测绑定的任务与系统运行不一致")
    if (
        not isinstance(binding.prediction_snapshot_json, dict)
        or not isinstance(binding.prediction_digest, str)
    ):
        raise EvaluationBindingError("历史评测绑定缺少预测证据，不能作为可信证据")
    frozen_values = {
        "model": binding.model,
        "prompt_digest": binding.prompt_digest,
        "rules_digest": binding.rules_digest,
        "data_digest": binding.data_digest,
        "input_digest": binding.input_digest,
        "provenance_schema_version": binding.provenance_schema_version,
    }
    if binding.dataset_split not in {"development", "regression", "blind"}:
        raise EvaluationBindingError("历史评测绑定缺少合法 split，不能作为可信证据")
    if any(value is None or value == "" for value in frozen_values.values()):
        raise EvaluationBindingError("历史评测绑定缺少执行前冻结版本，不能作为可信证据")
    if any(getattr(run, name) != value for name, value in frozen_values.items()):
        raise EvaluationBindingError("系统运行版本与执行前评测绑定不一致")
    expected_key = evaluation_idempotency_key(
        EvaluationBindingSpec(
            case_fingerprint=binding.case_fingerprint,
            asset_digest=binding.asset_digest,
            task_input_digest=binding.task_input_digest,
            dataset_split=binding.dataset_split,
            model=binding.model,
            prompt_snapshot=run.prompt_snapshot or "",
            prompt_digest=binding.prompt_digest,
            rules_digest=binding.rules_digest,
            data_digest=binding.data_digest,
            input_snapshot=run.input_snapshot or {},
            input_digest=binding.input_digest,
            provenance_schema_version=binding.provenance_schema_version,
            requirement_parse_result_id=binding.requirement_parse_result_id,
            uploaded_image_id=binding.uploaded_image_id,
            prediction_snapshot=binding.prediction_snapshot_json or {},
            prediction_digest=binding.prediction_digest or "",
        )
    )
    if run.idempotency_key != expected_key:
        raise EvaluationBindingError("评测绑定与运行幂等键不一致")
    task = db.get(DesignTask, run.task_id)
    if task is None:
        raise EvaluationBindingError("评测绑定的任务不存在")
    validate_spec_for_task(
        db,
        task=task,
        spec=EvaluationBindingSpec(
            case_fingerprint=binding.case_fingerprint,
            asset_digest=binding.asset_digest,
            task_input_digest=binding.task_input_digest,
            dataset_split=binding.dataset_split,
            model=binding.model,
            prompt_snapshot=run.prompt_snapshot or "",
            prompt_digest=binding.prompt_digest,
            rules_digest=binding.rules_digest,
            data_digest=binding.data_digest,
            input_snapshot=run.input_snapshot or {},
            input_digest=binding.input_digest,
            provenance_schema_version=binding.provenance_schema_version,
            requirement_parse_result_id=binding.requirement_parse_result_id,
            uploaded_image_id=binding.uploaded_image_id,
            prediction_snapshot=binding.prediction_snapshot_json or {},
            prediction_digest=binding.prediction_digest or "",
        ),
    )
    try:
        prediction_evidence_service.validate_frozen_prediction(
            db,
            task=task,
            binding=binding,
        )
    except prediction_evidence_service.PredictionEvidenceError as exc:
        raise EvaluationBindingError(str(exc)) from exc
    if validate_current_generation:
        _validate_current_generation_facts(db, task=task, binding=binding)
    return binding


def _validate_current_generation_facts(
    db: Session,
    *,
    task: DesignTask,
    binding: EvaluationRunBinding,
) -> None:
    """Worker 领取前复算当前部署的完整生成事实，防止绑定后混版。"""
    from app.core.config import settings
    from app.services import generation_constraints_service, llm_service
    from app.services.generation_provenance import build_generation_provenance

    payload = task_input_payload(db, task)
    requirement = payload.get("confirmed_requirement")
    if not isinstance(requirement, dict) or not requirement:
        raise EvaluationBindingError("正式评测缺少冻结的 confirmed_requirement")
    generation_context = generation_constraints_service.build_generation_context(
        db,
        task,
        requirement=requirement,
    )
    requirement_for_llm = dict(generation_context.requirement)
    image_context = payload.get("image_context") or []
    if image_context:
        requirement_for_llm["image_analysis"] = list(image_context)
    catalog_context = generation_context.catalog_context
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
    current_values = {
        "model": settings.llm_model,
        "prompt_digest": provenance["prompt_digest"],
        "rules_digest": provenance["rules_digest"],
        "data_digest": provenance["data_digest"],
        "input_digest": provenance["input_digest"],
        "provenance_schema_version": GENERATION_PROVENANCE_SCHEMA_VERSION,
    }
    if any(getattr(binding, name) != value for name, value in current_values.items()):
        raise EvaluationBindingError("当前生成制品或完整输入与执行前评测绑定不一致")
