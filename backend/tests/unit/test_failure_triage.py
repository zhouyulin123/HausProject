import json
from pathlib import Path

import pytest

from evals.failure_triage import (
    FailureTriageInputError,
    build_failure_triage_report,
    load_failure_triage_evidence,
    render_failure_triage_markdown,
)
from evals.real_world import RealWorldCase, RealWorldDataset
from evals.run_failure_triage import main as run_failure_triage_main


def _case(
    case_id: str,
    *,
    split: str,
    eligible: bool = True,
) -> RealWorldCase:
    return RealWorldCase(
        id=case_id,
        name=f"案例 {case_id}",
        split=split,
        origin="private_real",
        asset_path=Path(f"{case_id}.png"),
        consent_status="granted" if eligible else "pending",
        annotation_status="ready",
        label_version="labels-1",
        allowed_purposes=("offline_evaluation",),
        failure_tags=(),
    )


def _dataset() -> RealWorldDataset:
    return RealWorldDataset(
        schema_version="1.0",
        dataset_version="data-1",
        cases=(
            _case("case-a", split="development"),
            _case("case-b", split="regression"),
            _case("case-c", split="blind"),
            _case("case-pending", split="unassigned", eligible=False),
        ),
    )


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _failure(
    case_id: str,
    code: str,
    failure_type: str,
    severity: str,
    *,
    tags: list[str] | None = None,
    metrics: list[str] | None = None,
) -> dict:
    return {
        "case_id": case_id,
        "code": code,
        "failure_type": failure_type,
        "severity": severity,
        "tags": tags or [],
        "metrics": metrics or [],
    }


def _payload(failures: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "taxonomy_version": "1.0",
        "data_version": "data-1",
        "failures": failures,
    }


def test_triage_aggregates_structured_failures_deterministically_and_anonymizes_ids(
    tmp_path,
):
    evidence_path = _write_json(
        tmp_path / "failures.json",
        _payload(
            [
                _failure(
                    "case-b",
                    "layout_collision",
                    "layout",
                    "high",
                    tags=["collision", "hard_constraint"],
                    metrics=["layout_hard_constraint_pass_rate"],
                ),
                _failure(
                    "case-a",
                    "layout_collision",
                    "layout",
                    "high",
                    tags=["collision"],
                    metrics=["layout_hard_constraint_pass_rate"],
                ),
                _failure(
                    "case-b",
                    "invalid_sku",
                    "catalog",
                    "critical",
                    tags=["catalog"],
                    metrics=["valid_sku_rate"],
                ),
                _failure(
                    "case-c",
                    "budget_exceeded",
                    "budget",
                    "medium",
                    tags=["budget"],
                    metrics=["budget_compliance_rate"],
                ),
            ]
        ),
    )
    dataset = _dataset()
    evidence = load_failure_triage_evidence(evidence_path, dataset=dataset)

    first = build_failure_triage_report(
        dataset=dataset,
        evidence=evidence,
        anonymization_salt="test-salt-at-least-16-bytes",
        salt_id="test-key-v1",
    )
    second = build_failure_triage_report(
        dataset=dataset,
        evidence=evidence,
        anonymization_salt="test-salt-at-least-16-bytes",
        salt_id="test-key-v1",
    )

    assert first == second
    assert first["schema_version"] == "1.0"
    assert first["input"] == {
        "schema_version": "1.0",
        "taxonomy_version": "1.0",
        "data_version": "data-1",
    }
    assert first["summary"] == {
        "eligible_case_count": 3,
        "failure_count": 4,
        "affected_case_count": 3,
    }
    assert [item["failure_type"] for item in first["by_failure_type"]] == [
        "budget",
        "catalog",
        "layout",
    ]
    assert [item["severity"] for item in first["by_severity"]] == [
        "critical",
        "high",
        "medium",
    ]
    assert [item["split"] for item in first["by_split"]] == [
        "development",
        "regression",
        "blind",
    ]
    assert first["clusters"][0]["code"] == "invalid_sku"
    layout_cluster = next(
        item for item in first["clusters"] if item["code"] == "layout_collision"
    )
    assert layout_cluster["failure_count"] == 2
    assert layout_cluster["affected_case_count"] == 2
    assert layout_cluster["tag_counts"] == {
        "collision": 2,
        "hard_constraint": 1,
    }
    assert layout_cluster["metric_counts"] == {
        "layout_hard_constraint_pass_rate": 2,
    }
    serialized = json.dumps(first, ensure_ascii=False)
    assert all(
        raw_id not in serialized
        for raw_id in ("case-a", "case-b", "case-c", "case-pending")
    )
    aliases = {
        case_id
        for cluster in first["clusters"]
        for case_id in cluster["case_ids"]
    }
    assert len(aliases) == 3
    assert all(alias.startswith("case-") and len(alias) == 21 for alias in aliases)


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"schema_version": "2.0"}, "schema_version"),
        (_payload([]) | {"taxonomy_version": "2.0"}, "taxonomy_version"),
        (_payload([]) | {"data_version": "data-2"}, "数据版本不一致"),
        (
            _payload(
                [
                    _failure(
                        "unknown",
                        "invalid_sku",
                        "catalog",
                        "critical",
                    )
                ]
            ),
            "未准入或不存在",
        ),
        (
            _payload(
                [
                    _failure(
                        "case-pending",
                        "invalid_sku",
                        "catalog",
                        "critical",
                    )
                ]
            ),
            "未准入或不存在",
        ),
    ],
)
def test_triage_rejects_incompatible_versions_and_noneligible_cases(
    tmp_path,
    payload,
    expected,
):
    path = _write_json(tmp_path / "failures.json", payload)

    with pytest.raises(FailureTriageInputError, match=expected):
        load_failure_triage_evidence(path, dataset=_dataset())


