from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.real_world import EvaluationInputError, load_case_manifest
from evals.real_world_release_gate import (
    classify_release_sensitive_paths,
    load_release_gate_config,
    validate_release_dataset,
    validate_release_event,
)
from tests.real_world_fixtures import write_v2_manifest


def _manifest(tmp_path: Path, *, origin: str = "private_real"):
    asset = tmp_path / "room.png"
    asset.write_bytes(b"real-room")
    manifest = write_v2_manifest(
        tmp_path,
        filename="manifest.json",
        dataset_version="release-data-1",
        cases=[
            {
                "id": "case-1",
                "name": "真实户型",
                "split": "regression",
                "origin": origin,
                "asset_path": asset.name,
                "consent_status": (
                    "granted" if origin == "private_real" else "not_required"
                ),
                "annotation_status": "ready",
                "label_version": "labels-1",
                "allowed_purposes": ["offline_evaluation"],
                "failure_tags": [],
            }
        ],
    )
    return load_case_manifest(manifest)


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("backend/app/core/config.py", "model"),
        ("backend/app/services/llm_service.py", "prompt"),
        ("backend/app/services/layout_repair.py", "rules"),
        ("backend/data/public_products_ikea_cn_2026-08-30.json", "data"),
        ("backend/app/services/catalog_service.py", "data"),
    ],
)
def test_sensitive_path_changes_require_real_world_regression(path, category):
    changes = classify_release_sensitive_paths([path])

    assert changes.required is True
    assert path in changes.by_category[category]


def test_unrelated_docs_change_does_not_claim_a_quality_pass():
    changes = classify_release_sensitive_paths(["docs/operator-guide.md"])

    assert changes.required is False
    assert changes.status == "not_required"


def test_release_dataset_rejects_synthetic_cases_even_outside_blind(tmp_path):
    dataset = _manifest(tmp_path, origin="synthetic")

    with pytest.raises(EvaluationInputError, match="synthetic"):
        validate_release_dataset(dataset, split="regression")


def test_release_dataset_requires_nonzero_real_case_denominator(tmp_path):
    dataset = _manifest(tmp_path)

    with pytest.raises(EvaluationInputError, match="development.*真实案例"):
        validate_release_dataset(dataset, split="development")


def test_only_controlled_manual_workflow_can_issue_release_proof():
    validate_release_event("workflow_dispatch", ("development", "regression", "blind"))

    with pytest.raises(EvaluationInputError, match="workflow_dispatch"):
        validate_release_event("push", ("development", "regression"))
    with pytest.raises(EvaluationInputError, match="PR.*blind"):
        validate_release_event("pull_request", ("blind",))


def test_gate_config_requires_all_splits_and_never_accepts_inline_secrets(tmp_path):
    config = {
        "schema_version": "1.0",
        "splits": {
            split: {
                "manifest": f"private/{split}/manifest.json",
                "asset_root": f"private/{split}",
                "run_bindings": f"private/{split}/bindings.json",
                "security_targets": f"private/{split}/security-targets.json",
                "baseline_evidence": f"private/{split}/baseline.evidence.json",
                "deployment_base_url": "https://eval.example.test",
            }
            for split in ("development", "regression", "blind")
        },
    }
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    loaded = load_release_gate_config(path)

    assert tuple(loaded) == ("development", "regression", "blind")

    config["eval_hmac_key"] = "must-not-be-here"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(EvaluationInputError, match="未知字段"):
        load_release_gate_config(path)


def test_controlled_workflow_contract_is_fail_closed():
    workflow = Path(".github/workflows/real-world-release-gate.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "runs-on: [self-hosted" in workflow
    assert "environment: real-world-evaluation" in workflow
    assert "EVAL_EVIDENCE_HMAC_KEY: ${{ secrets." in workflow
    assert "SECURITY_EVIDENCE_HMAC_KEY: ${{ secrets." in workflow
    assert "python -m evals.real_world_release_gate" in workflow
    assert "if-no-files-found: error" in workflow
    assert "real_world_release_gate.json" in workflow

