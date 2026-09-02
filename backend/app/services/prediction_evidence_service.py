"""真实模型确认前预测的规范化、冻结与完整性校验。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DesignTask,
    EvaluationRunBinding,
    RequirementParseResult,
    RoomFactConfirmation,
    UploadedImage,
)
from app.schemas.room_model import RoomModel
from app.services.generation_provenance import canonical_digest


PREDICTION_EVIDENCE_SCHEMA_VERSION = "1.0"


class PredictionEvidenceError(ValueError):
    """预测源或冻结快照不满足可信证据约束。"""


def normalize_room_prediction(raw: dict[str, Any]) -> dict[str, Any]:
    """严格校验 RoomModel，并将有标识的数组转为可寻址映射。"""
    model = RoomModel.model_validate(raw)
    payload = model.model_dump(mode="json")
    payload["rooms"] = {room["id"]: room for room in payload["rooms"]}
    payload["doors"] = {item["id"]: item for item in payload["doors"]}
    payload["windows"] = {item["id"]: item for item in payload["windows"]}
    payload["walls"] = {
        f"{item['room_id']}:{item['wall_index']}": item
        for item in payload["walls"]
    }
    return payload


def capture_uploaded_prediction(
    image: UploadedImage,
    *,
    raw_room_model: dict[str, Any] | None,
    source: str,
) -> None:
    """保存上传时的原始预测；重复调用不得覆盖已有快照。"""
    normalized_source = source.strip()
    if image.original_prediction_source is not None:
        raise PredictionEvidenceError("上传图片的原始预测已经写入，不能覆盖")
    image.original_prediction_source = normalized_source
    if normalized_source != "vl" or raw_room_model is None:
        image.original_prediction_json = None
        image.original_prediction_digest = None
        return
    normalized = normalize_room_prediction(raw_room_model)
    image.original_prediction_json = normalized
    image.original_prediction_digest = canonical_digest(normalized)


def _requirement_prediction(
    db: Session,
    *,
    task: DesignTask,
) -> tuple[dict[str, Any], int | None]:
    result = db.scalars(
        select(RequirementParseResult)
        .where(
            RequirementParseResult.task_id == task.id,
            RequirementParseResult.parser == "llm",
            RequirementParseResult.raw_input == (task.raw_user_input or ""),
        )
        .order_by(RequirementParseResult.id.desc())
    ).first()
    if result is None or not isinstance(result.parsed_json, dict):
        return {"available": False, "source": None, "parsed": None}, None
    return (
        {
            "available": True,
            "source": "llm",
            "parse_result_id": result.id,
            "raw_input": result.raw_input,
            "parsed": result.parsed_json,
        },
        result.id,
    )


def _space_prediction(
    image: UploadedImage,
) -> dict[str, Any]:
    source = image.original_prediction_source
    if source != "vl":
        return {
            "available": False,
            "source": source,
            "image_id": image.id,
            "room_model": None,
        }
    if (
        not isinstance(image.original_prediction_json, dict)
        or not isinstance(image.original_prediction_digest, str)
        or canonical_digest(image.original_prediction_json)
        != image.original_prediction_digest
    ):
        raise PredictionEvidenceError("上传图片的原始 VL 预测摘要不一致")
    # 再次校验字段，并确保保存形态是按 room.id 规范化后的结构。
    raw = dict(image.original_prediction_json)
    rooms = raw.get("rooms")
    if not isinstance(rooms, dict):
        raise PredictionEvidenceError("上传图片的原始 VL 预测未按 room.id 规范化")
    try:
        denormalized = {**raw, "rooms": list(rooms.values())}
        for field_name in ("doors", "windows", "walls"):
            value = denormalized.get(field_name)
            if isinstance(value, dict):
                denormalized[field_name] = list(value.values())
        normalized = normalize_room_prediction(denormalized)
    except (TypeError, ValueError) as exc:
        raise PredictionEvidenceError("上传图片的原始 VL 预测结构不合法") from exc
    if normalized != raw:
        raise PredictionEvidenceError("上传图片的原始 VL 预测规范化结果不一致")
    return {
        "available": True,
        "source": "vl",
        "image_id": image.id,
        "room_model": raw,
    }


def _confirmation_snapshot(
    db: Session,
    *,
    task_id: int,
    image_id: int,
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(RoomFactConfirmation)
        .where(
            RoomFactConfirmation.task_id == task_id,
            RoomFactConfirmation.image_id == image_id,
        )
        .order_by(RoomFactConfirmation.id)
    ).all()
    return [
        {
            "confirmation_id": row.id,
            "fact_path": row.fact_path,
            "previous_value": row.previous_value_json,
            "confirmed_value": row.confirmed_value_json,
            "previous_confidence": row.previous_confidence,
            "confirmed_by_type": row.confirmed_by_type,
            "confirmed_by_id": row.confirmed_by_id,
            "confirmed_at": (
                row.confirmed_at.isoformat() if row.confirmed_at is not None else None
            ),
        }
        for row in rows
    ]


def build_prediction_snapshot(
    db: Session,
    *,
    task: DesignTask,
) -> tuple[dict[str, Any], int | None, int | None]:
    requirement, parse_result_id = _requirement_prediction(db, task=task)
    images = db.scalars(
        select(UploadedImage)
        .where(UploadedImage.task_id == task.id)
        .order_by(UploadedImage.id)
    ).all()
    if len(images) != 1:
        raise PredictionEvidenceError("预测证据要求任务唯一绑定一张案例图片")
    image = images[0]
    space = _space_prediction(image)
    snapshot = {
        "schema_version": PREDICTION_EVIDENCE_SCHEMA_VERSION,
        "requirement": requirement,
        "space": space,
        "confirmations": _confirmation_snapshot(
            db,
            task_id=task.id,
            image_id=image.id,
        ),
    }
    return snapshot, parse_result_id, image.id


def validate_frozen_prediction(
    db: Session,
    *,
    task: DesignTask,
    binding: EvaluationRunBinding,
) -> dict[str, Any]:
    snapshot = binding.prediction_snapshot_json
    digest = binding.prediction_digest
    if not isinstance(snapshot, dict) or not isinstance(digest, str):
        raise PredictionEvidenceError("历史评测绑定缺少预测证据，不能作为可信证据")
    if canonical_digest(snapshot) != digest:
        raise PredictionEvidenceError("评测绑定的预测证据摘要不一致")
    current, parse_result_id, image_id = build_prediction_snapshot(db, task=task)
    if (
        current != snapshot
        or binding.requirement_parse_result_id != parse_result_id
        or binding.uploaded_image_id != image_id
    ):
        raise PredictionEvidenceError("评测绑定后的模型预测证据已发生变化")
    return snapshot