@pytest.mark.parametrize(
    "failure, expected",
    [
        (
            _failure("case-a", "invalid_sku", "catalog", "critical")
            | {"message": "这段自由文本不应参与分类"},
            "未知字段",
        ),
        (
            _failure(
                "case-a",
                "invalid_sku",
                "catalog",
                "critical",
                tags=["沙发撞门"],
            ),
            "tags",
        ),
        (
            _failure("case-a", "invalid_sku", "catalog", "urgent"),
            "severity",
        ),
    ],
)
def test_triage_never_classifies_free_text_or_unknown_fields(
    tmp_path,
    failure,
    expected,
):
    path = _write_json(tmp_path / "failures.json", _payload([failure]))

    with pytest.raises(FailureTriageInputError, match=expected):
        load_failure_triage_evidence(path, dataset=_dataset())


def test_triage_rejects_duplicate_case_code_pairs(tmp_path):
    failure = _failure("case-a", "invalid_sku", "catalog", "critical")
    path = _write_json(
        tmp_path / "failures.json",
        _payload([failure, failure]),
    )

    with pytest.raises(FailureTriageInputError, match="重复失败记录"):
        load_failure_triage_evidence(path, dataset=_dataset())


def _write_manifest(tmp_path: Path) -> Path:
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.png").write_bytes(name.encode())
    return _write_json(
        tmp_path / "manifest.json",
        {
            "schema_version": "1.0",
            "dataset_version": "data-1",
            "cases": [
                {
                    "id": f"case-{name}",
                    "name": f"脱敏案例 {name}",
                    "split": split,
                    "origin": "private_real",
                    "asset_path": f"{name}.png",
                    "consent_status": "granted",
                    "annotation_status": "ready",
                    "label_version": "labels-1",
                    "allowed_purposes": ["offline_evaluation"],
                    "failure_tags": [],
                }
                for name, split in (
                    ("a", "development"),
                    ("b", "regression"),
                    ("c", "blind"),
                )
            ],
        },
    )


def test_failure_triage_cli_exit_codes_and_outputs(tmp_path, monkeypatch):
    manifest = _write_manifest(tmp_path)
    empty_input = _write_json(tmp_path / "empty.json", _payload([]))
    failed_input = _write_json(
        tmp_path / "failed.json",
        _payload(
            [
                _failure(
                    "case-a",
                    "invalid_sku",
                    "catalog",
                    "critical",
                    metrics=["valid_sku_rate"],
                )
            ]
        ),
    )
    monkeypatch.setenv("EVAL_CASE_ID_SALT", "test-salt-at-least-16-bytes")

    empty_code = run_failure_triage_main(
        [
            "--manifest",
            str(manifest),
            "--failures",
            str(empty_input),
            "--output-dir",
            str(tmp_path / "empty-report"),
        ]
    )
    failed_code = run_failure_triage_main(
        [
            "--manifest",
            str(manifest),
            "--failures",
            str(failed_input),
            "--output-dir",
            str(tmp_path / "failed-report"),
        ]
    )

    assert empty_code == 0
    assert failed_code == 1
    report = json.loads(
        (tmp_path / "failed-report" / "failure_triage.json").read_text(
            encoding="utf-8"
        )
    )
    markdown = (
        tmp_path / "failed-report" / "failure_triage.md"
    ).read_text(encoding="utf-8")
    assert report["summary"]["failure_count"] == 1
    assert "invalid_sku" in markdown
    assert "case-a" not in markdown

    monkeypatch.delenv("EVAL_CASE_ID_SALT")
    invalid_code = run_failure_triage_main(
        [
            "--manifest",
            str(manifest),
            "--failures",
            str(empty_input),
            "--output-dir",
            str(tmp_path / "invalid-report"),
        ]
    )
    assert invalid_code == 2
    assert not (tmp_path / "invalid-report").exists()


def test_triage_markdown_contains_structured_dimensions_only(tmp_path):
    path = _write_json(
        tmp_path / "failures.json",
        _payload(
            [
                _failure(
                    "case-a",
                    "invalid_sku",
                    "catalog",
                    "critical",
                    tags=["catalog"],
                    metrics=["valid_sku_rate"],
                )
            ]
        ),
    )
    evidence = load_failure_triage_evidence(path, dataset=_dataset())
    report = build_failure_triage_report(
        dataset=_dataset(),
        evidence=evidence,
        anonymization_salt="test-salt-at-least-16-bytes",
        salt_id="test-key-v1",
    )

    markdown = render_failure_triage_markdown(report)

    assert "失败类型" in markdown
    assert "严重度" in markdown
    assert "数据切分" in markdown
    assert "catalog" in markdown
    assert "critical" in markdown
    assert "development" in markdown
