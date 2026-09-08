from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.schemas.failure_triage import FailureVerificationReportRequest
from app.services.failure_triage_service import failure_fingerprint
from app.services.failure_triage_signature import verify_failure_triage_signature
from app.services.generation_provenance import canonical_digest
from evals.failure_verification import (
    build_failure_verification_report,
    main,
)


SIGNING_KEY = "failure-verification-signing-key-at-least-32"


def _sha(char: str) -> str:
    return "sha256:" + char * 64


FINGERPRINT = failure_fingerprint(
    taxonomy_version="taxonomy-1",
    data_version="data-1",
    failure_type="catalog",
    code="stale_price",
)
COMMIT_SHA = "a" * 40


def _triage_report(split: str, *, recurring: bool = False) -> dict:
    manifest = _sha(str(ord(split[0]) % 10))
    evidence = _sha(str((ord(split[0]) + 1) % 10))
    output = _sha(str((ord(split[0]) + 2) % 10))
    return {
        "schema_version": "2.0",
        "input": {
            "taxonomy_version": "taxonomy-1",
            "data_version": "data-1",
            "manifest_digest": manifest,
            "evidence_digest": evidence,
            "output_digests": [output],
        },
        "clusters": (
            [
                {
                    "failure_type": "catalog",
                    "code": "stale_price",
                    "severity": "high",
                    "failure_count": 1,
                    "affected_case_count": 1,
                    "splits": [split],
                    "case_ids": [f"alias-{split}"],
                    "execution_refs": [f"exec-{split}"],
                    "output_digests": [output],
                    "tag_counts": {},
                    "metric_counts": {},
                }
            ]
            if recurring
            else []
        ),
    }


def _signed_triage_payload(report: dict) -> dict:
    from evals.failure_triage import build_failure_triage_sync_payload

    return build_failure_triage_sync_payload(
        report,
        report_id=f"release-{report['input']['manifest_digest']}",
        candidate_version=COMMIT_SHA,
        signing_key_id="triage-key-1",
        signing_key=SIGNING_KEY,
        generated_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )


def _release_gate(triage_reports: dict[str, dict]) -> dict:
    return {
        "schema_version": "1.0",
        "proof_type": "real_world_release_regression",
        "status": "passed",
        "overall_passed": True,
        "commit_sha": COMMIT_SHA,
        "splits": [
            {
                "split": split,
                "absolute_gate_passed": True,
                "regression_passed": True,
                "dataset_fingerprint": report["input"]["manifest_digest"],
                "candidate_evidence_digest": report["input"]["evidence_digest"],
                "baseline_evidence_digest": _sha(str(index + 4)),
                "failure_triage": {
                    "report_digest": "pending",
                },
            }
            for index, (split, report) in enumerate(triage_reports.items())
        ],
    }


def _inputs(tmp_path: Path, *, recurring: bool = False):
    triage_reports = {
        split: _triage_report(split, recurring=recurring)
        for split in ("development", "regression", "blind")
    }
    for report in triage_reports.values():
        report["sync_payload"] = _signed_triage_payload(report)
    gate = _release_gate(triage_reports)
    for item, report in zip(gate["splits"], triage_reports.values()):
        item["failure_triage"]["report_digest"] = (
            canonical_digest(report)
        )
    return gate, triage_reports


def _targets() -> list[dict[str, str]]:
    return [{"fingerprint": FINGERPRINT, "fixed_version": "rules-2"}]


def test_builds_signed_complete_failure_verification_without_case_ids(tmp_path):
    gate, triage_reports = _inputs(tmp_path)

    report = build_failure_verification_report(
        release_gate_report=gate,
        triage_reports=triage_reports,
        targets=_targets(),
        signing_key=SIGNING_KEY,
        signing_key_id="triage-key-1",
        generated_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    parsed = FailureVerificationReportRequest.model_validate(report)
    assert parsed.covered_splits == ["blind", "development", "regression"]
    assert verify_failure_triage_signature(report, signing_key=SIGNING_KEY)
    assert "alias-" not in json.dumps(report)
    assert "case_ids" not in report


def test_incomplete_split_or_reappeared_target_fails_closed(tmp_path):
    gate, triage_reports = _inputs(tmp_path, recurring=True)
    with pytest.raises(ValueError, match="三 split|重复|复现"):
        build_failure_verification_report(
            release_gate_report=gate,
            triage_reports={key: value for key, value in triage_reports.items() if key != "blind"},
            targets=_targets(),
            signing_key=SIGNING_KEY,
            signing_key_id="triage-key-1",
        )

    with pytest.raises(ValueError, match="复现"):
        build_failure_verification_report(
            release_gate_report=gate,
            triage_reports=triage_reports,
            targets=_targets(),
            signing_key=SIGNING_KEY,
            signing_key_id="triage-key-1",
        )


def test_gate_identity_and_candidate_commit_must_match(tmp_path):
    gate, triage_reports = _inputs(tmp_path)
    gate["proof_type"] = "other"
    with pytest.raises(ValueError, match="门禁报告"):
        build_failure_verification_report(
            release_gate_report=gate,
            triage_reports=triage_reports,
            targets=_targets(),
            signing_key=SIGNING_KEY,
            signing_key_id="triage-key-1",
        )

    gate, triage_reports = _inputs(tmp_path)
    gate["commit_sha"] = "b" * 40
    with pytest.raises(ValueError, match="提交"):
        build_failure_verification_report(
            release_gate_report=gate,
            triage_reports=triage_reports,
            targets=_targets(),
            signing_key=SIGNING_KEY,
            signing_key_id="triage-key-1",
        )


def test_report_identity_binds_the_explicit_target_set(tmp_path):
    gate, triage_reports = _inputs(tmp_path)
    first = build_failure_verification_report(
        release_gate_report=gate,
        triage_reports=triage_reports,
        targets=_targets(),
        signing_key=SIGNING_KEY,
        signing_key_id="triage-key-1",
    )
    second_target = {
        "fingerprint": failure_fingerprint(
            taxonomy_version="taxonomy-1",
            data_version="data-1",
            failure_type="layout",
            code="item_collision",
        ),
        "fixed_version": "rules-3",
    }
    second = build_failure_verification_report(
        release_gate_report=gate,
        triage_reports=triage_reports,
        targets=[*_targets(), second_target],
        signing_key=SIGNING_KEY,
        signing_key_id="triage-key-1",
    )

    assert first["report_id"] != second["report_id"]
    assert len(first["report_id"]) <= 100


def test_output_failure_returns_two_and_does_not_publish(tmp_path, monkeypatch):
    gate, triage_reports = _inputs(tmp_path)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps({"schema_version": "1.0", "verified_clusters": _targets()}),
        encoding="utf-8",
    )
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    triage_dir = tmp_path / "triage"
    triage_dir.mkdir()
    for split, report in triage_reports.items():
        (triage_dir / f"{split}.failure_triage.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
    output = tmp_path / "not-a-directory" / "report.json"
    output.parent.write_text("file", encoding="utf-8")
    monkeypatch.setenv("FAILURE_VERIFICATION_SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("FAILURE_VERIFICATION_SIGNING_KEY_ID", "triage-key-1")

    assert (
        main(
            [
                "--release-gate-report",
                str(gate_path),
                "--triage-dir",
                str(triage_dir),
                "--targets",
                str(targets_path),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()
