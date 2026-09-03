from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import DesignPlanVersion, DesignRevision, DesignTask, EffectRenderJob, RenderedImage
from app.services import effect_render_job_service
from app.workers import effect_render_worker


def _queued_job(factory):
    with factory() as db:
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
        job, _ = effect_render_job_service.create_or_get_job(
            db,
            task_id=task.id,
            plan_version_id=plan.id,
            idempotency_key="worker-render-1",
            request_digest="sha256:request",
            prompt_snapshot="a living room",
            prompt_digest="sha256:prompt",
            source_image_id=None,
            source_image_digest=None,
            max_attempts=2,
            execution_timeout_seconds=300,
        )
        return job.id


def test_worker_publishes_png_and_binds_rendered_image(monkeypatch, tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    job_id = _queued_job(factory)
    monkeypatch.setattr(effect_render_worker, "SessionLocal", factory)
    monkeypatch.setattr(effect_render_worker.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(effect_render_worker.sd_service, "is_available", lambda: True)
    monkeypatch.setattr(
        effect_render_worker.sd_service,
        "render_effect_image",
        lambda *_: (b"\x89PNG\r\n\x1a\ncontent", "text2img"),
    )

    assert effect_render_worker.process_one_job(worker_id="worker-a") is True

    with factory() as db:
        job = db.get(EffectRenderJob, job_id)
        assert job.status == "completed"
        assert job.rendered_image_id is not None
        assert db.query(RenderedImage).count() == 1
        assert (tmp_path / job.output_url.removeprefix("/uploads/")).is_file()
    engine.dispose()


def test_worker_records_disabled_provider_without_creating_output(monkeypatch, tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    job_id = _queued_job(factory)
    monkeypatch.setattr(effect_render_worker, "SessionLocal", factory)
    monkeypatch.setattr(effect_render_worker.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(effect_render_worker.sd_service, "is_available", lambda: False)

    assert effect_render_worker.process_one_job(worker_id="worker-a") is True

    with factory() as db:
        job = db.get(EffectRenderJob, job_id)
        assert job.status == "provider_unavailable"
        assert job.rendered_image_id is None
        assert db.query(RenderedImage).count() == 0
    engine.dispose()


def test_worker_removes_published_file_when_attempt_loses_ownership(
    monkeypatch, tmp_path
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    _queued_job(factory)
    monkeypatch.setattr(effect_render_worker, "SessionLocal", factory)
    monkeypatch.setattr(effect_render_worker.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(effect_render_worker.sd_service, "is_available", lambda: True)
    monkeypatch.setattr(
        effect_render_worker.sd_service,
        "render_effect_image",
        lambda *_: (b"\x89PNG\r\n\x1a\ncontent", "text2img"),
    )
    monkeypatch.setattr(
        effect_render_worker.effect_render_job_service,
        "complete_job",
        lambda *_, **__: False,
    )

    assert effect_render_worker.process_one_job(worker_id="stale-worker") is True
    assert list((tmp_path / "effect_renders").glob("*.png")) == []
    engine.dispose()
