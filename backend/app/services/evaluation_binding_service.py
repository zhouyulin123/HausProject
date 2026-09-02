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
from app.services.generation_provenance import canonical_digest


EVALUATION_IDEMPOTENCY_PREFIX = "eval-v1:"
_TASK_INPUT_FIELDS = frozenset(
    {
        "raw_user_input",
        "confirmed_requirement",
        "space_type",
        "style",
        "budget_min",
        "budget_max",
    }
)


class EvaluationBindingError(ValueError):
    """评测运行没有绑定到冻结的案例任务输入。"""


@dataclass(frozen=True)
class EvaluationBindingSpec:
    case_fingerprint: str
    asset_digest: str
    task_input_digest: str


def is_evaluation_idempotency_key(value: str | None) -> bool:
    return bool(value and value.startswith(EVALUATION_IDEMPOTENCY_PREFIX))


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
    return normalized


def task_input_payload(task: DesignTask) -> dict[str, Any]:
    return normalize_task_input(
        {
            "raw_user_input": task.raw_user_input,
            "confirmed_requirement": task.confirmed_requirement_json,
            "space_type": task.space_type,
            "style": task.style,
            "budget_min": task.budget_min,
            "budget_max": task.budget_max,
        }
    )


def task_input_digest(task: DesignTask) -> str:
    return canonical_digest(task_input_payload(task))


def expected_task_input_digest(value: Mapping[str, Any]) -> str:
    return canonical_digest(normalize_task_input(value))


def task_asset_digests(db: Session, *, task_id: int) -> set[str]:
    return {
        digest
        for digest in db.scalars(
            select(UploadedImage.content_digest).where(
                UploadedImage.task_id == task_id,
                UploadedImage.content_digest.is_not(None),
            )
        ).all()
        if isinstance(digest, str) and digest
    }


def validate_spec_for_task(
    db: Session,
    *,
    task: DesignTask,
    spec: EvaluationBindingSpec,
) -> None:
    if task_input_digest(task) != spec.task_input_digest:
        raise EvaluationBindingError("当前任务输入与评测案例不一致")
    asset_digests = task_asset_digests(db, task_id=task.id)
    if asset_digests != {spec.asset_digest}:
        raise EvaluationBindingError("当前任务绑定的案例资产不唯一或不一致")


def validate_persisted_binding(
    db: Session,
    *,
    run: GenerationRun,
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
    expected_key = (
        EVALUATION_IDEMPOTENCY_PREFIX
        + binding.case_fingerprint.removeprefix("sha256:")
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
        ),
    )
    return binding
