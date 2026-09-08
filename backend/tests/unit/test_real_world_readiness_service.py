import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.real_world_readiness_service import (
    RealWorldReadinessError,
    build_real_world_readiness,
)
from app.services import real_world_readiness_service
from evals.real_world import RealWorldCase, RealWorldDataset


def _write_manifest(root: Path) -> Path:
    asset_dir = root / "assets"
    asset_dir.mkdir()
    for filename in ("development.png", "regression.png", "blind.png", "unassigned.png"):
        (asset_dir / filename).write_bytes(filename.encode())
    cases = [
        {
            "id": "development-1",
            "name": "脱敏开发案例",
            "split": "development",
            "origin": "private_real",
            "asset_path": "assets/development.png",
            "consent_status": "granted",
            "annotation_status": "ready",
            "label_version": "labels-1",
            "allowed_purposes": ["offline_evaluation"],
            "failure_tags": [],
        },
        {
            "id": "regression-1",
            "name": "脱敏回归案例",
            "split": "regression",
            "origin": "private_real",
            "asset_path": "assets/regression.png",
            "consent_status": "pending",
            "annotation_status": "ready",
            "label_version": "labels-1",
            "allowed_purposes": ["offline_evaluation"],
            "failure_tags": [],
        },
        {
            "id": "blind-1",
            "name": "脱敏盲测案例",
            "split": "blind",
            "origin": "private_real",
            "asset_path": "assets/blind.png",
            "consent_status": "granted",
            "annotation_status": "ready",
            "label_version": "labels-1",
            "allowed_purposes": [],
            "failure_tags": [],
        },
        {
            "id": "unassigned-1",
            "name": "脱敏未分组案例",
            "split": "unassigned",
            "origin": "private_real",
            "asset_path": "assets/unassigned.png",
            "consent_status": "granted",
            "annotation_status": "pending",
            "label_version": None,
            "allowed_purposes": [],
            "failure_tags": [],
        },
    ]
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"schema_version": "1.0", "dataset_version": "dataset-test-1", "cases": cases},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest


def test_build_real_world_readiness_returns_only_governance_counts(tmp_path):
    checked_at = datetime(2026, 9, 8, tzinfo=timezone.utc)
    result = build_real_world_readiness(_write_manifest(tmp_path), checked_at=checked_at)

    assert result["manifest_version"] == "1.0"
    assert result["dataset_id"] == "dataset-test-1"
    assert result["total"] == 4
    assert result["eligible_total"] == 1
    assert result["private_real_eligible_total"] == 1
    assert result["blocked_total"] == 3
    assert result["split_counts"] == {
        "development": {"total": 1, "eligible": 1},
        "regression": {"total": 1, "eligible": 0},
        "blind": {"total": 1, "eligible": 0},
    }
    assert result["consent_status_counts"] == {"granted": 3, "pending": 1}
    assert result["annotation_status_counts"] == {"pending": 1, "ready": 3}
    assert result["blocker_counts"] == {
        "annotation_not_ready": 1,
        "consent_not_granted": 1,
        "purpose_not_allowed": 2,
        "split_not_assigned": 1,
        "trusted_schema_required": 1,
    }
    assert result["minimum_required"] == 20
    assert result["minimum_met"] is False
    assert result["checked_at"] == checked_at
    serialized = json.dumps(result, ensure_ascii=False, default=str)
    assert "development-1" not in serialized
    assert "脱敏开发案例" not in serialized
    assert "assets/development.png" not in serialized


def test_build_real_world_readiness_fails_closed_for_missing_manifest(tmp_path):
    with pytest.raises(RealWorldReadinessError, match="真实案例清单不可用"):
        build_real_world_readiness(tmp_path / "missing.json")


def test_default_manifest_uses_project_asset_root():
    result = build_real_world_readiness()

    assert result["total"] == 4
    assert result["eligible_total"] == 0
    assert result["private_real_eligible_total"] == 0
    assert result["blocked_total"] == 4


def test_synthetic_case_cannot_satisfy_private_real_minimum(tmp_path, monkeypatch):
    manifest = _write_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["cases"][0]["origin"] = "synthetic"
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(real_world_readiness_service, "MINIMUM_REQUIRED", 1)

    result = build_real_world_readiness(manifest)

    assert result["eligible_total"] == 1
    assert result["private_real_eligible_total"] == 0
    assert result["split_counts"]["development"]["eligible"] == 0
    assert result["minimum_met"] is False


def test_minimum_also_requires_all_three_private_real_splits(tmp_path, monkeypatch):
    monkeypatch.setattr(real_world_readiness_service, "MINIMUM_REQUIRED", 1)

    result = build_real_world_readiness(_write_manifest(tmp_path))

    assert result["private_real_eligible_total"] == 1
    assert result["split_counts"]["development"]["eligible"] == 1
    assert result["split_counts"]["regression"]["eligible"] == 0
    assert result["split_counts"]["blind"]["eligible"] == 0
    assert result["minimum_met"] is False


def _eligible_case(case_id: str, split: str, origin: str = "private_real"):
    return RealWorldCase(
        id=case_id,
        name="脱敏案例",
        split=split,
        origin=origin,
        asset_path=Path(f"{case_id}.png"),
        asset_sha256=case_id.ljust(64, "0")[:64],
        consent_status="granted",
        annotation_status="ready",
        label_version="labels-v1",
        allowed_purposes=("offline_evaluation",),
        failure_tags=(),
    )


def test_minimum_rejects_legacy_schema_and_synthetic_release_case(monkeypatch):
    cases = tuple(
        _eligible_case(f"real-{index}", ("development", "regression", "blind")[index % 3])
        for index in range(20)
    )
    legacy = RealWorldDataset("1.0", "legacy", cases)
    monkeypatch.setattr(
        real_world_readiness_service,
        "load_case_manifest",
        lambda *_args, **_kwargs: legacy,
    )
    result = build_real_world_readiness("unused.json")
    assert result["minimum_met"] is False
    assert result["blocker_counts"]["trusted_schema_required"] == 1

    mixed = RealWorldDataset(
        "2.0",
        "mixed",
        cases + (_eligible_case("synthetic-1", "development", "synthetic"),),
    )
    monkeypatch.setattr(
        real_world_readiness_service,
        "load_case_manifest",
        lambda *_args, **_kwargs: mixed,
    )
    result = build_real_world_readiness("unused.json")
    assert result["private_real_eligible_total"] == 20
    assert result["minimum_met"] is False
    assert result["blocker_counts"]["synthetic_release_case"] == 1
