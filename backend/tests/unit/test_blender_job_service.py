from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import (
    BlenderRenderJob,
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    DesignTask,
    RenderedImage,
    TaskExecutionEvent,
)
from app.services import blender_job_service


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _job(
    *,
    status: str = "queued",
    attempt: int = 0,
    scene_version_id: int = 1,
):
    return BlenderRenderJob(
        scene_id=1,
        scene_version_id=scene_version_id,
        scene_version=1,
        profile="preview",
        status=status,
        progress=0,
        attempt=attempt,
        max_attempts=2,
        execution_deadline_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_claim_next_job_sets_worker_lease_and_prevents_second_claim():
    engine, factory = _database()
    try:
        with factory() as db:
            db.add(_job())
            db.commit()

            claimed = blender_job_service.claim_next_job(
                db,
                worker_id="worker-a",
                lease_seconds=300,
                max_attempts=2,
            )
            second = blender_job_service.claim_next_job(
                db,
                worker_id="worker-b",
                lease_seconds=300,
                max_attempts=2,
            )

            assert claimed is not None
            assert claimed.status == "running"
            assert claimed.worker_id == "worker-a"
            assert claimed.attempt == 1
            assert claimed.lease_expires_at is not None
            assert second is None
    finally:
        engine.dispose()


def test_expired_job_retries_once_then_becomes_failed():
    engine, factory = _database()
    try:
        with factory() as db:
            job = _job(status="running", attempt=1)
            job.worker_id = "dead-worker"
            job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            db.add(job)
            db.commit()

            retried = blender_job_service.claim_next_job(
                db,
                worker_id="worker-b",
                lease_seconds=300,
                max_attempts=2,
            )
            assert retried is not None
            assert retried.attempt == 2

            retried.lease_expires_at = datetime.now(timezone.utc) - timedelta(
                seconds=10
            )
            db.commit()
            none_left = blender_job_service.claim_next_job(
                db,
                worker_id="worker-c",
                lease_seconds=300,
                max_attempts=2,
            )

            assert none_left is None
            db.refresh(retried)
            assert retried.status == "dead_letter"
            assert retried.progress == 100
            assert retried.dead_lettered_at is not None
    finally:
        engine.dispose()


def test_claim_only_due_jobs_and_dead_letters_queued_deadline_or_exhaustion():
    engine, factory = _database()
    now = datetime(2026, 9, 8, 8, tzinfo=timezone.utc)
    try:
        with factory() as db:
            future = _job()
            future.next_retry_at = now + timedelta(minutes=1)
            future.execution_deadline_at = now + timedelta(hours=1)
            exhausted = _job(attempt=2, scene_version_id=2)
            exhausted.execution_deadline_at = now + timedelta(hours=1)
            expired = _job(scene_version_id=3)
            expired.execution_deadline_at = now
            db.add_all([future, exhausted, expired])
            db.commit()

            claimed = blender_job_service.claim_next_job(
                db,
                worker_id="worker-a",
                lease_seconds=300,
                max_attempts=5,
                now=now,
            )

            assert claimed is None
            db.refresh(future)
            db.refresh(exhausted)
            db.refresh(expired)
            assert future.status == "queued"
            assert exhausted.status == "dead_letter"
            assert expired.status == "dead_letter"
            assert blender_job_service._as_utc(exhausted.dead_lettered_at) == now
            assert blender_job_service._as_utc(expired.dead_lettered_at) == now
    finally:
        engine.dispose()


def test_transient_failure_requeues_before_deadline_then_exhaustion_dead_letters():
    engine, factory = _database()
    now = datetime(2026, 9, 8, 8, tzinfo=timezone.utc)
    try:
        with factory() as db:
            job = _job(status="running", attempt=1)
            job.worker_id = "worker-a"
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(minutes=5)
            job.execution_deadline_at = now + timedelta(minutes=10)
            db.add(job)
            db.commit()

            assert (
                blender_job_service.mark_failed(
                    db,
                    job_id=job.id,
                    worker_id="worker-a",
                    worker_attempt=1,
                    error_message="临时 IO 错误",
                    error_code="render_transient",
                    retryable=True,
                    retry_delay_seconds=20,
                    now=now,
                )
                is True
            )
            db.refresh(job)
            assert job.status == "queued"
            assert blender_job_service._as_utc(job.next_retry_at) == (
                now + timedelta(seconds=20)
            )
            assert job.error_code == "render_transient"

            job.status = "running"
            job.attempt = 2
            job.worker_id = "worker-b"
            job.lease_expires_at = now + timedelta(minutes=5)
            job.heartbeat_at = now
            db.commit()
            assert (
                blender_job_service.mark_failed(
                    db,
                    job_id=job.id,
                    worker_id="worker-b",
                    worker_attempt=2,
                    error_message="再次失败",
                    error_code="render_transient",
                    retryable=True,
                    retry_delay_seconds=40,
                    now=now,
                )
                is True
            )
            db.refresh(job)
            assert job.status == "dead_letter"
            assert job.error_code == "render_retry_exhausted"
            assert blender_job_service._as_utc(job.dead_lettered_at) == now
    finally:
        engine.dispose()


def test_manual_requeue_preserves_attempt_budget_and_cannot_revive_dead_letter():
    engine, factory = _database()
    now = datetime(2026, 9, 8, 8, tzinfo=timezone.utc)
    try:
        with factory() as db:
            job = _job(status="failed", attempt=1)
            job.execution_deadline_at = now + timedelta(minutes=10)
            db.add(job)
            db.commit()

            original_deadline = job.execution_deadline_at
            retried = blender_job_service.requeue_failed_job(db, job=job, now=now)
            assert retried.status == "queued"
            assert retried.attempt == 1
            assert blender_job_service._as_utc(retried.execution_deadline_at) == (
                blender_job_service._as_utc(original_deadline)
            )

            retried.status = "failed"
            retried.attempt = retried.max_attempts
            db.commit()
            exhausted = blender_job_service.requeue_failed_job(db, job=retried, now=now)
            assert exhausted.status == "dead_letter"
            assert exhausted.attempt == exhausted.max_attempts

            assert (
                blender_job_service.requeue_failed_job(
                    db,
                    job=exhausted,
                    now=now + timedelta(seconds=1),
                ).status
                == "dead_letter"
            )
    finally:
        engine.dispose()


def test_heartbeat_is_capped_by_deadline_and_cancel_blocks_stale_completion():
    engine, factory = _database()
    now = datetime(2026, 9, 8, 8, tzinfo=timezone.utc)
    try:
        with factory() as db:
            job = _job(status="running", attempt=1)
            job.worker_id = "worker-a"
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=30)
            job.execution_deadline_at = now + timedelta(seconds=45)
            db.add(job)
            db.commit()

            assert (
                blender_job_service.renew_lease(
                    db,
                    job_id=job.id,
                    worker_id="worker-a",
                    worker_attempt=1,
                    lease_seconds=300,
                    now=now + timedelta(seconds=10),
                )
                is True
            )
            db.refresh(job)
            assert blender_job_service._as_utc(job.heartbeat_at) == (
                now + timedelta(seconds=10)
            )
            assert blender_job_service._as_utc(job.lease_expires_at) == (
                blender_job_service._as_utc(job.execution_deadline_at)
            )

            cancelled = blender_job_service.cancel_job(db, job=job, now=now)
            assert cancelled.status == "cancelled"
            assert blender_job_service._as_utc(cancelled.cancel_requested_at) == now
            assert (
                blender_job_service.mark_completed(
                    db,
                    job_id=job.id,
                    worker_id="worker-a",
                    worker_attempt=1,
                    output_url="/uploads/late.png",
                    now=now + timedelta(seconds=1),
                )
                is False
            )
    finally:
        engine.dispose()


