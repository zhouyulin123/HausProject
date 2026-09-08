from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import (
    DesignScene,
    DesignSceneVersion,
    DesignTask,
    GenerationRunEvent,
    UploadedImage,
)
from app.services import design_version_service, generation_run_service
from evals.real_world import (
    DatasetValidationError,
    EvaluationInputError,
    load_case_manifest,
)
from evals.trusted_evidence import (
    RunBinding,
    bind_evaluation_run,
    collect_trusted_evidence,
)
from tests.real_world_fixtures import write_v2_manifest


SIGNING_KEY = "output-evidence-test-key-at-least-32-bytes"


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _dataset(tmp_path: Path, *, constraint_type: str = "inside_room"):
    (tmp_path / "room.png").write_bytes(b"deidentified-room")
    manifest = write_v2_manifest(
        tmp_path,
        filename="manifest.json",
        dataset_version="output-contract-v1",
        cases=[
            {
                "id": "case-output-001",
                "name": "匿名案例",
                "split": "regression",
                "origin": "private_real",
                "asset_path": "room.png",
                "consent_status": "granted",
                "annotation_status": "ready",
                "label_version": "labels-v1",
                "allowed_purposes": ["offline_evaluation"],
                "failure_tags": [],
                "task_input": {
                    "raw_user_input": "需要现代客厅",
                    "confirmed_requirement": {
                        "space_type": "客厅",
                        "style": "现代",
                    },
                    "space_type": "客厅",
                    "style": "现代",
                    "budget_min": 10000,
                    "budget_max": 20000,
                },
            }
        ],
    )
    if constraint_type != "inside_room":
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        annotation_path = tmp_path / manifest_payload["cases"][0]["annotation_path"]
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        constraint = annotation["layout_hard_constraints"][0]
        constraint.update(
            {
                "constraint_id": "walkway-main",
                "type": constraint_type,
                "subject_id": "walkway-main",
                "operator": "gte",
                "value": 800,
                "unit": "mm",
            }
        )
        annotation_path.write_text(
            json.dumps(annotation, ensure_ascii=False),
            encoding="utf-8",
        )
        manifest_payload["cases"][0]["annotation_sha256"] = hashlib.sha256(
            annotation_path.read_bytes()
        ).hexdigest()
        manifest.write_text(
            json.dumps(manifest_payload, ensure_ascii=False),
            encoding="utf-8",
        )
    return load_case_manifest(manifest)


def _eligibility_snapshot(sku: str, *, quantity: int, unit_price: int) -> dict:
    return {
        "schemaVersion": "1.0",
        "eligible": True,
        "reasonCodes": [],
        "checkedAt": "2026-09-01T00:00:00+00:00",
        "sku": sku,
        "quantity": quantity,
        "unitPrice": unit_price,
        "dataVersion": "catalog-data-v1",
        "recordVersion": 1,
        "policy": {
            "region": None,
            "allowDraft": False,
            "maxUnitPrice": 20000,
            "maxDimensionsMm": {},
        },
        "facts": {
            "isActive": True,
            "dataOrigin": "merchant_verified",
            "verificationStatus": "verified",
            "availabilityStatus": "in_stock",
            "stockQuantity": 10,
            "leadTimeDaysMin": None,
            "leadTimeDaysMax": None,
            "priceValidFrom": "2026-01-01T00:00:00+00:00",
            "priceValidTo": "2027-01-01T00:00:00+00:00",
            "regionCodes": [],
            "dimensionsMm": {"width": 1000, "depth": 800, "height": 900},
        },
    }


