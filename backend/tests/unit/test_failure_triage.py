from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.services.failure_triage_signature import verify_failure_triage_signature
from evals.failure_triage import (
    FailureTriageInputError,
    build_failure_triage_report,
    load_failure_triage_evidence,
    load_trusted_failure_evidence,
    render_failure_triage_markdown,
)
from evals.real_world import CaseResult, load_case_manifest
from evals.run_failure_triage import main as run_failure_triage_main
from evals.trusted_evidence import (
    _case_fingerprint,
    _digest,
    _signature,
    dataset_fingerprint,
)
from tests.real_world_fixtures import write_v2_manifest


EVIDENCE_KEY = "trusted-evidence-key-that-is-at-least-32-bytes"
REPORT_KEY = "trusted-report-key-that-is-at-least-32-bytes"


def _dataset(tmp_path: Path):
    (tmp_path / "room.png").write_bytes(b"authorized-room")
    manifest = write_v2_manifest(
        tmp_path,
        filename="manifest.json",
        dataset_version="dataset-v2",
        cases=[
            {
                "id": "private-case-a",
                "name": "匿名案例",
                "split": "regression",
                "origin": "private_real",
                "asset_path": "room.png",
                "consent_status": "granted",
                "annotation_status": "ready",
                "label_version": "labels-v2",
                "allowed_purposes": ["offline_evaluation"],
                "failure_tags": [],
                "task_input": {
                    "raw_user_input": "现代客厅",
                    "confirmed_requirement": {"style": "现代"},
                    "space_type": "客厅",
                    "style": "现代",
                    "budget_min": 10000,
                    "budget_max": 20000,
                },
            }
        ],
    )
    return manifest, load_case_manifest(manifest)


def _trusted_bundle(dataset, *, failing: bool = True) -> dict:
    manifest_digest = dataset_fingerprint(dataset, split="regression")
    result = CaseResult(
        case_id="private-case-a",
        recommended_skus=2,
        valid_skus=1 if failing else 2,
        layout_checks=1,
        layout_hard_passes=0 if failing else 1,
        generation_succeeded=True,
    )
    result_payload = asdict(result)
    result_payload.pop("case_id")
    versions = {
        "model": "model-v1",
        "prompt": "sha256:" + "1" * 64,
        "rules": "sha256:" + "2" * 64,
        "data": "sha256:" + "3" * 64,
    }
    unsigned = {
        "schema_version": "4.0",
        "evidence_type": "system_execution",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "dataset_fingerprint": manifest_digest,
        "split": "regression",
        "versions": versions,
        "executions": [
            {
                "case_fingerprint": _case_fingerprint(
                    manifest_digest,
                    "private-case-a",
                ),
                "execution_ref": "exec-hmac-sha256:" + "4" * 64,
                "source": "generation_worker",
                "generator": "llm",
                "status": "completed",
                "model": "model-v1",
                "prompt_digest": versions["prompt"],
                "rules_digest": versions["rules"],
                "data_digest": versions["data"],
                "input_digest": "sha256:" + "5" * 64,
                "output_digest": "sha256:" + "6" * 64,
                "result": result_payload,
                "result_digest": _digest(result_payload),
            }
        ],
    }
    return {
        **unsigned,
        "attestation": {
            "algorithm": "HMAC-SHA256",
            "key_id": "quality-key-v1",
            "signature": _signature(unsigned, EVIDENCE_KEY),
        },
    }


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_triage_aggregates_only_verified_evidence_and_anonymizes_cases(tmp_path):
    _, dataset = _dataset(tmp_path)
    evidence_path = _write_json(tmp_path / "evidence.json", _trusted_bundle(dataset))
    evidence = load_trusted_failure_evidence(
        evidence_path,
        dataset=dataset,
        split="regression",
        verification_keys={"quality-key-v1": EVIDENCE_KEY},
    )

    first = build_failure_triage_report(
        dataset=dataset,
        evidence=evidence,
        anonymization_salt="case-reference-key-at-least-16-bytes",
        salt_id="case-key-v1",
    )
    second = build_failure_triage_report(
        dataset=dataset,
        evidence=evidence,
        anonymization_salt="case-reference-key-at-least-16-bytes",
        salt_id="case-key-v1",
    )

    assert first == second
    assert first["summary"] == {
        "eligible_case_count": 1,
        "failure_count": 2,
        "affected_case_count": 1,
    }
    assert {item["code"] for item in first["clusters"]} == {
        "invalid_sku",
        "layout_hard_constraint_failed",
    }
    assert first["input"]["manifest_digest"] == dataset_fingerprint(
        dataset,
        split="regression",
    )
    assert first["input"]["evidence_digest"].startswith("sha256:")
    assert first["input"]["output_digests"] == ["sha256:" + "6" * 64]
    serialized = json.dumps(first, ensure_ascii=False)
    assert "private-case-a" not in serialized
    assert "task_id" not in serialized
    assert "system_run_id" not in serialized


