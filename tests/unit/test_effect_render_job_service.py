from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import (
    DesignPlanVersion,
    DesignRevision,
    DesignTask,
    EffectRenderJob,
    RenderedImage,
    TaskExecutionEvent,
)
from app.services import effect_render_job_service


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _persist_plan(db):
    task = DesignTask(status="completed", progress=100)
    db.add(task)
    db.flush()
    revision = DesignRevision(
        task_id=task.id,
        version=1,
        requirement_snapshot={},
        generator="test",
        status="completed",
    )
    db.add(revision)
    db.flush()
    plan = DesignPlanVersion(
        revision_id=revision.id,
        plan_key="plan-a",
        plan_name="方案 A",
        style="原木风",
        plan_json={"style": "原木风"},
    )
    db.add(plan)
    db.commit()
    return task, plan


def test_create_or_get_is_idempotent_and_rejects_digest_conflict():
    engine, factory = _database()
    try:
        with factory() as db:
            task, plan = _persist_plan(db)
            first, created = effect_render_job_service.create_or_get_job(
                db,
                task_id=task.id,
                plan_version_id=plan.id,
                idempotency_key="render-key-1",
                request_digest="sha256:first",
                prompt_snapshot="a living room",
                prompt_digest="sha256:prompt",
                source_image_id=None,
                source_image_digest=None,
                max_attempts=2,
                execution_timeout_seconds=300,
            )
            same, created_again = effect_render_job_service.create_or_get_job(
                db,
                task_id=task.id,
                plan_version_id=plan.id,
                idempotency_key="render-key-1",
                request_digest="sha256:first",
                prompt_snapshot="a living room",
                prompt_digest="sha256:prompt",
                source_image_id=None,
                source_image_digest=None,
                max_attempts=2,
                execution_timeout_seconds=300,
            )

            assert created is True
            assert created_again is False
            assert same.id == first.id
            assert db.query(EffectRenderJob).count() == 1

            with pytest.raises(effect_render_job_service.IdempotencyConflict):
                effect_render_job_service.create_or_get_job(
                    db,
                    task_id=task.id,
                    plan_version_id=plan.id,
                    idempotency_key="render-key-1",
                    request_digest="sha256:changed",
                    prompt_snapshot="changed",
                    prompt_digest="sha256:changed",
                    source_image_id=None,
                    source_image_digest=None,
                    max_attempts=2,
                    execution_timeout_seconds=300,
                )
    finally:
        engine.dispose()


def test_expired_lease_retries_then_dead_letters_and_stale_attempt_cannot_commit():
    engine, factory = _database()
    try:
        with factory() as db:
            task, plan = _persist_plan(db)
            job, _ = effect_render_job_service.create_or_get_job(
                db,
                task_id=task.id,
                plan_version_id=plan.id,
                idempotency_key="render-key-2",
                request_digest="sha256:first",
                prompt_snapshot="a living room",
                prompt_digest="sha256:prompt",
                source_image_id=None,
                source_image_digest=None,
                max_attempts=2,
                execution_timeout_seconds=300,
            )
            first = effect_render_job_service.claim_next_job(
                db, worker_id="worker-a", lease_seconds=30
            )
            assert first is not None
            first_attempt = first.attempt_count
            first.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()

            assert effect_render_job_service.complete_job(
                db,
                job_id=job.id,
                worker_id="worker-a",
                worker_attempt=first_attempt,
                image_url="/uploads/effect_renders/stale.png",
                mode="text2img",
            ) is False
            assert db.query(RenderedImage).count() == 0

            second = effect_render_job_service.claim_next_job(
                db, worker_id="worker-b", lease_seconds=30
            )
            assert second is not None
            assert second.attempt_count == 2
            second.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()

            assert effect_render_job_service.claim_next_job(
                db, worker_id="worker-c", lease_seconds=30
            ) is None
            db.refresh(job)
            assert job.status == "dead_letter"
            assert job.dead_lettered_at is not None
            events = db.query(TaskExecutionEvent).order_by(TaskExecutionEvent.id).all()
            assert [event.event_code for event in events] == [
                "effect.queued",
                "effect.claimed",
                "effect.retry_scheduled",
                "effect.claimed",
                "effect.dead_letter",
            ]
            assert not any(event.event_code == "effect.completed" for event in events)
            assert events[-1].billing_status == "unknown"
    finally:
        engine.dispose()


def test_cancel_queued_job_is_terminal_and_never_claimed():
    engine, factory = _database()
    try:
        with factory() as db:
            task, plan = _persist_plan(db)
            job, _ = effect_render_job_service.create_or_get_job(
                db,
                task_id=task.id,
                plan_version_id=plan.id,
                idempotency_key="render-key-3",
                request_digest="sha256:first",
                prompt_snapshot="a living room",
                prompt_digest="sha256:prompt",
                source_image_id=None,
                source_image_digest=None,
                max_attempts=2,
                execution_timeout_seconds=300,
            )
            cancelled = effect_render_job_service.cancel_job(db, job=job)

            assert cancelled.status == "cancelled"
            assert cancelled.cancel_requested_at is not None
            assert effect_render_job_service.claim_next_job(
                db, worker_id="worker-a", lease_seconds=30
            ) is None
    finally:
        engine.dispose()


def test_cancel_running_job_revokes_worker_and_prevents_output_commit():
    engine, factory = _database()
    try:
        with factory() as db:
            task, plan = _persist_plan(db)
            job, _ = effect_render_job_service.create_or_get_job(
                db,
                task_id=task.id,
                plan_version_id=plan.id,
                idempotency_key="render-key-4",
                request_digest="sha256:first",
                prompt_snapshot="a living room",
                prompt_digest="sha256:prompt",
                source_image_id=None,
                source_image_digest=None,
                max_attempts=2,
                execution_timeout_seconds=300,
            )
            claimed = effect_render_job_service.claim_next_job(
                db, worker_id="worker-a", lease_seconds=30
            )
            assert claimed is not None
            worker_attempt = claimed.attempt_count

            cancelled = effect_render_job_service.cancel_job(db, job=claimed)

            assert cancelled.status == "cancelled"
            assert cancelled.worker_id is None
            assert effect_render_job_service.complete_job(
                db,
                job_id=job.id,
                worker_id="worker-a",
                worker_attempt=worker_attempt,
                image_url="/uploads/effect_renders/cancelled.png",
                mode="text2img",
            ) is False
            assert db.query(RenderedImage).count() == 0
    finally:
        engine.dispose()