def _plan(
    *,
    model_reports_passed: bool = True,
    include_catalog_evidence: bool = True,
) -> dict:
    suggestions = [
        {
            "id": "SOFA-001",
            "sku": "SOFA-001",
            "quantity": 1,
            "unitPrice": 9000,
            "dataVersion": "catalog-data-v1",
            "recordVersion": 1,
        },
        {
            "id": "LAMP-OUTSIDE",
            "sku": "LAMP-OUTSIDE",
            "quantity": 1,
            "unitPrice": 1000,
            "dataVersion": "catalog-data-v1",
            "recordVersion": 1,
        },
    ]
    if include_catalog_evidence:
        suggestions[0]["catalogEligibility"] = _eligibility_snapshot(
            "SOFA-001", quantity=1, unit_price=9000
        )
        suggestions[1]["catalogEligibility"] = _eligibility_snapshot(
            "LAMP-OUTSIDE", quantity=1, unit_price=1000
        )
    return {
        "id": "plan-a",
        "name": "真实输出方案",
        "style": "现代",
        "furnitureSuggestions": suggestions,
        "layoutConstraintResults": [
            {"constraintId": "inside-room", "passed": model_reports_passed}
        ],
        "shopQuote": {
            "currency": "CNY",
            "furnitureTotal": 10000,
            "customTotal": 0,
            "total": 10000,
            "lineItems": [
                {
                    "sku": "SOFA-001",
                    "quantity": 1,
                    "unitPrice": 9000,
                    "dataVersion": "catalog-data-v1",
                    "recordVersion": 1,
                },
                {
                    "sku": "LAMP-OUTSIDE",
                    "quantity": 1,
                    "unitPrice": 1000,
                    "dataVersion": "catalog-data-v1",
                    "recordVersion": 1,
                },
            ],
            "customLineItems": [],
            "catalogVersion": "catalog-v1",
            "priceVersion": "price-v1",
            "ruleVersion": "rules-v1",
        },
    }


def _scene_document(*, x: float) -> dict:
    return {
        "schemaVersion": "1.0",
        "unit": "m",
        "coordinateSystem": "right-handed-y-up",
        "room": {
            "id": "living",
            "name": "客厅",
            "floorPolygon": [
                {"x": -2, "z": -2},
                {"x": 2, "z": -2},
                {"x": 2, "z": 2},
                {"x": -2, "z": 2},
            ],
            "ceilingHeight": 2.8,
            "wallThickness": 0.12,
        },
        "openings": [],
        "items": [
            {
                "instanceId": "sofa-main",
                "sku": "SOFA-001",
                "category": "沙发",
                "transform": {
                    "position": {"x": x, "y": 0.45, "z": 0},
                    "rotation": {"x": 0, "y": 0, "z": 0},
                    "scale": {"x": 1, "y": 1, "z": 1},
                },
                "dimensions": {"x": 1, "y": 0.9, "z": 1},
            }
        ],
    }


def _completed_run(
    db: Session,
    dataset,
    *,
    scene_x: float = 3,
    model_reports_passed: bool = True,
):
    case = dataset.cases[0]
    task = DesignTask(
        status="confirmed",
        progress=50,
        raw_user_input="需要现代客厅",
        confirmed_requirement_json={"space_type": "客厅", "style": "现代"},
        space_type="客厅",
        style="现代",
        budget_min=10000,
        budget_max=20000,
    )
    db.add(task)
    db.flush()
    db.add(
        UploadedImage(
            task_id=task.id,
            file_url="/uploads/eval-room.png",
            content_digest=f"sha256:{case.asset_sha256}",
        )
    )
    db.commit()
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )
    revision = design_version_service.persist_generation(
        db,
        task=task,
        plans=[_plan(model_reports_passed=model_reports_passed)],
        generator="llm",
        workflow_trace=[{"node": "validate_quality", "status": "completed"}],
    )
    plan = revision.plans[0]
    scene = DesignScene(plan_version_id=plan.id, current_version=1)
    db.add(scene)
    db.flush()
    db.add(
        DesignSceneVersion(
            scene_id=scene.id,
            version=1,
            scene_json=_scene_document(x=scene_x),
            validation_json={"valid": True, "errors": [], "warnings": []},
            source="auto_layout",
        )
    )
    db.flush()
    now = datetime.now(timezone.utc)
    run.attempt_count = 1
    run.started_at = now
    run.output_snapshot = {"forged": "collector must ignore this"}
    for index, node in enumerate(
        ("prepare_context", "generate_plans", "calculate_quote", "validate_quality"),
        start=1,
    ):
        db.add(
            GenerationRunEvent(
                run_id=run.id,
                node=node,
                status="completed",
                progress=index * 20,
                source={
                    "generate_plans": "llm",
                    "calculate_quote": "deterministic",
                    "validate_quality": "deterministic",
                }.get(node),
            )
        )
    assert generation_run_service.mark_completed(
        db,
        run=run,
        generator="llm",
        result_revision_id=revision.id,
    )
    db.refresh(run)
    return run, revision


