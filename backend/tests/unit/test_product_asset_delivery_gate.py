from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.product_asset_service import product_asset_contract


NOW = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)


def _product(**overrides):
    values = {
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
    return SimpleNamespace(**values)


def test_delivery_contract_exposes_only_reviewed_glb_url():
    approved = product_asset_contract(_product())
    pending = product_asset_contract(_product(model_license=""))

    assert approved["approved_model_url"] == "/uploads/models/sofa.glb"
    assert approved["asset_review"]["glb"] == {
        "status": "approved",
        "reason_code": None,
    }
    assert pending["approved_model_url"] is None
    assert pending["asset_review"]["glb"] == {
        "status": "unavailable",
        "reason_code": "glb_pending_review",
    }


def test_unimplemented_asset_reviews_fail_closed_without_fabricated_approval():
    contract = product_asset_contract(_product())

    for asset_kind in ("image", "cad", "material"):
        assert contract["asset_review"][asset_kind] == {
            "status": "unavailable",
            "reason_code": "review_evidence_missing",
        }


def test_external_or_traversing_glb_url_cannot_become_public():
    for unsafe_url in (
        "https://attacker.example/sofa.glb",
        "/uploads/models/../private.glb",
        "D:/private/sofa.glb",
        "/uploads/models/sofa.exe",
    ):
        contract = product_asset_contract(_product(model_url=unsafe_url))
        assert contract["asset_mode"] == "parametric"
        assert contract["approved_model_url"] is None
        assert contract["fallback_reason"] == "glb_metadata_invalid"
