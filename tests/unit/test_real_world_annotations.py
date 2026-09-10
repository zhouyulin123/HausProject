from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from evals.annotations import (
    ANNOTATION_SCHEMA_VERSION,
    AnnotationValidationError,
    load_case_annotation,
    load_execution_review,
)
from evals.real_world import (
    DatasetValidationError,
    RealWorldCase,
    RealWorldDataset,
    load_case_manifest,
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _dataset(tmp_path: Path, **case_overrides) -> RealWorldDataset:
    asset = tmp_path / "assets" / "room.png"
    asset.parent.mkdir(exist_ok=True)
    asset.write_bytes(b"deidentified-room")
    values = {
        "id": "real-case-001",
        "name": "脱敏案例",
        "split": "regression",
        "origin": "private_real",
        "asset_path": asset,
        "asset_sha256": _sha256(asset.read_bytes()),
        "consent_status": "granted",
        "annotation_status": "ready",
        "label_version": "labels-2026-09-02.1",
        "allowed_purposes": ("offline_evaluation",),
        "failure_tags": (),
        "task_input": {
            "raw_user_input": "设计一个已脱敏的测试客厅",
            "confirmed_requirement": {"space_type": "客厅"},
            "space_type": "客厅",
            "style": None,
            "budget_min": None,
            "budget_max": None,
            "image_context": ["已脱敏空间事实"],
        },
    }
    values.update(case_overrides)
    case = RealWorldCase(**values)
    return RealWorldDataset(
        schema_version="1.0",
        dataset_version="2026-09-02.1",
        cases=(case,),
    )


def _payload(dataset: RealWorldDataset) -> dict:
    case = dataset.cases[0]
    return {
        "schema_version": "1.0",
        "annotation_type": "real_world_case_annotation",
        "case_id": case.id,
        "label_version": case.label_version,
        "source_asset_sha256": case.asset_sha256,
        "requirements": [
            {"field": "space_type", "value": "客厅"},
            {"field": "occupant_count", "value": 3},
            {"field": "has_children", "value": True},
        ],
        "space_facts": [
            {
                "fact_path": "rooms.living.width_m",
                "value": 4.2,
                "confidence": 1.0,
                "requires_confirmation": False,
            },
            {
                "fact_path": "rooms.living.window_count",
                "value": 2,
                "confidence": 0.6,
                "requires_confirmation": True,
            },
        ],
        "allowed_skus": ["SOFA-001", "TABLE-001"],
        "budget": {"currency": "CNY", "min": 10000, "max": 30000},
        "layout_hard_constraints": [
            {
                "constraint_id": "walkway-main",
                "type": "minimum_clearance",
                "room_id": "living",
                "subject_id": "walkway-main",
                "related_id": None,
                "operator": "gte",
                "value": 800,
                "unit": "mm",
            },
            {
                "constraint_id": "sofa-inside-room",
                "type": "inside_room",
                "room_id": "living",
                "subject_id": "sofa-main",
                "related_id": None,
                "operator": "eq",
                "value": True,
                "unit": "boolean",
            },
        ],
        "style_tags": ["现代简约", "原木"],
    }


def _review_payload(dataset: RealWorldDataset, *, output_digest: str) -> dict:
    case = dataset.cases[0]
    return {
        "schema_version": "1.0",
        "review_type": "real_world_execution_review",
        "case_id": case.id,
        "label_version": case.label_version,
        "output_digest": output_digest,
        "reviewer_role": "designer",
        "overall_rating": 4,
        "dimension_scores": [
            {"metric": "functional_fit", "score": 5},
            {"metric": "style_match", "score": 4},
        ],
        "edit_facts": [
            {
                "edit_id": "edit-001",
                "action": "move",
                "target_type": "furniture",
                "target_id": "sofa-main",
                "axis": "x",
                "delta_mm": 200,
                "delta_degrees": None,
                "replacement_sku": None,
                "quantity_delta": None,
            },
            {
                "edit_id": "edit-002",
                "action": "replace",
                "target_type": "furniture",
                "target_id": "table-main",
                "axis": None,
                "delta_mm": None,
                "delta_degrees": None,
                "replacement_sku": "TABLE-002",
                "quantity_delta": None,
            },
        ],
    }


def _write_annotation(tmp_path: Path, payload: dict) -> Path:
    annotation_dir = tmp_path / "annotations"
    annotation_dir.mkdir(exist_ok=True)
    path = annotation_dir / "real-case-001.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=True),
        encoding="utf-8",
    )
    return path