def _binding(run, **overrides) -> RunBinding:
    values = {
        "case_id": "case-output-001",
        "task_id": run.task_id,
        "system_run_id": run.id,
        "execution_review_path": None,
        "execution_review_sha256": None,
    }
    values.update(overrides)
    return RunBinding(**values)


def _collect(db, dataset, run, *, binding=None, dataset_root=None):
    return collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=(binding or _binding(run),),
        dataset_root=dataset_root,
        signing_key=SIGNING_KEY,
        key_id="test-key-v1",
    )


def test_collector_recomputes_metrics_from_revision_and_annotation(db, tmp_path):
    dataset = _dataset(tmp_path)
    run, _ = _completed_run(db, dataset)

    bundle = _collect(db, dataset, run)

    execution = bundle["executions"][0]
    result = execution["result"]
    assert bundle["schema_version"] == "6.0"
    assert execution["output_digest"] == run.output_digest
    assert result["requirement_correct"] == 0
    assert result["requirement_total"] == 1
    assert result["space_fact_correct"] == 0
    assert result["space_fact_total"] == 1
    assert result["low_confidence_confirmed"] == 0
    assert result["low_confidence_facts"] == 0
    assert result["recommended_skus"] == 2
    assert result["valid_skus"] == 2
    assert result["product_match_checks"] == 2
    assert result["product_match_accepted"] == 1
    assert result["quote_checks"] == 1
    assert result["quote_consistent"] == 1
    assert result["budget_checks"] == 1
    assert result["budget_within_limit"] == 1
    assert result["layout_checks"] == 1
    assert result["layout_hard_passes"] == 0
    assert result["layout_no_evidence"] == 0
    assert result["style_checks"] == 1
    assert result["style_consistent"] == 1
    assert result["human_rating_count"] == 0
    assert result["human_review_count"] == 0
    assert result["human_edit_count"] == 0


def test_catalog_validity_and_human_product_match_are_independent(db, tmp_path):
    dataset = _dataset(tmp_path)
    run, _ = _completed_run(db, dataset)

    result = _collect(db, dataset, run)["executions"][0]["result"]

    assert result["recommended_skus"] == 2
    assert result["valid_skus"] == 2
    assert result["product_match_checks"] == 2
    assert result["product_match_accepted"] == 1


def test_catalog_validity_fails_closed_without_frozen_eligibility_evidence(
    db,
    tmp_path,
):
    dataset = _dataset(tmp_path)
    case = dataset.cases[0]
    task = DesignTask(
        status="confirmed",
        progress=50,
        raw_user_input="需要现代客厅",
        confirmed_requirement_json={"space_type": "客厅", "style": "现代"},
        space_type="客厅",
        style="现代",
        budget_min=10000,
        budget_max=20000,
    )
    db.add(task)
    db.flush()
    db.add(
        UploadedImage(
            task_id=task.id,
            file_url="/uploads/eval-room.png",
            content_digest=f"sha256:{case.asset_sha256}",
        )
    )
    db.commit()
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=case.id,
        task=task,
    )
    revision = design_version_service.persist_generation(
        db,
        task=task,
        plans=[_plan(include_catalog_evidence=False)],
        generator="llm",
        workflow_trace=[{"node": "validate_quality", "status": "completed"}],
    )
    plan = revision.plans[0]
    scene = DesignScene(plan_version_id=plan.id, current_version=1)
    db.add(scene)
    db.flush()
    db.add(
        DesignSceneVersion(
            scene_id=scene.id,
            version=1,
            scene_json=_scene_document(x=3),
            validation_json={"valid": True, "errors": [], "warnings": []},
            source="auto_layout",
        )
    )
    db.flush()
    now = datetime.now(timezone.utc)
    run.attempt_count = 1
    run.started_at = now
    for index, node in enumerate(
        ("prepare_context", "generate_plans", "calculate_quote", "validate_quality"),
        start=1,
    ):
        db.add(
            GenerationRunEvent(
                run_id=run.id,
                node=node,
                status="completed",
                progress=index * 20,
                source={
                    "generate_plans": "llm",
                    "calculate_quote": "deterministic",
                    "validate_quality": "deterministic",
                }.get(node),
            )
        )
    assert generation_run_service.mark_completed(
        db,
        run=run,
        generator="llm",
        result_revision_id=revision.id,
    )
    db.refresh(run)

    with pytest.raises(EvaluationInputError, match="冻结商品资格"):
        _collect(db, dataset, run)


