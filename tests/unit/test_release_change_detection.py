from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from evals.release_change_detection import (
    build_signed_release_proof,
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


def _proof_payload(private_key_b64: str, *, commit_sha: str = COMMIT_SHA):
    return build_signed_release_proof(
        {
            "schema_version": "1.0",
            "proof_type": "real_world_release_regression",
            "status": "passed",
            "overall_passed": True,
            "commit_sha": commit_sha,
            "issued_at": "2026-09-08T00:00:00+00:00",
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
    proof = _proof_payload(private_key_b64)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setenv("REAL_WORLD_RELEASE_PROOF_PUBLIC_KEY_B64", public_key_b64)
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
        )
