from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from evals.release_change_detection import (
    build_signed_release_proof,
    classify_release_sensitive_paths,
    main,
    verify_release_proof,
)


COMMIT_SHA = "a" * 40


def _key_material() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return (
        base64.b64encode(private_pem).decode("ascii"),
        base64.b64encode(public_pem).decode("ascii"),
    )


def _proof_payload(
    private_key_b64: str,
    *,
    commit_sha: str = COMMIT_SHA,
    issued_at: str = "2026-09-08T00:00:00+00:00",
):
    return build_signed_release_proof(
        {
            "schema_version": "1.0",
            "proof_type": "real_world_release_regression",
            "status": "passed",
            "overall_passed": True,
            "commit_sha": commit_sha,
            "issued_at": issued_at,
            "app_build_digest": "sha256:" + "b" * 64,
            "change_detection": {
                "required": True,
                "status": "proof_required",
            },
            "splits": [
                {"split": "development", "absolute_gate_passed": True},
                {"split": "regression", "absolute_gate_passed": True},
                {"split": "blind", "absolute_gate_passed": True},
            ],
        },
        signing_key_b64=private_key_b64,
        key_id="release-proof-v1",
    )


def test_signed_release_proof_is_verifiable_without_private_key(tmp_path: Path):
    private_key_b64, public_key_b64 = _key_material()
    proof = _proof_payload(private_key_b64)
    proof_path = tmp_path / "release-proof.json"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")

    verified = verify_release_proof(
        proof_path,
        expected_commit_sha=COMMIT_SHA,
        public_key_b64=public_key_b64,
        expected_key_id="release-proof-v1",
        now=datetime(2026, 9, 8, 1, tzinfo=timezone.utc),
    )

    assert verified["commit_sha"] == COMMIT_SHA
    assert verified["gate_status"] == "passed"
    assert "splits" not in verified


def test_sensitive_change_without_or_with_invalid_proof_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from evals import release_change_detection

    monkeypatch.setattr(
        release_change_detection,
        "changed_paths_between",
        lambda *_args, **_kwargs: ["backend/app/core/config.py"],
    )
    output = tmp_path / "result.json"

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-ref",
                "b" * 40,
                "--head-ref",
                COMMIT_SHA,
                "--output",
                str(output),
            ]
        )
        == 2
    )

    private_key_b64, public_key_b64 = _key_material()
    proof_path = tmp_path / "proof.json"
    proof = _proof_payload(
        private_key_b64,
        issued_at=datetime.now(timezone.utc).isoformat(),
    )
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setenv("REAL_WORLD_RELEASE_PROOF_PUBLIC_KEY_B64", public_key_b64)
    monkeypatch.setenv("REAL_WORLD_RELEASE_PROOF_KEY_ID", "release-proof-v1")
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-ref",
                "b" * 40,
                "--head-ref",
                COMMIT_SHA,
                "--proof-file",
                str(proof_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["claim"] == "proof_verified"
    assert result["proof"] == {
        "required": True,
        "verified": True,
        "commit_sha": COMMIT_SHA,
        "signature_key_id": "release-proof-v1",
    }

    proof = _proof_payload(private_key_b64, commit_sha="c" * 40)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-ref",
                "b" * 40,
                "--head-ref",
                COMMIT_SHA,
                "--proof-file",
                str(proof_path),
                "--output",
                str(output),
            ]
        )
        == 2
    )


def test_detect_only_classifies_sensitive_change_without_reading_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from evals import release_change_detection

    monkeypatch.setattr(
        release_change_detection,
        "changed_paths_between",
        lambda *_args, **_kwargs: ["backend/app/core/config.py"],
    )
    output = tmp_path / "result.json"

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-ref",
                "b" * 40,
                "--head-ref",
                COMMIT_SHA,
                "--detect-only",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["claim"] == "proof_required"
    assert result["proof"]["verified"] is False


def test_non_sensitive_change_does_not_require_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from evals import release_change_detection

    monkeypatch.setattr(
        release_change_detection,
        "changed_paths_between",
        lambda *_args, **_kwargs: ["docs/operator-guide.md"],
    )

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-ref",
                "b" * 40,
                "--head-ref",
                COMMIT_SHA,
            ]
        )
        == 0
    )