def test_collector_uses_frozen_geometry_not_model_reported_layout_result(
    db,
    tmp_path,
):
    dataset = _dataset(tmp_path)
    run, _ = _completed_run(
        db,
        dataset,
        scene_x=0,
        model_reports_passed=False,
    )

    result = _collect(db, dataset, run)["executions"][0]["result"]

    assert result["layout_checks"] == 1
    assert result["layout_hard_passes"] == 1
    assert result["layout_no_evidence"] == 0


def test_collector_reports_no_evidence_for_unrepresented_geometry_constraint(
    db,
    tmp_path,
):
    with pytest.raises(DatasetValidationError, match="无法由冻结 SceneDocument 确定性评估"):
        _dataset(tmp_path, constraint_type="walkway_width")


def test_collector_rejects_tampered_revision_even_if_snapshot_is_unchanged(db, tmp_path):
    dataset = _dataset(tmp_path)
    run, revision = _completed_run(db, dataset)
    revision.plans[0].plan_json = {**revision.plans[0].plan_json, "style": "轻奢"}
    db.commit()

    with pytest.raises(EvaluationInputError, match="输出摘要不一致"):
        _collect(db, dataset, run)


def test_collector_rejects_snapshot_only_success(db, tmp_path):
    dataset = _dataset(tmp_path)
    run, _ = _completed_run(db, dataset)
    run.result_revision_id = None
    run.output_digest = None
    run.output_snapshot = {"plan_count": 1, "plans": [{"furniture_count": 99}]}
    db.commit()

    with pytest.raises(EvaluationInputError, match="不可变输出"):
        _collect(db, dataset, run)


def test_matching_execution_review_adds_human_metrics(db, tmp_path):
    dataset = _dataset(tmp_path)
    run, _ = _completed_run(db, dataset)
    review = {
        "schema_version": "1.0",
        "review_type": "real_world_execution_review",
        "case_id": "case-output-001",
        "label_version": "labels-v1",
        "output_digest": run.output_digest,
        "reviewer_role": "designer",
        "overall_rating": 5,
        "dimension_scores": [{"metric": "layout_quality", "score": 4}],
        "edit_facts": [
            {
                "edit_id": "edit-001",
                "action": "move",
                "target_type": "furniture",
                "target_id": "sofa-main",
                "axis": "x",
                "delta_mm": 100,
                "delta_degrees": None,
                "replacement_sku": None,
                "quantity_delta": None,
            }
        ],
    }
    path = tmp_path / "reviews" / "case-output-001.json"
    path.parent.mkdir()
    path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    file_digest = hashlib.sha256(path.read_bytes()).hexdigest()

    bundle = _collect(
        db,
        dataset,
        run,
        binding=_binding(
            run,
            execution_review_path=path,
            execution_review_sha256=file_digest,
        ),
        dataset_root=tmp_path,
    )

    result = bundle["executions"][0]["result"]
    assert result["human_rating_count"] == 1
    assert result["human_rating_sum"] == 5
    assert result["human_review_count"] == 1
    assert result["human_edit_count"] == 1
    assert result["human_move_count"] == 1


def test_mismatched_execution_review_is_rejected(db, tmp_path):
    dataset = _dataset(tmp_path)
    run, _ = _completed_run(db, dataset)
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "review_type": "real_world_execution_review",
                "case_id": "case-output-001",
                "label_version": "labels-v1",
                "output_digest": "sha256:" + "f" * 64,
                "reviewer_role": "customer",
                "overall_rating": 1,
                "dimension_scores": [],
                "edit_facts": [],
            }
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(review_path.read_bytes()).hexdigest()

    with pytest.raises(EvaluationInputError, match="人工评审"):
        _collect(
            db,
            dataset,
            run,
            binding=_binding(
                run,
                execution_review_path=review_path,
                execution_review_sha256=digest,
            ),
            dataset_root=tmp_path,
        )