def test_legacy_self_reported_failure_file_is_always_rejected(tmp_path):
    legacy = _write_json(
        tmp_path / "failures.json",
        {
            "schema_version": "1.0",
            "taxonomy_version": "1.0",
            "data_version": "dataset-v2",
            "failures": [],
        },
    )

    with pytest.raises(FailureTriageInputError, match="不再接受自报失败文件"):
        load_failure_triage_evidence(legacy, dataset=object())


def test_failure_triage_cli_verifies_evidence_and_signs_bound_report(
    tmp_path,
    monkeypatch,
):
    manifest, dataset = _dataset(tmp_path)
    evidence_path = _write_json(tmp_path / "evidence.json", _trusted_bundle(dataset))
    monkeypatch.setenv("EVAL_CASE_ID_SALT", "case-reference-key-at-least-16-bytes")
    monkeypatch.setenv("EVAL_EVIDENCE_HMAC_KEY", EVIDENCE_KEY)
    monkeypatch.setenv("EVAL_EVIDENCE_KEY_ID", "quality-key-v1")
    monkeypatch.setenv("EVAL_REPORT_SIGNING_KEY", REPORT_KEY)

    output_dir = tmp_path / "report"
    exit_code = run_failure_triage_main(
        [
            "--manifest",
            str(manifest),
            "--split",
            "regression",
            "--evidence",
            str(evidence_path),
            "--output-dir",
            str(output_dir),
            "--salt-id",
            "case-key-v1",
            "--report-id",
            "weekly-2026-W36",
            "--candidate-version",
            "candidate-v1",
            "--signing-key-id",
            "report-key-v1",
        ]
    )

    assert exit_code == 1
    report = json.loads((output_dir / "failure_triage.json").read_text("utf-8"))
    sync_payload = report["sync_payload"]
    assert sync_payload["schema_version"] == "2.0"
    assert sync_payload["manifest_digest"] == report["input"]["manifest_digest"]
    assert sync_payload["evidence_digest"] == report["input"]["evidence_digest"]
    assert sync_payload["output_digests"] == report["input"]["output_digests"]
    assert verify_failure_triage_signature(
        sync_payload,
        signing_key=REPORT_KEY,
    )
    markdown = (output_dir / "failure_triage.md").read_text("utf-8")
    assert "invalid_sku" in markdown
    assert "private-case-a" not in markdown


def test_failure_triage_cli_fails_closed_on_tampered_evidence(tmp_path, monkeypatch):
    manifest, dataset = _dataset(tmp_path)
    bundle = _trusted_bundle(dataset)
    bundle["executions"][0]["result"]["valid_skus"] = 2
    evidence_path = _write_json(tmp_path / "tampered.json", bundle)
    monkeypatch.setenv("EVAL_CASE_ID_SALT", "case-reference-key-at-least-16-bytes")
    monkeypatch.setenv("EVAL_EVIDENCE_HMAC_KEY", EVIDENCE_KEY)
    monkeypatch.setenv("EVAL_EVIDENCE_KEY_ID", "quality-key-v1")
    monkeypatch.setenv("EVAL_REPORT_SIGNING_KEY", REPORT_KEY)

    output_dir = tmp_path / "report"
    exit_code = run_failure_triage_main(
        [
            "--manifest",
            str(manifest),
            "--split",
            "regression",
            "--evidence",
            str(evidence_path),
            "--output-dir",
            str(output_dir),
            "--report-id",
            "tampered",
            "--candidate-version",
            "candidate-v1",
            "--signing-key-id",
            "report-key-v1",
        ]
    )

    assert exit_code == 2
    assert not output_dir.exists()


def test_triage_markdown_contains_only_structured_dimensions(tmp_path):
    _, dataset = _dataset(tmp_path)
    path = _write_json(tmp_path / "evidence.json", _trusted_bundle(dataset))
    evidence = load_trusted_failure_evidence(
        path,
        dataset=dataset,
        split="regression",
        verification_keys={"quality-key-v1": EVIDENCE_KEY},
    )
    report = build_failure_triage_report(
        dataset=dataset,
        evidence=evidence,
        anonymization_salt="case-reference-key-at-least-16-bytes",
        salt_id="case-key-v1",
    )

    markdown = render_failure_triage_markdown(report)

    assert "失败类型" in markdown
    assert "严重度" in markdown
    assert "数据切分" in markdown
    assert "catalog" in markdown
    assert "critical" in markdown
    assert "regression" in markdown