def test_open_geometry_contract_and_renderer_changes_require_release_proof():
    changes = classify_release_sensitive_paths(
        [
            "backend/app/services/open_geometry_service.py",
            "backend/app/services/open_geometry_contract.py",
            "backend/app/schemas/open_geometry.py",
            "shared/furniture_open_geometry_contract.json",
            "skills/furniture-open-geometry/SKILL.md",
            "frontend/src/lib/openGeometryRenderer.ts",
            "frontend/src/components/furniture/DeterministicFurnitureModel3D.tsx",
            "backend/evals/open_geometry.py",
            "backend/evals/run_open_geometry_eval.py",
            "backend/evals/cases/open_geometry.py",
        ]
    )

    assert changes.required is True
    assert len(changes.by_category["open_geometry"]) == 10


def test_action_plan_eval_and_contract_changes_require_release_proof():
    changes = classify_release_sensitive_paths(
        [
            "backend/app/schemas/agent_action_plan.py",
            "backend/evals/agent_action_plan.py",
            "backend/evals/run_agent_action_plan_eval.py",
            "backend/evals/cases/agent_action_plan.py",
        ]
    )

    assert changes.required is True
    assert len(changes.by_category["action_plan"]) == 4


def test_generation_constraints_are_release_sensitive_catalog_logic():
    changes = classify_release_sensitive_paths(
        ["backend/app/services/generation_constraints_service.py"]
    )

    assert changes.required is True
    assert changes.by_category["data"] == (
        "backend/app/services/generation_constraints_service.py",
    )


def test_model_call_governance_changes_require_release_proof():
    path = "backend/app/services/model_call_governance_service.py"
    changes = classify_release_sensitive_paths([path])

    assert changes.required is True
    assert changes.by_category["model"] == (path,)


def test_delivery_eligibility_rules_require_release_proof():
    paths = [
        "backend/app/schemas/custom_quote_evidence.py",
        "backend/app/schemas/product_eligibility.py",
        "backend/app/services/custom_quote_evidence_service.py",
        "backend/app/services/frozen_product_eligibility_service.py",
        "backend/app/services/generation_request_service.py",
        "backend/app/services/generation_source_service.py",
        "backend/app/services/plan_delivery_service.py",
        "backend/app/services/plan_traceability_audit_service.py",
    ]

    changes = classify_release_sensitive_paths(paths)

    assert changes.required is True
    assert changes.by_category["data"] == tuple(sorted(paths))


def test_release_proof_rejects_tampering_and_wrong_key(tmp_path: Path):
    private_key_b64, public_key_b64 = _key_material()
    proof = _proof_payload(private_key_b64)
    proof["gate_status"] = "failed"
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")

    with pytest.raises(ValueError, match="签名|通过"):
        verify_release_proof(
            proof_path,
            expected_commit_sha=COMMIT_SHA,
            public_key_b64=public_key_b64,
            expected_key_id="release-proof-v1",
            now=datetime(2026, 9, 8, 1, tzinfo=timezone.utc),
        )


def test_release_proof_rejects_wrong_key_id_and_stale_or_future_timestamp(
    tmp_path: Path,
):
    private_key_b64, public_key_b64 = _key_material()
    proof_path = tmp_path / "proof.json"
    proof = _proof_payload(private_key_b64)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    verification_time = datetime(2026, 9, 8, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="key_id"):
        verify_release_proof(
            proof_path,
            expected_commit_sha=COMMIT_SHA,
            public_key_b64=public_key_b64,
            expected_key_id="release-proof-v2",
            now=verification_time,
        )

    stale = _proof_payload(
        private_key_b64,
        issued_at=(verification_time - timedelta(days=8)).isoformat(),
    )
    proof_path.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(ValueError, match="过期"):
        verify_release_proof(
            proof_path,
            expected_commit_sha=COMMIT_SHA,
            public_key_b64=public_key_b64,
            expected_key_id="release-proof-v1",
            now=verification_time,
        )

    future_report = {
        "status": "passed",
        "overall_passed": True,
        "commit_sha": COMMIT_SHA,
        "issued_at": (verification_time + timedelta(minutes=6)).isoformat(),
    }
    future = build_signed_release_proof(
        future_report,
        signing_key_b64=private_key_b64,
        key_id="release-proof-v1",
    )
    proof_path.write_text(json.dumps(future), encoding="utf-8")
    with pytest.raises(ValueError, match="未来"):
        verify_release_proof(
            proof_path,
            expected_commit_sha=COMMIT_SHA,
            public_key_b64=public_key_b64,
            expected_key_id="release-proof-v1",
            now=verification_time,
        )