def _write_v2_manifest(
    tmp_path: Path,
    *,
    annotation_path: str | None,
    annotation_sha256: str | None,
) -> Path:
    manifest = {
        "schema_version": "2.0",
        "dataset_version": "2026-09-02.2",
        "cases": [
            {
                "id": "real-case-001",
                "name": "脱敏案例",
                "split": "regression",
                "origin": "private_real",
                "asset_path": "assets/room.png",
                "consent_status": "granted",
                "annotation_status": "ready",
                "label_version": "labels-2026-09-02.1",
                "allowed_purposes": ["offline_evaluation"],
                "failure_tags": [],
                "task_input": {
                    "raw_user_input": "设计一个已脱敏的测试客厅",
                    "confirmed_requirement": {"space_type": "客厅"},
                    "space_type": "客厅",
                    "style": None,
                    "budget_min": None,
                    "budget_max": None,
                    "image_context": ["已脱敏空间事实"],
                },
                "annotation_path": annotation_path,
                "annotation_sha256": annotation_sha256,
            }
        ],
    }
    path = tmp_path / "manifest-v2.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def test_v2_manifest_loads_and_freezes_ready_annotation_asset(tmp_path):
    seed_dataset = _dataset(tmp_path)
    annotation_path = _write_annotation(tmp_path, _payload(seed_dataset))
    annotation_sha256 = _sha256(annotation_path.read_bytes())
    manifest_path = _write_v2_manifest(
        tmp_path,
        annotation_path="annotations/real-case-001.json",
        annotation_sha256=annotation_sha256,
    )

    dataset = load_case_manifest(manifest_path)
    case = dataset.eligible_cases("regression")[0]

    assert case.annotation is not None
    assert case.annotation.file_sha256 == annotation_sha256
    assert case.annotation_sha256 == annotation_sha256
    assert case.annotation.content_fingerprint.startswith("sha256:")
    assert dataset.fingerprint.startswith("sha256:")


@pytest.mark.parametrize(
    ("annotation_path", "annotation_sha256"),
    [
        (None, None),
        ("annotations/real-case-001.json", None),
        (None, "0" * 64),
    ],
)
def test_v2_manifest_rejects_ready_case_without_frozen_annotation_reference(
    tmp_path,
    annotation_path,
    annotation_sha256,
):
    _dataset(tmp_path)
    path = _write_v2_manifest(
        tmp_path,
        annotation_path=annotation_path,
        annotation_sha256=annotation_sha256,
    )

    with pytest.raises(DatasetValidationError, match="annotation_path|annotation_sha256"):
        load_case_manifest(path)


def test_loads_complete_annotation_and_freezes_file_digest(tmp_path):
    dataset = _dataset(tmp_path)
    path = _write_annotation(tmp_path, _payload(dataset))
    file_digest = _sha256(path.read_bytes())

    annotation = load_case_annotation(
        path,
        dataset=dataset,
        dataset_root=tmp_path,
        expected_sha256=file_digest,
    )

    assert ANNOTATION_SCHEMA_VERSION == "1.0"
    assert annotation.case_id == "real-case-001"
    assert annotation.label_version == "labels-2026-09-02.1"
    assert annotation.file_sha256 == file_digest
    assert annotation.source_asset_sha256 == dataset.cases[0].asset_sha256
    assert [fact.field for fact in annotation.requirements] == [
        "has_children",
        "occupant_count",
        "space_type",
    ]
    assert [fact.fact_path for fact in annotation.space_facts] == [
        "rooms.living.width_m",
        "rooms.living.window_count",
    ]
    assert annotation.allowed_skus == ("SOFA-001", "TABLE-001")
    assert annotation.budget.currency == "CNY"
    assert annotation.budget.minimum == 10000
    assert annotation.budget.maximum == 30000
    assert annotation.style_tags == ("原木", "现代简约")
    assert annotation.content_fingerprint.startswith("sha256:")


