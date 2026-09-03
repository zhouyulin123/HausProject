from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from evals import collect_security_access_evidence
from evals.real_world import EvaluationInputError, EvaluationVersions, load_case_manifest
from evals.security_access_attestation import (
    AccessTarget,
    HttpObservation,
    collect_security_access_attestation,
    verify_security_access_attestation,
)
from tests.real_world_fixtures import write_v2_manifest


SECURITY_KEY = "security-suite-key-that-is-at-least-32-bytes"
SECURITY_KEY_ID = "security-regression-v1"
EVALUATION_KEY_ID = "quality-evidence-v1"
BUILD_DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)
VERSIONS = EvaluationVersions(
    model="model-v1",
    prompt="sha256:" + "1" * 64,
    rules="sha256:" + "2" * 64,
    data="sha256:" + "3" * 64,
)


def _dataset(tmp_path):
    cases = []
    for index in (1, 2):
        asset = tmp_path / f"room-{index}.png"
        asset.write_bytes(f"room-{index}".encode())
        cases.append(
            {
                "id": f"private-case-{index}",
                "name": "不得进入公开安全证据",
                "split": "regression",
                "origin": "private_real",
                "asset_path": asset.name,
                "consent_status": "granted",
                "annotation_status": "ready",
                "label_version": "labels-v1",
                "allowed_purposes": ["offline_evaluation"],
                "failure_tags": [],
            }
        )
    return load_case_manifest(
        write_v2_manifest(
            tmp_path,
            filename="manifest.json",
            dataset_version="dataset-v1",
            cases=cases,
        )
    )


class FakeTransport:
    def __init__(self, *, foreign_access: bool = False):
        self.foreign_access = foreign_access
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str]) -> HttpObservation:
        self.calls.append((url, headers))
        if url.endswith("/health"):
            return HttpObservation(
                status_code=200,
                headers={"x-app-build-digest": BUILD_DIGEST},
                json_body={"status": "ok", "environment": "staging"},
            )
        if "/api/sessions/" in url:
            return HttpObservation(
                status_code=200,
                headers={"x-app-build-digest": BUILD_DIGEST},
                json_body={"session_id": url.rsplit("/", 1)[-1], "status": "active"},
            )
        task_id = int(url.split("/api/design/tasks/", 1)[1].split("/", 1)[0])
        session_id = headers["X-Session-ID"]
        is_owner = session_id == f"00000000-0000-0000-0000-{task_id:012d}"
        if is_owner or self.foreign_access:
            return HttpObservation(
                status_code=200,
                headers={"x-app-build-digest": BUILD_DIGEST},
                json_body={"run_id": task_id + 1000, "status": "completed"},
            )
        return HttpObservation(
            status_code=404,
            headers={"x-app-build-digest": BUILD_DIGEST},
            json_body={"detail": "not found"},
        )


def _inputs(dataset):
    targets = []
    credentials = {}
    expected_run_bindings = {}
    for index, case in enumerate(dataset.eligible_cases("regression"), start=1):
        owner_name = f"CASE_{index}_OWNER_SESSION"
        foreign_name = f"CASE_{index}_FOREIGN_SESSION"
        task_id = 100 + index
        credentials[owner_name] = f"00000000-0000-0000-0000-{task_id:012d}"
        credentials[foreign_name] = f"10000000-0000-0000-0000-{task_id:012d}"
        targets.append(
            AccessTarget(
                case_id=case.id,
                task_id=task_id,
                owner_session_env=owner_name,
                foreign_session_env=foreign_name,
            )
        )
        expected_run_bindings[case.id] = (task_id, task_id + 1000)
    return tuple(targets), credentials, expected_run_bindings


def _collect(dataset, *, foreign_access=False):
    targets, credentials, expected_run_bindings = _inputs(dataset)
    payload = collect_security_access_attestation(
        dataset=dataset,
        split="regression",
        targets=targets,
        versions=VERSIONS,
        base_url="https://controlled.example",
        app_build_digest=BUILD_DIGEST,
        credentials=credentials,
        transport=FakeTransport(foreign_access=foreign_access),
        signing_key=SECURITY_KEY,
        key_id=SECURITY_KEY_ID,
        now=NOW,
        ttl_seconds=900,
    )
    return payload, expected_run_bindings, credentials


def _resign(payload):
    unsigned = {key: value for key, value in payload.items() if key != "attestation"}
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    payload["attestation"]["signature"] = "security-hmac-sha256:" + hmac.new(
        SECURITY_KEY.encode("utf-8"),
        encoded,
        hashlib.sha256,
    ).hexdigest()


def _verify(payload, dataset, expected_run_bindings, **overrides):
    kwargs = {
        "payload": payload,
        "dataset": dataset,
        "split": "regression",
        "versions": VERSIONS,
        "expected_app_build_digest": BUILD_DIGEST,
        "expected_run_bindings": expected_run_bindings,
        "verification_keys": {SECURITY_KEY_ID: SECURITY_KEY},
        "evaluation_key_id": EVALUATION_KEY_ID,
        "now": NOW + timedelta(minutes=1),
    }
    kwargs.update(overrides)
    return verify_security_access_attestation(**kwargs)


def _all_mapping_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _all_mapping_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_mapping_keys(nested)


