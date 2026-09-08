"""效果图任务的幂等创建、租约、恢复与终态提交。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import DesignPlanVersion, EffectRenderJob, RenderedImage
from app.services import task_timeline_service


ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = (
    "completed",
    "failed",
    "dead_letter",
    "cancelled",
    "provider_unavailable",
)


class IdempotencyConflict(RuntimeError):
    """同一任务的幂等键指向了不同输入。"""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clear_owner(job: EffectRenderJob) -> None:
    job.worker_id = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def get_job_for_key(
    db: Session, *, task_id: int, idempotency_key: str
) -> EffectRenderJob | None:
    return db.scalar(
        select(EffectRenderJob).where(
            EffectRenderJob.task_id == task_id,
            EffectRenderJob.idempotency_key == idempotency_key,
        )
    )


def create_or_get_job(
    db: Session,
    *,
    task_id: int,
    plan_version_id: int,
    idempotency_key: str,
    request_digest: str,
    prompt_snapshot: str,
    prompt_digest: str,
    source_image_id: int | None,
    source_image_digest: str | None,
    max_attempts: int,
    execution_timeout_seconds: int,
    request_id: str | None = None,
    scene_id: int | None = None,
    scene_version_id: int | None = None,
    scene_version: int | None = None,
    scene_snapshot_json: dict | None = None,
    scene_digest: str | None = None,
) -> tuple[EffectRenderJob, bool]:
    existing = get_job_for_key(db, task_id=task_id, idempotency_key=idempotency_key)
    if existing is not None:
        if existing.request_digest != request_digest:
            raise IdempotencyConflict("Idempotency-Key 已用于不同的效果图输入")
        return existing, False

    now = datetime.now(timezone.utc)
    job = EffectRenderJob(
        task_id=task_id,
        plan_version_id=plan_version_id,
        scene_id=scene_id,
        scene_version_id=scene_version_id,
        scene_version=scene_version,
        scene_snapshot_json=scene_snapshot_json,
        scene_digest=scene_digest,
        source_image_id=source_image_id,
        source_image_digest=source_image_digest,
        prompt_snapshot=prompt_snapshot,
        prompt_digest=prompt_digest,
        request_digest=request_digest,
        idempotency_key=idempotency_key,
        request_id=request_id,
        status="queued",
        progress=0,
        attempt_count=0,
        max_attempts=max(1, max_attempts),
        execution_deadline_at=now + timedelta(seconds=execution_timeout_seconds),
    )
    db.add(job)
    try:
        db.flush()
        task_timeline_service.record_lifecycle_event(
            db,
            task_id=task_id,
            source_type="effect",
            source_id=job.id,
            state="queued",
            attempt=0,
        )
        db.commit()
        db.refresh(job)
        return job, True
    except IntegrityError:
        db.rollback()
        existing = get_job_for_key(db, task_id=task_id, idempotency_key=idempotency_key)
        if existing is None:
            raise
        if existing.request_digest != request_digest:
            raise IdempotencyConflict("Idempotency-Key 已用于不同的效果图输入")
        return existing, False


def latest_job_for_plan(
    db: Session,
    *,
    task_id: int,
    plan_version_id: int,
    scene_id: int,
    scene_version: int,
) -> EffectRenderJob | None:
    return db.scalars(
        select(EffectRenderJob)
        .where(
            EffectRenderJob.task_id == task_id,
            EffectRenderJob.plan_version_id == plan_version_id,
            EffectRenderJob.scene_id == scene_id,
            EffectRenderJob.scene_version == scene_version,
        )
        .order_by(EffectRenderJob.created_at.desc(), EffectRenderJob.id.desc())
        .limit(1)
    ).first()


def recover_expired_jobs(
    db: Session, *, now: datetime | None = None, retry_delay_seconds: int = 0
) -> None:
    current = now or datetime.now(timezone.utc)
    jobs = db.scalars(
        select(EffectRenderJob)
        .where(
            EffectRenderJob.status == "running",
            or_(
                EffectRenderJob.lease_expires_at < current,
                EffectRenderJob.execution_deadline_at <= current,
            ),
        )
        .with_for_update(skip_locked=True)
    ).all()
    for job in jobs:
        _clear_owner(job)
        if job.cancel_requested_at is not None:
            job.status = "cancelled"
            job.progress = 100
            job.completed_at = current
            lifecycle_state = "cancelled"
        elif job.attempt_count >= job.max_attempts or _as_utc(
            job.execution_deadline_at
        ) <= _as_utc(current):
            job.status = "dead_letter"
            job.progress = 100
            job.error_message = "效果图任务租约或执行期限已耗尽"
            job.dead_lettered_at = current
            job.completed_at = current
            lifecycle_state = "dead_letter"
        else:
            job.status = "queued"
            job.progress = 0
            job.error_message = "上次 Worker 租约过期，等待重试"
            job.next_retry_at = current + timedelta(seconds=retry_delay_seconds)
            lifecycle_state = "retry_scheduled"
        task_timeline_service.record_lifecycle_event(
            db,
            task_id=job.task_id,
            source_type="effect",
            source_id=job.id,
            state=lifecycle_state,
            attempt=job.attempt_count,
            occurred_at=current,
        )


def claim_next_job(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    retry_delay_seconds: int = 0,
    now: datetime | None = None,
) -> EffectRenderJob | None:
    current = now or datetime.now(timezone.utc)
    recover_expired_jobs(db, now=current, retry_delay_seconds=retry_delay_seconds)
    job = db.scalars(
        select(EffectRenderJob)
        .where(
            EffectRenderJob.status == "queued",
            or_(
                EffectRenderJob.next_retry_at.is_(None),
                EffectRenderJob.next_retry_at <= current,
            ),
            EffectRenderJob.execution_deadline_at > current,
        )
        .order_by(EffectRenderJob.created_at, EffectRenderJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        # 排队期间超过总截止时间也必须进入可观察终态。
        expired = db.scalars(
            select(EffectRenderJob)
            .where(
                EffectRenderJob.status == "queued",
                EffectRenderJob.execution_deadline_at <= current,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for item in expired:
            item.status = "dead_letter"
            item.progress = 100
            item.error_message = "效果图任务执行期限已耗尽"
            item.dead_lettered_at = current
            item.completed_at = current
            task_timeline_service.record_lifecycle_event(
                db,
                task_id=item.task_id,
                source_type="effect",
                source_id=item.id,
                state="dead_letter",
                attempt=item.attempt_count,
                occurred_at=current,
            )
        db.commit()
        return None
    job.status = "running"
    job.progress = 10
    job.attempt_count += 1
    job.worker_id = worker_id
    job.heartbeat_at = current
    job.lease_expires_at = min(
        current + timedelta(seconds=lease_seconds),
        _as_utc(job.execution_deadline_at),
    )
    job.next_retry_at = None
    job.started_at = job.started_at or current
    job.error_message = None
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=job.task_id,
        source_type="effect",
        source_id=job.id,
        state="claimed",
        attempt=job.attempt_count,
        occurred_at=current,
    )
    db.commit()
    db.refresh(job)
    return job


def _owned_job(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    worker_attempt: int,
    now: datetime,
) -> EffectRenderJob | None:
    job = db.scalar(
        select(EffectRenderJob)
        .where(EffectRenderJob.id == job_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        job is None
        or job.status != "running"
        or job.worker_id != worker_id
        or job.attempt_count != worker_attempt
        or job.cancel_requested_at is not None
        or job.lease_expires_at is None
        or _as_utc(job.lease_expires_at) <= _as_utc(now)
        or _as_utc(job.execution_deadline_at) <= _as_utc(now)
    ):
        db.rollback()
        return None
    return job


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
    job = _owned_job(
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


def mark_progress(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    worker_attempt: int,
    progress: int,
) -> bool:
    job = _owned_job(
        db,
        job_id=job_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=datetime.now(timezone.utc),
    )
    if job is None:
        return False
    job.progress = max(job.progress, min(progress, 95))
    db.commit()
    return True


def complete_job(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    worker_attempt: int,
    image_url: str,
    mode: str,
) -> bool:
    current = datetime.now(timezone.utc)
    job = _owned_job(
        db,
        job_id=job_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=current,
    )
    if job is None:
        return False
    plan = db.get(DesignPlanVersion, job.plan_version_id)
    if plan is None or plan.revision.task_id != job.task_id:
        db.rollback()
        return False
    rendered = RenderedImage(
        task_id=job.task_id,
        plan_version_id=job.plan_version_id,
        scene_version_id=job.scene_version_id,
        plan_id=plan.plan_key,
        prompt=job.prompt_snapshot,
        image_url=image_url,
        mode=mode,
    )
    db.add(rendered)
    db.flush()
    job.rendered_image_id = rendered.id
    job.output_url = image_url
    job.mode = mode
    job.status = "completed"
    job.progress = 100
    job.completed_at = current
    _clear_owner(job)
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=job.task_id,
        source_type="effect",
        source_id=job.id,
        state="completed",
        attempt=job.attempt_count,
        occurred_at=current,
    )
    db.commit()
    return True


def fail_job(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    worker_attempt: int,
    error_message: str,
    retryable: bool,
    retry_delay_seconds: int,
    terminal_status: str = "failed",
) -> bool:
    current = datetime.now(timezone.utc)
    job = _owned_job(
        db,
        job_id=job_id,
        worker_id=worker_id,
        worker_attempt=worker_attempt,
        now=current,
    )
    if job is None:
        return False
    _clear_owner(job)
    job.error_message = error_message
    if job.cancel_requested_at is not None:
        job.status = "cancelled"
        job.progress = 100
        job.completed_at = current
    elif retryable and job.attempt_count < job.max_attempts:
        next_retry = current + timedelta(seconds=retry_delay_seconds)
        if next_retry < _as_utc(job.execution_deadline_at):
            job.status = "queued"
            job.progress = 0
            job.next_retry_at = next_retry
        else:
            job.status = "dead_letter"
            job.progress = 100
            job.dead_lettered_at = current
            job.completed_at = current
    elif retryable:
        job.status = "dead_letter"
        job.progress = 100
        job.dead_lettered_at = current
        job.completed_at = current
    else:
        job.status = terminal_status
        job.progress = 100
        job.completed_at = current
    state = {
        "queued": "retry_scheduled",
        "provider_unavailable": "failed",
    }.get(job.status, job.status)
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=job.task_id,
        source_type="effect",
        source_id=job.id,
        state=state,
        attempt=job.attempt_count,
        occurred_at=current,
    )
    db.commit()
    return True


def cancel_job(db: Session, *, job: EffectRenderJob) -> EffectRenderJob:
    if job.status in TERMINAL_STATUSES:
        return job
    current = datetime.now(timezone.utc)
    job.cancel_requested_at = job.cancel_requested_at or current
    job.status = "cancelled"
    job.progress = 100
    job.completed_at = current
    _clear_owner(job)
    task_timeline_service.record_lifecycle_event(
        db,
        task_id=job.task_id,
        source_type="effect",
        source_id=job.id,
        state="cancelled",
        attempt=job.attempt_count,
        occurred_at=current,
    )
    db.commit()
    db.refresh(job)
    return job