def test_only_owning_worker_can_complete_claimed_job():
    engine, factory = _database()
    try:
        with factory() as db:
            db.add(_job())
            db.commit()
            claimed = blender_job_service.claim_next_job(
                db,
                worker_id="worker-a",
                lease_seconds=300,
                max_attempts=2,
            )
            assert claimed is not None

            blender_job_service.mark_completed(
                db,
                job_id=claimed.id,
                worker_id="worker-b",
                worker_attempt=claimed.attempt,
                output_url="/uploads/wrong.png",
            )
            db.refresh(claimed)
            assert claimed.status == "running"

            blender_job_service.mark_completed(
                db,
                job_id=claimed.id,
                worker_id="worker-a",
                worker_attempt=claimed.attempt,
                output_url="/uploads/blender_renders/right.png",
            )
            db.refresh(claimed)
            assert claimed.status == "completed"
            assert claimed.output_url.endswith("right.png")
    finally:
        engine.dispose()


def test_stale_attempt_cannot_publish_and_current_attempt_binds_plan_version():
    engine, factory = _database()
    try:
        with factory() as db:
            task = DesignTask(status="completed", progress=100)
            db.add(task)
            db.flush()
            revision = DesignRevision(
                task_id=task.id,
                version=1,
                requirement_snapshot={},
                generator="llm",
                status="completed",
            )
            db.add(revision)
            db.flush()
            plan = DesignPlanVersion(
                revision_id=revision.id,
                plan_key="plan-a",
                plan_name="方案 A",
                style="现代简约",
                plan_json={},
            )
            db.add(plan)
            db.flush()
            scene = DesignScene(plan_version_id=plan.id, current_version=1)
            db.add(scene)
            db.flush()
            scene_version = DesignSceneVersion(
                scene_id=scene.id,
                version=1,
                scene_json={"schemaVersion": "1.0", "items": []},
                validation_json={"valid": True, "issues": []},
                source="auto_layout",
            )
            db.add(scene_version)
            db.flush()
            db.add(
                BlenderRenderJob(
                    scene_id=scene.id,
                    scene_version_id=scene_version.id,
                    scene_version=1,
                    profile="final",
                    status="queued",
                    progress=0,
                    attempt=0,
                    max_attempts=3,
                    execution_deadline_at=(
                        datetime.now(timezone.utc) + timedelta(hours=1)
                    ),
                )
            )
            db.commit()

            first = blender_job_service.claim_next_job(
                db,
                worker_id="worker-shared",
                lease_seconds=300,
                max_attempts=3,
            )
            assert first is not None
            first_attempt = first.attempt
            first.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()

            assert (
                blender_job_service.mark_completed(
                    db,
                    job_id=first.id,
                    worker_id="worker-shared",
                    worker_attempt=first_attempt,
                    output_url="/uploads/blender_renders/expired.png",
                )
                is False
            )

            second = blender_job_service.claim_next_job(
                db,
                worker_id="worker-shared",
                lease_seconds=300,
                max_attempts=3,
            )
            assert second is not None
            assert second.attempt == first_attempt + 1

            assert (
                blender_job_service.mark_progress(
                    db,
                    job_id=second.id,
                    worker_id="worker-shared",
                    worker_attempt=first_attempt,
                    progress=90,
                )
                is False
            )
            assert (
                blender_job_service.mark_completed(
                    db,
                    job_id=second.id,
                    worker_id="worker-shared",
                    worker_attempt=first_attempt,
                    output_url="/uploads/blender_renders/stale.png",
                )
                is False
            )
            assert db.query(RenderedImage).count() == 0

            assert (
                blender_job_service.mark_completed(
                    db,
                    job_id=second.id,
                    worker_id="worker-shared",
                    worker_attempt=second.attempt,
                    output_url="/uploads/blender_renders/current.png",
                )
                is True
            )
            rendered = db.query(RenderedImage).one()
            assert rendered.plan_version_id == plan.id
            assert rendered.task_id == task.id
            events = db.query(TaskExecutionEvent).order_by(TaskExecutionEvent.id).all()
            assert [event.event_code for event in events] == [
                "blender.claimed",
                "blender.retry_scheduled",
                "blender.claimed",
                "blender.completed",
            ]
            assert not any(
                event.event_key.endswith(f"a{first_attempt}:completed")
                for event in events
            )
            assert events[-1].billing_status == "unknown"
    finally:
        engine.dispose()
