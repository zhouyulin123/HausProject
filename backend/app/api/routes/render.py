"""效果图异步任务接口；实际 SD 调用只允许发生在独立 Worker。"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_owned_design_task
from app.core.config import settings
from app.core.request_context import normalize_request_id
from app.db.database import get_db
from app.db.models import DesignSceneVersion, DesignTask, EffectRenderJob, UploadedImage
from app.schemas.effect_render import EffectRenderJobResponse, EffectRenderRequest
from app.schemas.scenes import SceneDocument
from app.services import effect_render_job_service, scene_service


router = APIRouter()

_STYLE_MAP = {
    "奶油": "cream style, soft beige and off-white tones",
    "原木": "natural wood, light oak furniture, warm wood tones",
    "现代简约": "modern minimalist, clean lines",
    "简约": "modern minimalist, clean lines",
    "轻奢": "light luxury, marble and brass accents, elegant",
    "侘寂": "japandi wabi-sabi style, muji, textured plaster",
    "日式": "japandi style, muji, natural materials",
    "北欧": "scandinavian nordic style, bright and airy",
    "中古": "mid-century modern style, vintage furniture",
    "法式": "french vintage style, molding, arched details",
    "工业": "industrial loft style, exposed brick and metal",
}

_ROOM_MAP = {
    "客厅": "living room",
    "卧室": "bedroom",
    "厨房": "kitchen",
    "餐厅": "dining room",
    "书房": "study room, home office",
    "儿童房": "children's room",
    "卫生间": "bathroom",
    "阳台": "balcony",
    "衣帽间": "walk-in closet",
    "玄关": "entryway",
    "全屋": "living room",
}


def build_effect_prompt(style: str, room_type: str) -> str:
    style_en = next(
        (value for key, value in _STYLE_MAP.items() if key in style),
        "modern cozy interior",
    )
    room_en = _ROOM_MAP.get(room_type, "living room")
    return f"a {room_en}, {style_en}, well decorated, furnished"


def _room_type_from_task(task: DesignTask) -> str:
    requirement = task.confirmed_requirement_json or {}
    rooms = requirement.get("rooms") or []
    return rooms[0] if rooms else "客厅"


def _digest_json(value: object) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{sha256(canonical).hexdigest()}"


def _source_image_snapshot(
    db: Session, *, task_id: int
) -> tuple[int | None, str | None]:
    image = db.scalars(
        select(UploadedImage)
        .where(
            UploadedImage.task_id == task_id,
            UploadedImage.file_url.is_not(None),
        )
        .order_by(UploadedImage.id)
        .limit(1)
    ).first()
    if image is None:
        return None, None
    digest = image.content_digest
    if not digest and image.file_url:
        path = Path(settings.upload_dir) / Path(image.file_url).name
        if path.is_file():
            digest = f"sha256:{sha256(path.read_bytes()).hexdigest()}"
    return image.id, digest


def _response(job: EffectRenderJob) -> EffectRenderJobResponse:
    return EffectRenderJobResponse(
        job_id=job.id,
        request_id=job.request_id,
        task_id=job.task_id,
        plan_version_id=job.plan_version_id,
        scene_id=job.scene_id,
        scene_version_id=job.scene_version_id,
        scene_version=job.scene_version,
        scene_digest=job.scene_digest,
        status=job.status,
        progress=job.progress,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        image_url=job.output_url,
        mode=job.mode,
        error_message=job.error_message,
        cancel_requested_at=job.cancel_requested_at,
        next_retry_at=job.next_retry_at,
        execution_deadline_at=job.execution_deadline_at,
        dead_lettered_at=job.dead_lettered_at,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.post("", response_model=EffectRenderJobResponse, status_code=202)
def queue_effect_render(
    payload: EffectRenderRequest,
    request: Request,
    x_session_id: SessionIdHeader,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=100,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db, session_id=x_session_id, task_id=payload.task_id
    )
    existing = effect_render_job_service.get_job_for_key(
        db, task_id=task.id, idempotency_key=idempotency_key
    )
    if existing is not None and existing.plan_version_id != payload.plan_version_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "idempotency_conflict",
                "message": "Idempotency-Key 已用于不同的效果图输入",
            },
        )

    plan_version = scene_service.get_owned_plan_version(
        db,
        session_id=x_session_id,
        plan_version_id=payload.plan_version_id,
    )
    if plan_version is None or plan_version.revision.task_id != payload.task_id:
        raise HTTPException(status_code=404, detail="方案版本不存在")

    scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=payload.scene_id,
    )
    scene_version = db.scalar(
        select(DesignSceneVersion).where(
            DesignSceneVersion.scene_id == payload.scene_id,
            DesignSceneVersion.version == payload.scene_version,
        )
    )
    if (
        scene is None
        or scene.plan_version_id != plan_version.id
        or scene_version is None
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "scene_snapshot_not_found",
                "message": "指定场景版本不存在或不属于当前方案",
            },
        )
    try:
        scene_snapshot = SceneDocument.model_validate(
            scene_version.scene_json
        ).model_dump(by_alias=True, mode="json")
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scene_snapshot_invalid",
                "message": "指定场景版本不是有效的 SceneDocument",
            },
        ) from exc
    scene_digest = _digest_json(scene_snapshot)

    plan = plan_version.plan_json or {}
    prompt = build_effect_prompt(
        str(plan.get("style") or plan_version.style or ""),
        _room_type_from_task(task),
    )
    source_image_id, source_image_digest = _source_image_snapshot(db, task_id=task.id)
    prompt_digest = _digest_json({"prompt": prompt, "version": 1})
    request_digest = _digest_json(
        {
            "schema_version": 2,
            "task_id": task.id,
            "plan_version_id": plan_version.id,
            "plan_snapshot": plan_version.plan_json,
            "prompt_digest": prompt_digest,
            "source_image_id": source_image_id,
            "source_image_digest": source_image_digest,
            "scene_id": scene.id,
            "scene_version_id": scene_version.id,
            "scene_version": scene_version.version,
            "scene_digest": scene_digest,
        }
    )
    try:
        job, _ = effect_render_job_service.create_or_get_job(
            db,
            task_id=task.id,
            plan_version_id=plan_version.id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            prompt_snapshot=prompt,
            prompt_digest=prompt_digest,
            source_image_id=source_image_id,
            source_image_digest=source_image_digest,
            scene_id=scene.id,
            scene_version_id=scene_version.id,
            scene_version=scene_version.version,
            scene_snapshot_json=scene_snapshot,
            scene_digest=scene_digest,
            max_attempts=settings.effect_render_worker_max_attempts,
            execution_timeout_seconds=(
                settings.effect_render_worker_execution_timeout_seconds
            ),
            request_id=getattr(request.state, "request_id", None)
            or normalize_request_id(request.headers.get("X-Request-ID")),
        )
    except effect_render_job_service.IdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "message": str(exc)},
        ) from exc
    return _response(job)


@router.get("", response_model=EffectRenderJobResponse)
def get_latest_effect_render(
    plan_version_id: Annotated[int, Query(ge=1)],
    scene_id: Annotated[int, Query(ge=1)],
    scene_version: Annotated[int, Query(ge=1)],
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    plan = scene_service.get_owned_plan_version(
        db, session_id=x_session_id, plan_version_id=plan_version_id
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="方案版本不存在")
    scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=scene_id,
    )
    if scene is None or scene.plan_version_id != plan.id:
        raise HTTPException(status_code=404, detail="场景不存在")
    job = effect_render_job_service.latest_job_for_plan(
        db,
        task_id=plan.revision.task_id,
        plan_version_id=plan.id,
        scene_id=scene_id,
        scene_version=scene_version,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="效果图任务不存在")
    return _response(job)


def _owned_job(db: Session, *, session_id: str, job_id: int) -> EffectRenderJob:
    job = db.get(EffectRenderJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="效果图任务不存在")
    require_owned_design_task(db, session_id=session_id, task_id=job.task_id)
    return job


@router.get("/{job_id}", response_model=EffectRenderJobResponse)
def get_effect_render(
    job_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    return _response(_owned_job(db, session_id=x_session_id, job_id=job_id))


@router.post("/{job_id}/cancel", response_model=EffectRenderJobResponse)
def cancel_effect_render(
    job_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    job = _owned_job(db, session_id=x_session_id, job_id=job_id)
    return _response(effect_render_job_service.cancel_job(db, job=job))