def test_http_suite_signs_only_anonymous_owner_and_foreign_observations(tmp_path):
    dataset = _dataset(tmp_path)
    payload, expected_run_bindings, credentials = _collect(dataset)

    verified = _verify(payload, dataset, expected_run_bindings)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert verified.check_count == 2
    assert verified.severe_count == 0
    assert verified.suite_version == "cross-user-http/1.0"
    assert verified.app_build_digest == BUILD_DIGEST
    assert len(verified.case_results) == 2
    assert all(item.check_count == 1 for item in verified.case_results)
    assert all(item.owner_status == 200 for item in verified.case_results)
    assert all(item.foreign_status == 404 for item in verified.case_results)
    assert all(case.id not in serialized for case in dataset.cases)
    assert all(value not in serialized for value in credentials.values())
    assert {"task_id", "run_id", "session_id"}.isdisjoint(
        set(_all_mapping_keys(payload))
    )


def test_http_suite_records_actual_cross_user_disclosure_as_severe(tmp_path):
    dataset = _dataset(tmp_path)
    payload, expected_run_bindings, _ = _collect(dataset, foreign_access=True)

    verified = _verify(payload, dataset, expected_run_bindings)

    assert verified.check_count == 2
    assert verified.severe_count == 2
    assert all(item.foreign_status == 200 for item in verified.case_results)


def test_http_suite_rejects_missing_eligible_case_target(tmp_path):
    dataset = _dataset(tmp_path)
    targets, credentials, _ = _inputs(dataset)

    with pytest.raises(EvaluationInputError, match="缺少已准入案例"):
        collect_security_access_attestation(
            dataset=dataset,
            split="regression",
            targets=targets[:1],
            versions=VERSIONS,
            base_url="https://controlled.example",
            app_build_digest=BUILD_DIGEST,
            credentials=credentials,
            transport=FakeTransport(),
            signing_key=SECURITY_KEY,
            key_id=SECURITY_KEY_ID,
            now=NOW,
        )


def test_verifier_rejects_forgery_replay_and_wrong_binding(tmp_path):
    dataset = _dataset(tmp_path)
    payload, expected_run_bindings, _ = _collect(dataset)

    forged = json.loads(json.dumps(payload))
    forged["cases"][0]["severe_count"] = 1
    with pytest.raises(EvaluationInputError, match="签名无效"):
        _verify(forged, dataset, expected_run_bindings)

    with pytest.raises(EvaluationInputError, match="过期"):
        _verify(
            payload,
            dataset,
            expected_run_bindings,
            now=NOW + timedelta(minutes=16),
        )

    replayed_run_ids = dict(expected_run_bindings)
    task_id, run_id = replayed_run_ids["private-case-1"]
    replayed_run_ids["private-case-1"] = (task_id, run_id + 1)
    with pytest.raises(EvaluationInputError, match="运行绑定"):
        _verify(payload, dataset, replayed_run_ids)


def test_verifier_rejects_build_version_key_domain_and_case_mismatch(tmp_path):
    dataset = _dataset(tmp_path)
    payload, expected_run_bindings, _ = _collect(dataset)

    with pytest.raises(EvaluationInputError, match="应用构建"):
        _verify(
            payload,
            dataset,
            expected_run_bindings,
            expected_app_build_digest="sha256:" + "b" * 64,
        )
    with pytest.raises(EvaluationInputError, match="评测版本"):
        _verify(
            payload,
            dataset,
            expected_run_bindings,
            versions=replace(VERSIONS, rules="sha256:" + "9" * 64),
        )
    with pytest.raises(EvaluationInputError, match="独立"):
        _verify(
            payload,
            dataset,
            expected_run_bindings,
            evaluation_key_id=SECURITY_KEY_ID,
        )

    missing_case = json.loads(json.dumps(payload))
    missing_case["cases"].pop()
    _resign(missing_case)
    with pytest.raises(EvaluationInputError, match="缺少已准入案例"):
        _verify(missing_case, dataset, expected_run_bindings)


def test_verifier_derives_counts_from_signed_http_statuses(tmp_path):
    dataset = _dataset(tmp_path)
    payload, expected_run_bindings, _ = _collect(dataset)
    fabricated = json.loads(json.dumps(payload))
    fabricated["cases"][0]["check_count"] = 99
    _resign(fabricated)

    with pytest.raises(EvaluationInputError, match="HTTP 事实"):
        _verify(fabricated, dataset, expected_run_bindings)


def test_independent_cli_reads_credentials_from_environment_and_writes_no_secrets(
    tmp_path,
    monkeypatch,
):
    dataset = _dataset(tmp_path)
    targets, credentials, _ = _inputs(dataset)
    target_file = tmp_path / "security-targets.json"
    target_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "split": "regression",
                "versions": VERSIONS.__dict__,
                "targets": [target.__dict__ for target in targets],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "security-evidence.json"
    monkeypatch.setenv("SECURITY_EVIDENCE_HMAC_KEY", SECURITY_KEY)
    monkeypatch.setenv("SECURITY_EVIDENCE_KEY_ID", SECURITY_KEY_ID)
    for name, value in credentials.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        collect_security_access_evidence,
        "UrllibHttpTransport",
        lambda **_: FakeTransport(),
    )

    exit_code = collect_security_access_evidence.main(
        [
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--split",
            "regression",
            "--targets",
            str(target_file),
            "--base-url",
            "https://controlled.example",
            "--app-build-digest",
            BUILD_DIGEST,
            "--output",
            str(output),
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert exit_code == 0
    assert payload["attestation"]["key_id"] == SECURITY_KEY_ID
    assert all(value not in serialized for value in credentials.values())
    assert all(case.id not in serialized for case in dataset.cases)
