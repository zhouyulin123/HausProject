"""设计反馈事件写入、资源归属与幂等控制。"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    DesignFeedbackEvent,
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    Product,
)
from app.schemas.feedback import DesignFeedbackEventRequest


class FeedbackResourceNotFound(ValueError):
    pass


class FeedbackIdempotencyConflict(ValueError):
    pass


def _payload_hash(payload: DesignFeedbackEventRequest) -> str:
    encoded = json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_plan(db: Session, *, task_id: int, plan_version_id: int) -> None:
    plan_id = db.scalar(
        select(DesignPlanVersion.id)
        .join(DesignRevision, DesignRevision.id == DesignPlanVersion.revision_id)
        .where(
            DesignPlanVersion.id == plan_version_id,
            DesignRevision.task_id == task_id,
        )
    )
    if plan_id is None:
        raise FeedbackResourceNotFound("方案版本不存在或不属于当前任务")


def _require_scene(
    db: Session,
    *,
    task_id: int,
    scene_id: int,
    scene_version: int,
) -> None:
    scene = db.scalar(
        select(DesignScene)
        .join(
            DesignPlanVersion,
            DesignPlanVersion.id == DesignScene.plan_version_id,
        )
        .join(DesignRevision, DesignRevision.id == DesignPlanVersion.revision_id)
        .where(DesignScene.id == scene_id, DesignRevision.task_id == task_id)
    )
    if scene is None:
        raise FeedbackResourceNotFound("场景不存在或不属于当前任务")
    version_id = db.scalar(
        select(DesignSceneVersion.id).where(
            DesignSceneVersion.scene_id == scene.id,
            DesignSceneVersion.version == scene_version,
        )
    )
    if version_id is None:
        raise FeedbackResourceNotFound("场景版本不存在或不属于当前场景")


def _require_skus(db: Session, skus: set[str]) -> None:
    if not skus:
        return
    existing = set(
        db.scalars(select(Product.sku).where(Product.sku.in_(sorted(skus)))).all()
    )
    missing = sorted(skus - existing)
    if missing:
        raise FeedbackResourceNotFound(f"商品 SKU 不存在：{', '.join(missing)}")


def create_feedback_event(
    db: Session,
    *,
    task_id: int,
    payload: DesignFeedbackEventRequest,
) -> DesignFeedbackEvent:
    digest = _payload_hash(payload)
    existing = db.scalar(
        select(DesignFeedbackEvent).where(
            DesignFeedbackEvent.task_id == task_id,
            DesignFeedbackEvent.client_event_id == payload.client_event_id,
        )
    )
    if existing is not None:
        if existing.payload_hash != digest:
            raise FeedbackIdempotencyConflict("client_event_id 已用于不同反馈事件")
        return existing

    if payload.plan_version_id is not None:
        _require_plan(
            db,
            task_id=task_id,
            plan_version_id=payload.plan_version_id,
        )
    if payload.scene_id is not None and payload.scene_version is not None:
        _require_scene(
            db,
            task_id=task_id,
            scene_id=payload.scene_id,
            scene_version=payload.scene_version,
        )
    _require_skus(
        db,
        {
            sku
            for sku in (payload.source_sku, payload.target_sku)
            if sku is not None
        },
    )
    event = DesignFeedbackEvent(
        task_id=task_id,
        payload_hash=digest,
        **payload.model_dump(mode="json"),
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(DesignFeedbackEvent).where(
                DesignFeedbackEvent.task_id == task_id,
                DesignFeedbackEvent.client_event_id == payload.client_event_id,
            )
        )
        if existing is not None and existing.payload_hash == digest:
            return existing
        raise FeedbackIdempotencyConflict(
            "client_event_id 已用于不同反馈事件"
        ) from exc
    return event
