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
)
from app.services import blender_job_service


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _job(*, status: str = "queued", attempt: int = 0):
    return BlenderRenderJob(
        scene_id=1,
        scene_version_id=1,
        scene_version=1,
        profile="preview",
        status=status,
        progress=0,
        attempt=attempt,
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
            job.lease_expires_at = datetime.now(timezone.utc) - timedelta(
                seconds=10
            )
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

            retried.lease_expires_at = datetime.now(
                timezone.utc
            ) - timedelta(seconds=10)
            db.commit()
            none_left = blender_job_service.claim_next_job(
                db,
                worker_id="worker-c",
                lease_seconds=300,
                max_attempts=2,
            )

            assert none_left is None
            db.refresh(retried)
            assert retried.status == "failed"
            assert retried.progress == 100
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

            assert blender_job_service.mark_completed(
                db,
                job_id=first.id,
                worker_id="worker-shared",
                worker_attempt=first_attempt,
                output_url="/uploads/blender_renders/expired.png",
            ) is False

            second = blender_job_service.claim_next_job(
                db,
                worker_id="worker-shared",
                lease_seconds=300,
                max_attempts=3,
            )
            assert second is not None
            assert second.attempt == first_attempt + 1

            assert blender_job_service.mark_progress(
                db,
                job_id=second.id,
                worker_id="worker-shared",
                worker_attempt=first_attempt,
                progress=90,
            ) is False
            assert blender_job_service.mark_completed(
                db,
                job_id=second.id,
                worker_id="worker-shared",
                worker_attempt=first_attempt,
                output_url="/uploads/blender_renders/stale.png",
            ) is False
            assert db.query(RenderedImage).count() == 0

            assert blender_job_service.mark_completed(
                db,
                job_id=second.id,
                worker_id="worker-shared",
                worker_attempt=second.attempt,
                output_url="/uploads/blender_renders/current.png",
            ) is True
            rendered = db.query(RenderedImage).one()
            assert rendered.plan_version_id == plan.id
            assert rendered.task_id == task.id
    finally:
        engine.dispose()