def test_semantic_fingerprint_is_independent_of_set_like_input_order(tmp_path):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    first_path = _write_annotation(tmp_path, payload)
    first = load_case_annotation(
        first_path,
        dataset=dataset,
        dataset_root=tmp_path,
    )

    for field in (
        "requirements",
        "space_facts",
        "allowed_skus",
        "layout_hard_constraints",
        "style_tags",
    ):
        payload[field].reverse()
    second_path = _write_annotation(tmp_path, payload)
    second = load_case_annotation(
        second_path,
        dataset=dataset,
        dataset_root=tmp_path,
    )

    assert first.file_sha256 != second.file_sha256
    assert first.content_fingerprint == second.content_fingerprint


@pytest.mark.parametrize(
    ("dataset_overrides", "payload_override", "error"),
    [
        ({}, {"case_id": "unknown-case"}, "case_id"),
        ({}, {"label_version": "labels-other"}, "label_version"),
        ({}, {"source_asset_sha256": "0" * 64}, "资产 SHA-256"),
        ({"annotation_status": "pending"}, {}, "尚未 ready"),
    ],
)
def test_cross_checks_manifest_identity_and_readiness(
    tmp_path,
    dataset_overrides,
    payload_override,
    error,
):
    dataset = _dataset(tmp_path, **dataset_overrides)
    payload = _payload(dataset)
    payload.update(payload_override)
    path = _write_annotation(tmp_path, payload)

    with pytest.raises(AnnotationValidationError, match=error):
        load_case_annotation(path, dataset=dataset, dataset_root=tmp_path)


def test_rejects_annotation_path_outside_dataset_root(tmp_path):
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    dataset = _dataset(dataset_root)
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps(_payload(dataset), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(AnnotationValidationError, match="数据集目录之外"):
        load_case_annotation(
            outside,
            dataset=dataset,
            dataset_root=dataset_root,
        )


def test_rejects_changed_annotation_file_digest(tmp_path):
    dataset = _dataset(tmp_path)
    path = _write_annotation(tmp_path, _payload(dataset))

    with pytest.raises(AnnotationValidationError, match="文件 SHA-256"):
        load_case_annotation(
            path,
            dataset=dataset,
            dataset_root=tmp_path,
            expected_sha256="f" * 64,
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("schema_version", "2.0", "schema_version"),
        ("annotation_type", "free_form", "annotation_type"),
        ("unexpected", True, "未知字段"),
        ("file_sha256", "0" * 64, "未知字段"),
    ],
)
def test_rejects_unknown_schema_or_fields(tmp_path, field, value, error):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    payload[field] = value

    with pytest.raises(AnnotationValidationError, match=error):
        load_case_annotation(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
        )


def test_rejects_duplicate_json_object_keys(tmp_path):
    dataset = _dataset(tmp_path)
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":"1.0","schema_version":"1.0"}',
        encoding="utf-8",
    )

    with pytest.raises(AnnotationValidationError, match="重复键"):
        load_case_annotation(path, dataset=dataset, dataset_root=tmp_path)


@pytest.mark.parametrize("invalid_number", [float("nan"), float("inf"), 1e400])
def test_rejects_nan_and_infinite_numbers(tmp_path, invalid_number):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    payload["space_facts"][0]["value"] = invalid_number

    with pytest.raises(AnnotationValidationError, match="有限数值"):
        load_case_annotation(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["requirements"].append(
            deepcopy(value["requirements"][0])
        ),
        lambda value: value["space_facts"].append(
            deepcopy(value["space_facts"][0])
        ),
        lambda value: value["allowed_skus"].append(value["allowed_skus"][0]),
        lambda value: value["layout_hard_constraints"].append(
            deepcopy(value["layout_hard_constraints"][0])
        ),
        lambda value: value["style_tags"].append(value["style_tags"][0]),
    ],
)
def test_rejects_duplicate_structured_facts(tmp_path, mutator):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    mutator(payload)

    with pytest.raises(AnnotationValidationError, match="重复"):
        load_case_annotation(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
        )


@pytest.mark.parametrize(
    "field_path",
    [
        ("style_tags", 0),
        ("allowed_skus", 0),
        ("requirements", 0, "value"),
        ("layout_hard_constraints", 0, "subject_id"),
    ],
)
def test_rejects_empty_labels(tmp_path, field_path):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    target = payload
    for part in field_path[:-1]:
        target = target[part]
    target[field_path[-1]] = "  "

    with pytest.raises(AnnotationValidationError, match="不能为空"):
        load_case_annotation(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
        )


