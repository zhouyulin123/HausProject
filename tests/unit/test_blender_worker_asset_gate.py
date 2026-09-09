from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.models import BlenderRenderJob, DesignSceneVersion, Product
from app.services import product_asset_service
from app.workers import blender_worker


NOW = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)


def _product(**overrides) -> Product:
    values = {
        "sku": "SOFA-001",
        "name": "审核沙发",
        "price": 5000,
        "model_url": "/uploads/models/sofa.glb",
        "model_status": "ready",
        "model_width_mm": 2200,
        "model_height_mm": 800,
        "model_depth_mm": 950,
        "model_license": "供应商书面商用授权",
        "model_source": "supplier:SOFA-001",
        "model_reviewed_at": NOW,
        "model_reviewed_by": "user:7",
    }
    values.update(overrides)
    return Product(**values)


def test_blender_rejects_ready_glb_when_shared_review_gate_rejects_it(
    monkeypatch,
):
    product = _product()
    original = product_asset_service.product_asset_contract

    def reject(candidate):
        contract = original(candidate)
        return {
            **contract,
            "asset_mode": "parametric",
            "fallback_reason": "glb_pending_review",
            "approved_model_url": None,
        }

    monkeypatch.setattr(product_asset_service, "product_asset_contract", reject)
    urls = blender_worker.approved_product_model_urls(
        [product],
        allow_uploaded_models=True,
    )

    assert urls == {"SOFA-001": None}


def test_blender_applies_deployment_path_policy_after_shared_review_gate():
    uploaded = _product(sku="UPLOADED", model_url="/uploads/models/sofa.glb")
    bundled = _product(sku="BUNDLED", model_url="/models/demo/sofa.glb")

    assert blender_worker.approved_product_model_urls(
        [uploaded, bundled],
        allow_uploaded_models=False,
    ) == {
        "UPLOADED": None,
        "BUNDLED": "/models/demo/sofa.glb",
    }


def test_final_job_checks_catalog_at_load_and_again_before_publish(monkeypatch):
    job = SimpleNamespace(
        id=7,
        profile="final",
        scene_id=3,
        scene_version_id=11,
    )
    version = SimpleNamespace(
        scene_json={
            "schemaVersion": "1.0",
            "unit": "m",
            "coordinateSystem": "right-handed-y-up",
            "room": {
                "id": "room",
                "name": "客厅",
                "floorPolygon": [
                    {"x": 0, "z": 0},
                    {"x": 4, "z": 0},
                    {"x": 4, "z": 4},
                    {"x": 0, "z": 4},
                ],
                "ceilingHeight": 2.8,
                "wallThickness": 0.12,
            },
            "openings": [],
            "items": [],
        }
    )

    class EmptyScalars:
        def all(self):
            return []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def get(self, model, identity):
            if model is BlenderRenderJob and identity == job.id:
                return job
            if model is DesignSceneVersion and identity == job.scene_version_id:
                return version
            return None

        def scalars(self, *_):
            return EmptyScalars()

        def expunge(self, *_):
            return None

    checks = []
    monkeypatch.setattr(blender_worker, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        blender_worker,
        "_assert_catalog_deliverable",
        lambda *_, **__: checks.append("checked"),
    )

    blender_worker._load_job_payload(job.id)
    blender_worker.assert_job_catalog_deliverable(job.id)

    assert checks == ["checked", "checked"]


def test_blender_retry_delay_is_exponential():
    assert blender_worker.retry_delay_seconds(1, base_seconds=5) == 5
    assert blender_worker.retry_delay_seconds(3, base_seconds=5) == 20
