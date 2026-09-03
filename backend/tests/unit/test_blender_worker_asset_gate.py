from datetime import datetime, timezone

from app.db.models import Product
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


def test_blender_rejects_ready_glb_when_shared_review_gate_rejects_it():
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

    product_asset_service.product_asset_contract = reject
    try:
        urls = blender_worker.approved_product_model_urls(
            [product],
            allow_uploaded_models=True,
        )
    finally:
        product_asset_service.product_asset_contract = original

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
