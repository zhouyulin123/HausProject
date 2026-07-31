from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import BlenderRenderJob
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
                output_url="/uploads/wrong.png",
            )
            db.refresh(claimed)
            assert claimed.status == "running"

            blender_job_service.mark_completed(
                db,
                job_id=claimed.id,
                worker_id="worker-a",
                output_url="/uploads/blender_renders/right.png",
            )
            db.refresh(claimed)
            assert claimed.status == "completed"
            assert claimed.output_url.endswith("right.png")
    finally:
        engine.dispose()
