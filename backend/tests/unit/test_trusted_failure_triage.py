import json
from pathlib import Path

import pytest

from evals.failure_triage import (
    FailureTriageInputError,
    build_failure_triage_report,
    derive_failure_triage_evidence,
    load_trusted_failure_evidence,
)
from evals.real_world import (
    CaseResult,
    EvaluationVersions,
    RealWorldCase,
    RealWorldDataset,
)
from evals.trusted_evidence import (
    ExecutionProvenance,
    VerifiedEvaluationEvidence,
    _case_fingerprint,
)


def _dataset() -> RealWorldDataset:
    return RealWorldDataset(
        schema_version="2.0",
        dataset_version="dataset-v2",
        cases=(
            RealWorldCase(
                id="case-private-a",
                name="匿名案例",
                split="regression",
                origin="private_real",
                asset_path=Path("room-a.png"),
                consent_status="granted",
                annotation_status="ready",
                label_version="labels-v2",
                allowed_purposes=("offline_evaluation",),
                failure_tags=(),
            ),
        ),
    )


def _verified_evidence(*, signature_verified: bool = True):
    output_digest = "sha256:" + "a" * 64
    return VerifiedEvaluationEvidence(
        schema_version="4.0",
        versions=EvaluationVersions(
            model="model-v1",
            prompt="sha256:" + "1" * 64,
            rules="sha256:" + "2" * 64,
            data="sha256:" + "3" * 64,
        ),
        dataset_fingerprint="sha256:" + "4" * 64,
        evidence_digest="sha256:" + "5" * 64,
        split="regression",
        results=(
            CaseResult(
                case_id="case-private-a",
                recommended_skus=2,
                valid_skus=1,
                layout_checks=2,
                layout_hard_passes=1,
                generation_succeeded=True,
            ),
        ),
        executions=(
            ExecutionProvenance(
                case_fingerprint=_case_fingerprint(
                    "sha256:" + "4" * 64,
                    "case-private-a",
                ),
                execution_ref="exec-hmac-sha256:" + "7" * 64,
                source="generation_worker",
                generator="llm",
                status="completed",
                model="model-v1",
                prompt_digest="sha256:" + "1" * 64,
                rules_digest="sha256:" + "2" * 64,
                data_digest="sha256:" + "3" * 64,
                input_digest="sha256:" + "8" * 64,
                output_digest=output_digest,
                result_digest="sha256:" + "9" * 64,
            ),
        ),
        key_id="quality-key-v1",
        signature_verified=signature_verified,
    )


def test_triage_is_derived_from_verified_metrics_and_binds_source_digests():
    dataset = _dataset()
    failures = derive_failure_triage_evidence(
        evidence=_verified_evidence(),
        dataset=dataset,
    )

    report = build_failure_triage_report(
        dataset=dataset,
        evidence=failures,
        anonymization_salt="test-case-key-at-least-16-bytes",
        salt_id="case-key-v1",
    )

    assert {item.code for item in failures.failures} == {
        "invalid_sku",
        "layout_hard_constraint_failed",
    }
    assert report["input"] == {
        "schema_version": "4.0",
        "taxonomy_version": "2.0",
        "data_version": "dataset-v2",
        "manifest_digest": "sha256:" + "4" * 64,
        "evidence_digest": "sha256:" + "5" * 64,
        "output_digests": ["sha256:" + "a" * 64],
    }
    assert all(
        cluster["execution_refs"] == ["exec-hmac-sha256:" + "7" * 64]
        for cluster in report["clusters"]
    )
    assert all(
        cluster["output_digests"] == ["sha256:" + "a" * 64]
        for cluster in report["clusters"]
    )


def test_triage_rejects_unverified_objects_and_legacy_self_reported_files(tmp_path):
    with pytest.raises(FailureTriageInputError, match="已验签"):
        derive_failure_triage_evidence(
            evidence=_verified_evidence(signature_verified=False),
            dataset=_dataset(),
        )

    legacy = tmp_path / "legacy-failures.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "taxonomy_version": "1.0",
                "data_version": "dataset-v2",
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(FailureTriageInputError, match="可信评测证据"):
        load_trusted_failure_evidence(
            legacy,
            dataset=_dataset(),
            split="regression",
            verification_keys={"quality-key-v1": "x" * 32},
        )
