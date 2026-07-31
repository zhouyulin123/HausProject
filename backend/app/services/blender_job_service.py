"""Blender 渲染作业的持久化、归属查询与 Worker 租约。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
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


ACTIVE_STATUSES = ("queued", "running")


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
) -> tuple[BlenderRenderJob, bool]:
    existing = get_existing_job(
        db,
        scene_version_id=version.id,
        profile=profile,
    )
    if existing is not None:
        return existing, False
    job = BlenderRenderJob(
        scene_id=scene.id,
        scene_version_id=version.id,
        scene_version=version.version,
        profile=profile,
        status="queued",
        progress=0,
        attempt=0,
    )
    db.add(job)
    try:
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
) -> BlenderRenderJob:
    if job.status != "failed":
        return job
    job.status = "queued"
    job.progress = 0
    job.worker_id = None
    job.lease_expires_at = None
    job.output_url = None
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    db.commit()
    db.refresh(job)
    return job


def get_scene_job(
    db: Session,
    *,
    scene_id: int,
    job_id: int,
) -> BlenderRenderJob | None:
    return db.scalar(
        select(BlenderRenderJob).where(
            BlenderRenderJob.id == job_id,
            BlenderRenderJob.scene_id == scene_id,
        )
    )


def recover_expired_jobs(
    db: Session,
    *,
    max_attempts: int,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(timezone.utc)
    jobs = db.scalars(
        select(BlenderRenderJob)
        .where(
            BlenderRenderJob.status == "running",
            BlenderRenderJob.lease_expires_at < current,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for job in jobs:
        job.worker_id = None
        job.lease_expires_at = None
        if job.attempt < max_attempts:
            job.status = "queued"
            job.progress = 0
            job.error_message = "上次 Worker 租约过期，等待重试"
        else:
            job.status = "failed"
            job.progress = 100
            job.error_message = "渲染任务多次超时"
            job.completed_at = current


def claim_next_job(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int,
) -> BlenderRenderJob | None:
    current = datetime.now(timezone.utc)
    recover_expired_jobs(
        db,
        max_attempts=max_attempts,
        now=current,
    )
    job = db.scalars(
        select(BlenderRenderJob)
        .where(BlenderRenderJob.status == "queued")
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
    job.started_at = current
    job.completed_at = None
    job.error_message = None
    job.lease_expires_at = current + timedelta(seconds=lease_seconds)
    db.commit()
    db.refresh(job)
    return job


def mark_progress(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    progress: int,
) -> None:
    job = db.get(BlenderRenderJob, job_id)
    if job is None or job.status != "running" or job.worker_id != worker_id:
        return
    job.progress = max(job.progress, min(progress, 95))
    db.commit()


def mark_completed(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    output_url: str,
) -> None:
    job = db.get(BlenderRenderJob, job_id)
    if job is None or job.status != "running" or job.worker_id != worker_id:
        return
    job.status = "completed"
    job.progress = 100
    job.output_url = output_url
    job.error_message = None
    job.lease_expires_at = None
    job.completed_at = datetime.now(timezone.utc)

    scene = db.get(DesignScene, job.scene_id)
    plan_version = (
        db.get(DesignPlanVersion, scene.plan_version_id) if scene else None
    )
    revision = (
        db.get(DesignRevision, plan_version.revision_id)
        if plan_version
        else None
    )
    if plan_version and revision:
        db.add(
            RenderedImage(
                task_id=revision.task_id,
                plan_id=plan_version.plan_key,
                prompt=(
                    f"SceneDocument scene={job.scene_id} "
                    f"version={job.scene_version}"
                ),
                image_url=output_url,
                mode="blender_cycles"
                if job.profile == "final"
                else "blender_eevee",
            )
        )
    db.commit()


def mark_failed(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    error_message: str,
) -> None:
    job = db.get(BlenderRenderJob, job_id)
    if job is None or job.status != "running" or job.worker_id != worker_id:
        return
    job.status = "failed"
    job.progress = 100
    job.error_message = error_message[:500]
    job.lease_expires_at = None
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
