"""Blender 渲染作业的持久化、归属查询与 Worker 租约。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    BlenderRenderJob,
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    RenderedImage,
)
from app.services import task_timeline_service


ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed", "dead_letter", "cancelled")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clear_owner(job: BlenderRenderJob) -> None:
    job.worker_id = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def _task_id_for_job(db: Session, job: BlenderRenderJob) -> int | None:
    return db.scalar(
        select(DesignRevision.task_id)
        .join(DesignPlanVersion, DesignPlanVersion.revision_id == DesignRevision.id)
        .join(DesignScene, DesignScene.plan_version_id == DesignPlanVersion.id)
        .where(DesignScene.id == job.scene_id)
    )


def _record_timeline(
    db: Session,
    *,
    job: BlenderRenderJob,
    state: str,
    occurred_at: datetime,
) -> None:
    task_id = _task_id_for_job(db, job)
    if task_id is None:
        return
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=task_id,
        source_type="blender",
        source_id=job.id,
        state=state,
        attempt=job.attempt,
        occurred_at=occurred_at,
    )


def _mark_dead_letter(
    job: BlenderRenderJob,
    *,
    now: datetime,
    message: str,
    error_code: str = "render_deadline_or_attempts_exhausted",
) -> None:
    job.status = "dead_letter"
    job.progress = 100
    job.error_message = message[:500]
    job.error_code = error_code
    job.dead_lettered_at = now
    job.completed_at = now
    job.next_retry_at = None
    _clear_owner(job)


def _owned_active_job(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    worker_attempt: int,
    now: datetime,
) -> BlenderRenderJob | None:
    job = db.scalar(
        select(BlenderRenderJob)
        .where(BlenderRenderJob.id == job_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        job is None
        or job.status != "running"
        or job.worker_id != worker_id
        or job.attempt != worker_attempt
        or job.cancel_requested_at is not None
        or job.lease_expires_at is None
        or _as_utc(job.lease_expires_at) <= _as_utc(now)
        or _as_utc(job.execution_deadline_at) <= _as_utc(now)
    ):
        db.rollback()
        return None
    return job


def get_existing_job(
    db: Session,
    *,
    scene_version_id: int,
    profile: str,
) -> BlenderRenderJob | None:
    return db.scalar(
        select(BlenderRenderJob).where(
            BlenderRenderJob.scene_version_id == scene_version_id,
            BlenderRenderJob.profile == profile,
        )
    )


def create_or_get_job(
    db: Session,
    *,
    scene: DesignScene,
    version: DesignSceneVersion,
    profile: str,
    max_attempts: int = 2,
    execution_timeout_seconds: int = 1800,
    request_id: str | None = None,
) -> tuple[BlenderRenderJob, bool]:
    existing = get_existing_job(
        db,
        scene_version_id=version.id,
        profile=profile,
    )
    if existing is not None:
        return existing, False
    now = datetime.now(timezone.utc)
    job = BlenderRenderJob(
        request_id=request_id,
        scene_id=scene.id,
        scene_version_id=version.id,
        scene_version=version.version,
        profile=profile,
        status="queued",
        progress=0,
        attempt=0,
        max_attempts=max(1, max_attempts),
        execution_deadline_at=now + timedelta(seconds=execution_timeout_seconds),
    )
    db.add(job)
    try:
        db.flush()
        _record_timeline(db, job=job, state="queued", occurred_at=now)
        db.commit()
        db.refresh(job)
        return job, True
    except IntegrityError:
        db.rollback()
        existing = get_existing_job(
            db,
            scene_version_id=version.id,
            profile=profile,
        )
        if existing is None:
            raise
        return existing, False


def requeue_failed_job(
    db: Session,
    *,
    job: BlenderRenderJob,
    now: datetime | None = None,
) -> BlenderRenderJob:
    if job.status != "failed":
        return job
    current = now or datetime.now(timezone.utc)
    if job.attempt >= job.max_attempts or _as_utc(job.execution_deadline_at) <= _as_utc(
        current
    ):
        _mark_dead_letter(
            job,
            now=current,
            message="Blender 渲染任务执行期限或重试次数已耗尽",
        )
        _record_timeline(db, job=job, state="dead_letter", occurred_at=current)
        db.commit()
        db.refresh(job)
        return job
    job.status = "queued"
    job.progress = 0
    _clear_owner(job)
    job.output_url = None
    job.error_message = None
    job.error_code = None
    job.next_retry_at = current
    job.cancel_requested_at = None
    job.completed_at = None
    _record_timeline(db, job=job, state="retry_scheduled", occurred_at=current)
    db.commit()
    db.refresh(job)
    return job


def get_scene_job(
    db: Session,
    *,
    scene_id: int,
    job_id: int,
    for_update: bool = False,
) -> BlenderRenderJob | None:
    statement = select(BlenderRenderJob).where(
        BlenderRenderJob.id == job_id,
        BlenderRenderJob.scene_id == scene_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def recover_expired_jobs(
    db: Session,
    *,
    max_attempts: int | None = None,
    retry_delay_seconds: int = 0,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(timezone.utc)
    jobs = db.scalars(
        select(BlenderRenderJob)
        .where(
            BlenderRenderJob.status == "running",
            or_(
                BlenderRenderJob.lease_expires_at.is_(None),
                BlenderRenderJob.lease_expires_at < current,
                BlenderRenderJob.execution_deadline_at <= current,
            ),
        )
        .with_for_update(skip_locked=True)
    ).all()
    for job in jobs:
        _clear_owner(job)
        allowed_attempts = job.max_attempts or max_attempts or 1
        if job.cancel_requested_at is not None:
            job.status = "cancelled"
            job.progress = 100
            job.completed_at = current
            lifecycle_state = "cancelled"
        elif job.attempt >= allowed_attempts or _as_utc(
            job.execution_deadline_at
        ) <= _as_utc(current):
            _mark_dead_letter(
                job,
                now=current,
                message="Blender 渲染任务租约或执行期限已耗尽",
            )
            lifecycle_state = "dead_letter"
        else:
            job.status = "queued"
            job.progress = 0
            job.error_message = "上次 Worker 租约过期，等待重试"
            job.next_retry_at = current + timedelta(seconds=retry_delay_seconds)
            lifecycle_state = "retry_scheduled"
        _record_timeline(
            db,
            job=job,
            state=lifecycle_state,
            occurred_at=current,
        )


def claim_next_job(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int | None = None,
    retry_delay_seconds: int = 0,
    now: datetime | None = None,
) -> BlenderRenderJob | None:
    current = now or datetime.now(timezone.utc)
    recover_expired_jobs(
        db,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        now=current,
    )
    cancelled_queued = db.scalars(
        select(BlenderRenderJob)
        .where(
            BlenderRenderJob.status == "queued",
            BlenderRenderJob.cancel_requested_at.is_not(None),
        )
        .with_for_update(skip_locked=True)
    ).all()
    for cancelled in cancelled_queued:
        cancelled.status = "cancelled"
        cancelled.progress = 100
        cancelled.completed_at = current
        cancelled.next_retry_at = None
        _clear_owner(cancelled)
        _record_timeline(
            db,
            job=cancelled,
            state="cancelled",
            occurred_at=current,
        )
    expired_queued = db.scalars(
        select(BlenderRenderJob)
        .where(
            BlenderRenderJob.status == "queued",
            or_(
                BlenderRenderJob.execution_deadline_at <= current,
                BlenderRenderJob.attempt >= BlenderRenderJob.max_attempts,
            ),
        )
        .with_for_update(skip_locked=True)
    ).all()
    for expired in expired_queued:
        _mark_dead_letter(
            expired,
            now=current,
            message="Blender 渲染任务执行期限或重试次数已耗尽",
        )
        _record_timeline(
            db,
            job=expired,
            state="dead_letter",
            occurred_at=current,
        )
    job = db.scalars(
        select(BlenderRenderJob)
        .where(
            BlenderRenderJob.status == "queued",
            BlenderRenderJob.cancel_requested_at.is_(None),
            BlenderRenderJob.attempt < BlenderRenderJob.max_attempts,
            BlenderRenderJob.execution_deadline_at > current,
            or_(
                BlenderRenderJob.next_retry_at.is_(None),
                BlenderRenderJob.next_retry_at <= current,
            ),
        )
        .order_by(BlenderRenderJob.created_at, BlenderRenderJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        db.commit()
        return None
    job.status = "running"
    job.progress = 10
    job.attempt += 1
    job.worker_id = worker_id
    job.started_at = job.started_at or current
    job.heartbeat_at = current
    job.completed_at = None
    job.error_message = None
    job.error_code = None
    job.next_retry_at = None
    job.lease_expires_at = min(
        current + timedelta(seconds=lease_seconds),
        _as_utc(job.execution_deadline_at),
    )
    _record_timeline(db, job=job, state="claimed", occurred_at=current)
    db.commit()
    db.refresh(job)
    return job


def mark_progress(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    worker_attempt: int,
    progress: int,
    now: datetime | None = None,
) -> bool:
    job = _owned_active_job(
        db,
        job_id=job_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=now or datetime.now(timezone.utc),
    )
    if job is None:
        return False
    job.progress = max(job.progress, min(progress, 95))
    db.commit()
    return True


def renew_lease(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    worker_attempt: int,
    lease_seconds: int,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    job = _owned_active_job(
        db,
        job_id=job_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=current,
    )
    if job is None:
        return False
    job.heartbeat_at = current
    job.lease_expires_at = min(
        current + timedelta(seconds=lease_seconds),
        _as_utc(job.execution_deadline_at),
    )
    db.commit()
    return True


def mark_completed(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    worker_attempt: int,
    output_url: str,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    job = _owned_active_job(
        db,
        job_id=job_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=current,
    )
    if job is None:
        return False
    job.status = "completed"
    job.progress = 100
    job.output_url = output_url
    job.error_message = None
    job.lease_expires_at = None
    job.completed_at = current
    _clear_owner(job)

    scene = db.get(DesignScene, job.scene_id)
    plan_version = db.get(DesignPlanVersion, scene.plan_version_id) if scene else None
    revision = (
        db.get(DesignRevision, plan_version.revision_id) if plan_version else None
    )
    if plan_version and revision:
        db.add(
            RenderedImage(
                task_id=revision.task_id,
                plan_version_id=plan_version.id,
                plan_id=plan_version.plan_key,
                prompt=(
                    f"SceneDocument scene={job.scene_id} version={job.scene_version}"
                ),
                image_url=output_url,
                mode="blender_cycles" if job.profile == "final" else "blender_eevee",
            )
        )
    _record_timeline(db, job=job, state="completed", occurred_at=current)
    db.commit()
    return True


def mark_failed(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    worker_attempt: int,
    error_message: str,
    error_code: str = "render_failed",
    retryable: bool = False,
    retry_delay_seconds: int = 0,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    job = _owned_active_job(
        db,
        job_id=job_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=current,
    )
    if job is None:
        return False
    _clear_owner(job)
    job.error_message = error_message[:500]
    job.error_code = error_code
    if retryable and job.attempt < job.max_attempts:
        next_retry = current + timedelta(seconds=retry_delay_seconds)
        if next_retry < _as_utc(job.execution_deadline_at):
            job.status = "queued"
            job.progress = 0
            job.next_retry_at = next_retry
        else:
            _mark_dead_letter(
                job,
                now=current,
                message=error_message,
                error_code="render_retry_exhausted",
            )
    elif retryable:
        _mark_dead_letter(
            job,
            now=current,
            message=error_message,
            error_code="render_retry_exhausted",
        )
    else:
        job.status = "failed"
        job.progress = 100
        job.completed_at = current
    state = "retry_scheduled" if job.status == "queued" else job.status
    _record_timeline(db, job=job, state=state, occurred_at=current)
    db.commit()
    return True


def cancel_job(
    db: Session,
    *,
    job: BlenderRenderJob,
    now: datetime | None = None,
) -> BlenderRenderJob:
    if job.status in TERMINAL_STATUSES:
        return job
    current = now or datetime.now(timezone.utc)
    job.cancel_requested_at = job.cancel_requested_at or current
    job.status = "cancelled"
    job.progress = 100
    job.completed_at = current
    job.next_retry_at = None
    _clear_owner(job)
    _record_timeline(db, job=job, state="cancelled", occurred_at=current)
    db.commit()
    db.refresh(job)
    return job