@pytest.mark.parametrize("pii_field", ["raw_user_input", "phone", "email", "notes"])
def test_rejects_raw_free_text_and_pii_fields(tmp_path, pii_field):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    payload[pii_field] = "不应进入标注资产"

    with pytest.raises(AnnotationValidationError, match="PII|自由文本"):
        load_case_annotation(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
        )


@pytest.mark.parametrize(
    "budget",
    [
        {"currency": "USD", "min": 10000, "max": 30000},
        {"currency": "CNY", "min": -1, "max": 30000},
        {"currency": "CNY", "min": 30001, "max": 30000},
        {"currency": "CNY", "min": 10000.5, "max": 30000},
    ],
)
def test_rejects_invalid_budget_contract(tmp_path, budget):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    payload["budget"] = budget

    with pytest.raises(AnnotationValidationError, match="budget"):
        load_case_annotation(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", 1.1),
        ("confidence", -0.1),
        ("requires_confirmation", 1),
        ("fact_path", "rooms/living/width"),
    ],
)
def test_rejects_invalid_space_fact_contract(tmp_path, field, value):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    payload["space_facts"][0][field] = value

    with pytest.raises(AnnotationValidationError, match="space_facts"):
        load_case_annotation(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", "free_text_rule"),
        ("operator", "contains"),
        ("unit", "pixels"),
        ("value", "800mm"),
    ],
)
def test_rejects_invalid_layout_constraint_contract(tmp_path, field, value):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    payload["layout_hard_constraints"][0][field] = value

    with pytest.raises(AnnotationValidationError, match="layout_hard_constraints"):
        load_case_annotation(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
        )


def test_case_annotation_rejects_run_dependent_human_evaluation(tmp_path):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    payload["human_evaluation"] = {
        "overall_rating": 5,
        "dimension_scores": [],
        "edit_facts": [],
    }

    with pytest.raises(AnnotationValidationError, match="未知字段"):
        load_case_annotation(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
        )


@pytest.mark.parametrize("constraint_type", ["walkway_width", "maximum_occupancy"])
def test_rejects_layout_constraints_without_frozen_scene_evidence(
    tmp_path,
    constraint_type,
):
    dataset = _dataset(tmp_path)
    payload = _payload(dataset)
    payload["layout_hard_constraints"][0]["type"] = constraint_type

    with pytest.raises(
        AnnotationValidationError,
        match="无法由冻结 SceneDocument 确定性评估",
    ):
        load_case_annotation(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
        )


def test_execution_review_is_bound_to_exact_output_digest(tmp_path):
    dataset = _dataset(tmp_path)
    output_digest = "sha256:" + "a" * 64
    path = _write_annotation(tmp_path, _review_payload(dataset, output_digest=output_digest))

    review = load_execution_review(
        path,
        dataset=dataset,
        dataset_root=tmp_path,
        expected_output_digest=output_digest,
    )

    assert review.case_id == dataset.cases[0].id
    assert review.output_digest == output_digest
    assert review.reviewer_role == "designer"
    assert review.overall_rating == 4
    assert review.content_fingerprint.startswith("sha256:")

    with pytest.raises(AnnotationValidationError, match="输出 SHA-256"):
        load_execution_review(
            path,
            dataset=dataset,
            dataset_root=tmp_path,
            expected_output_digest="sha256:" + "b" * 64,
        )


@pytest.mark.parametrize(
    ("action", "field", "value"),
    [
        ("move", "delta_mm", None),
        ("rotate", "delta_degrees", None),
        ("replace", "replacement_sku", None),
        ("quantity", "quantity_delta", 0),
        ("invent", "delta_mm", 1),
    ],
)
def test_execution_review_rejects_incomplete_or_unknown_edit_facts(
    tmp_path,
    action,
    field,
    value,
):
    dataset = _dataset(tmp_path)
    output_digest = "sha256:" + "a" * 64
    payload = _review_payload(dataset, output_digest=output_digest)
    edit = payload["edit_facts"][0]
    edit["action"] = action
    edit[field] = value

    with pytest.raises(AnnotationValidationError, match="edit_facts"):
        load_execution_review(
            _write_annotation(tmp_path, payload),
            dataset=dataset,
            dataset_root=tmp_path,
            expected_output_digest=output_digest,
        )
