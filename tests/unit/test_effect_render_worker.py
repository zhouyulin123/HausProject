from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import (
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    DesignTask,
    EffectRenderJob,
    RenderedImage,
)
from app.services import effect_render_job_service
from app.workers import effect_render_worker
from app.schemas.scenes import SceneDocument


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


def _scene_payload(*, sku: str, custom: bool = False) -> dict:
    item = {
        "instanceId": "sofa-main",
        "sku": sku,
        "category": "沙发",
        "dimensions": {"x": 2.2, "y": 0.85, "z": 0.95},
        "transform": {
            "position": {"x": 1.25, "y": 0.425, "z": 2.75},
            "rotation": {"x": 0, "y": 1.57, "z": 0},
            "scale": {"x": 1, "y": 1, "z": 1},
        },
        "sourceType": "custom_furniture_draft" if custom else "catalog",
        "assetMode": "parametric",
    }
    if custom:
        item["customFurnitureRef"] = {
            "taskId": 1,
            "planVersionId": 1,
            "introducedSceneVersion": 1,
            "draftClientMutationId": "draft-worker-1",
            "draftStateVersion": 1,
            "specDigest": "sha256:" + "a" * 64,
        }
    return {
        "schemaVersion": "1.0",
        "unit": "m",
        "coordinateSystem": "right-handed-y-up",
        "room": {
            "id": "living-room",
            "name": "客厅",
            "floorPolygon": [
                {"x": 0, "z": 0},
                {"x": 5, "z": 0},
                {"x": 5, "z": 4},
                {"x": 0, "z": 4},
            ],
            "ceilingHeight": 2.8,
            "wallThickness": 0.12,
        },
        "items": [item],
    }


def _queued_scene_job(factory, *, bad_digest: bool = False):
    from hashlib import sha256
    import json

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
        db.flush()
        version_one_json = _scene_payload(sku="CUSTOM-OLD", custom=True)
        version_one_json["items"][0]["customFurnitureRef"]["taskId"] = task.id
        version_one_json["items"][0]["customFurnitureRef"]["planVersionId"] = plan.id
        scene = DesignScene(plan_version_id=plan.id, current_version=2)
        db.add(scene)
        db.flush()
        version_one = DesignSceneVersion(
            scene_id=scene.id,
            version=1,
            scene_json=version_one_json,
            validation_json={"valid": True},
        )
        version_two = DesignSceneVersion(
            scene_id=scene.id,
            version=2,
            scene_json=_scene_payload(sku="CURRENT-NEW"),
            validation_json={"valid": True},
        )
        db.add_all([version_one, version_two])
        db.commit()
        normalized_scene = SceneDocument.model_validate(version_one_json).model_dump(
            by_alias=True,
            mode="json",
        )
        canonical = json.dumps(
            normalized_scene,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        scene_digest = f"sha256:{sha256(canonical).hexdigest()}"
        if bad_digest:
            scene_digest = "sha256:" + "0" * 64
        job, _ = effect_render_job_service.create_or_get_job(
            db,
            task_id=task.id,
            plan_version_id=plan.id,
            scene_id=scene.id,
            scene_version_id=version_one.id,
            scene_version=1,
            scene_digest=scene_digest,
            scene_snapshot_json=normalized_scene,
            idempotency_key="worker-scene-render-1",
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


def test_worker_records_disabled_provider_without_creating_output(
    monkeypatch, tmp_path
):
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


def test_worker_conditions_prompt_from_bound_scene_version_not_current_scene(
    monkeypatch, tmp_path
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    job_id = _queued_scene_job(factory)
    captured: dict = {}
    monkeypatch.setattr(effect_render_worker, "SessionLocal", factory)
    monkeypatch.setattr(effect_render_worker.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(effect_render_worker.sd_service, "is_available", lambda: True)

    def fake_render(prompt, source_image):
        captured["prompt"] = prompt
        captured["source_image"] = source_image
        return b"\x89PNG\r\n\x1a\ncontent", "text2img"

    monkeypatch.setattr(
        effect_render_worker.sd_service, "render_effect_image", fake_render
    )

    assert effect_render_worker.process_one_job(worker_id="scene-worker") is True

    prompt = captured["prompt"]
    assert "CUSTOM-OLD" in prompt
    assert "CURRENT-NEW" not in prompt
    assert '"sourceType":"custom_furniture_draft"' in prompt
    assert '"position":{"x":1.25,"y":0.425,"z":2.75}' in prompt
    assert '"dimensions":{"x":2.2,"y":0.85,"z":0.95}' in prompt
    assert captured["source_image"] is None
    with factory() as db:
        job = db.get(EffectRenderJob, job_id)
        rendered = db.get(RenderedImage, job.rendered_image_id)
        assert job.status == "completed"
        assert rendered.scene_version_id == job.scene_version_id
    engine.dispose()


def test_worker_rejects_scene_snapshot_when_persisted_digest_does_not_match(
    monkeypatch, tmp_path
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    job_id = _queued_scene_job(factory, bad_digest=True)
    monkeypatch.setattr(effect_render_worker, "SessionLocal", factory)
    monkeypatch.setattr(effect_render_worker.settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(
        effect_render_worker.sd_service,
        "is_available",
        lambda: (_ for _ in ()).throw(AssertionError("摘要不匹配不得调用供应商")),
    )

    assert effect_render_worker.process_one_job(worker_id="scene-worker") is True

    with factory() as db:
        job = db.get(EffectRenderJob, job_id)
        assert job.status == "failed"
        assert job.rendered_image_id is None
    engine.dispose()
