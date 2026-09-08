from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import (
    DesignTask,
    DesignScene,
    DesignSceneVersion,
    EvaluationRunBinding,
    GenerationRunEvent,
    RequirementParseResult,
    RoomFactConfirmation,
    UploadedImage,
)
from app.services import (
    design_version_service,
    evaluation_binding_service,
    generation_run_service,
    prediction_evidence_service,
)
from app.services.generation_provenance import canonical_digest
from evals.real_world import load_case_manifest
from evals.trusted_evidence import RunBinding, bind_evaluation_run, collect_trusted_evidence
from tests.real_world_fixtures import (
    frozen_catalog_quote_line,
    frozen_catalog_suggestion,
    write_v2_manifest,
)


SIGNING_KEY = "prediction-evidence-test-key-at-least-32-bytes"


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _dataset(tmp_path: Path):
    (tmp_path / "room.png").write_bytes(b"authorized-prediction-room")
    return load_case_manifest(
        write_v2_manifest(
            tmp_path,
            filename="manifest.json",
            dataset_version="prediction-contract-v1",
            cases=[
                {
                    "id": "case-prediction-001",
                    "name": "真实预测证据案例",
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
    )


def _room_model(*, room_id: str = "living", width_m: float | None = 4.2):
    return {
        "schemaVersion": "1.0",
        "imageKind": "floor_plan",
        "spaceType": "客厅",
        "rooms": [
            {
                "id": room_id,
                "name": "客厅",
                "floorPolygon": [
                    {"x": 0, "z": 0},
                    {"x": 1, "z": 0},
                    {"x": 1, "z": 1},
                ],
                "widthM": width_m,
                "depthM": 5.0,
                "confidence": 0.42,
            }
        ],
        "scale": {"source": "vl", "confidence": 0.55},
        "confidence": 0.42,
        "requiresConfirmation": [f"rooms.{room_id}.width_m"],
    }


def _task_with_predictions(
    db: Session,
    dataset,
    *,
    parser: str = "llm",
    parsed_json: dict | None = None,
    room_id: str = "living",
    width_m: float | None = 4.2,
    prediction_source: str = "vl",
    parser_model: str | None = "requirement-model-v1",
    prediction_model: str | None = "vision-model-v1",
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
    parse_result = RequirementParseResult(
        task_id=task.id,
        raw_input=task.raw_user_input,
        parsed_json=parsed_json if parsed_json is not None else {"space_type": "客厅"},
        parser=parser,
        parser_model=parser_model,
    )
    db.add(parse_result)
    room_model = _room_model(room_id=room_id, width_m=width_m)
    image = UploadedImage(
        task_id=task.id,
        file_url="/uploads/eval-room.png",
        content_digest=f"sha256:{case.asset_sha256}",
        analysis_json={"room_model": room_model, "source": prediction_source},
    )
    prediction_evidence_service.capture_uploaded_prediction(
        image,
        raw_room_model=room_model,
        source=prediction_source,
        model=prediction_model,
    )
    db.add(image)
    db.commit()
    return task, parse_result, image


def _plan():
    suggestion = frozen_catalog_suggestion()
    return {
        "id": "plan-a",
        "name": "预测证据方案",
        "style": "现代",
        "furnitureSuggestions": [suggestion],
        "shopQuote": {
            "currency": "CNY",
            "furnitureTotal": 10000,
            "customTotal": 0,
            "total": 10000,
            "lineItems": [frozen_catalog_quote_line(suggestion)],
            "customLineItems": [],
            "catalogVersion": "catalog-v1",
            "priceVersion": "price-v1",
            "ruleVersion": "rules-v1",
        },
    }


def _scene_document():
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
                    "position": {"x": 0, "y": 0.45, "z": 0},
                    "rotation": {"x": 0, "y": 0, "z": 0},
                    "scale": {"x": 1, "y": 1, "z": 1},
                },
                "dimensions": {"x": 1, "y": 0.9, "z": 1},
            }
        ],
    }


def _complete_run(db: Session, dataset, task: DesignTask):
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=dataset.cases[0].id,
        task=task,
    )
    revision = design_version_service.persist_generation(
        db,
        task=task,
        plans=[_plan()],
        generator="llm",
        workflow_trace=[{"node": "validate_quality", "status": "completed"}],
    )
    scene = DesignScene(plan_version_id=revision.plans[0].id, current_version=1)
    db.add(scene)
    db.flush()
    db.add(
        DesignSceneVersion(
            scene_id=scene.id,
            version=1,
            scene_json=_scene_document(),
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
    return run


def _collect(db: Session, dataset, run):
    return collect_trusted_evidence(
        db,
        dataset=dataset,
        split="regression",
        bindings=(RunBinding(dataset.cases[0].id, run.task_id, run.id),),
        signing_key=SIGNING_KEY,
        key_id="prediction-key-v1",
    )


def test_metrics_use_frozen_pre_calibration_llm_and_vlm_predictions(db, tmp_path):
    dataset = _dataset(tmp_path)
    task, _, image = _task_with_predictions(db, dataset)
    db.add(
        RoomFactConfirmation(
            image_id=image.id,
            task_id=task.id,
            fact_path="rooms.living.width_m",
            previous_value_json=4.2,
            confirmed_value_json=4.8,
            previous_confidence=0.55,
            confirmed_by_type="anonymous_session",
            confirmed_by_id="session-001",
        )
    )
    # 校准投影与标注不同；准确率仍必须读取上传时的 4.2 原始预测。
    image.analysis_json = {
        "room_model": _room_model(width_m=4.8),
        "source": "vl",
    }
    db.commit()

    run = _complete_run(db, dataset, task)
    result = _collect(db, dataset, run)["executions"][0]["result"]

    assert result["requirement_correct"] == 1
    assert result["requirement_total"] == 1
    assert result["space_fact_correct"] == 1
    assert result["space_fact_total"] == 1
    assert result["low_confidence_confirmed"] == 1
    assert result["low_confidence_facts"] == 1
    binding = db.query(EvaluationRunBinding).filter_by(generation_run_id=run.id).one()
    assert binding.prediction_digest == canonical_digest(binding.prediction_snapshot_json)
    execution = _collect(db, dataset, run)["executions"][0]
    assert execution["prediction_digest"] == binding.prediction_digest
    room_prediction = binding.prediction_snapshot_json["space"]["room_model"]
    assert room_prediction["rooms"]["living"]["width_m"] == 4.2
    assert binding.prediction_snapshot_json["requirement"]["model"] == "requirement-model-v1"
    assert binding.prediction_snapshot_json["space"]["model"] == "vision-model-v1"


def test_missing_or_untrusted_prediction_is_a_miss_not_a_smaller_denominator(db, tmp_path):
    dataset = _dataset(tmp_path)
    task, _, _ = _task_with_predictions(
        db,
        dataset,
        parser="rule",
        parsed_json={"space_type": "客厅"},
        prediction_source="placeholder",
        parser_model=None,
        prediction_model=None,
    )

    run = _complete_run(db, dataset, task)
    result = _collect(db, dataset, run)["executions"][0]["result"]

    assert result["requirement_correct"] == 0
    assert result["requirement_total"] == 1
    assert result["space_fact_correct"] == 0
    assert result["space_fact_total"] == 1
    assert result["low_confidence_facts"] == 0


def test_model_source_without_actual_model_identity_is_not_trusted(db, tmp_path):
    dataset = _dataset(tmp_path)
    task, _, _ = _task_with_predictions(
        db,
        dataset,
        parser_model=None,
        prediction_model=None,
    )

    run = _complete_run(db, dataset, task)
    result = _collect(db, dataset, run)["executions"][0]["result"]

    assert result["requirement_correct"] == 0
    assert result["requirement_total"] == 1
    assert result["space_fact_correct"] == 0
    assert result["space_fact_total"] == 1


def test_space_paths_are_addressed_by_room_id_without_single_room_fallback(db, tmp_path):
    dataset = _dataset(tmp_path)
    task, _, _ = _task_with_predictions(db, dataset, room_id="bedroom")

    run = _complete_run(db, dataset, task)
    result = _collect(db, dataset, run)["executions"][0]["result"]

    assert result["space_fact_correct"] == 0
    assert result["space_fact_total"] == 1


def test_failed_generation_still_counts_frozen_prediction_denominators(db, tmp_path):
    dataset = _dataset(tmp_path)
    task, _, _ = _task_with_predictions(db, dataset)
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=dataset.cases[0].id,
        task=task,
    )
    run.attempt_count = 1
    run.started_at = datetime.now(timezone.utc)
    generation_run_service.mark_failed(
        db,
        run=run,
        error_message="generation failed after perception",
    )

    result = _collect(db, dataset, run)["executions"][0]["result"]

    assert result["generation_succeeded"] is False
    assert result["requirement_correct"] == 1
    assert result["requirement_total"] == 1
    assert result["space_fact_correct"] == 1
    assert result["space_fact_total"] == 1


def test_binding_revalidation_rejects_mutated_source_prediction(db, tmp_path):
    dataset = _dataset(tmp_path)
    task, parse_result, _ = _task_with_predictions(db, dataset)
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=dataset.cases[0].id,
        task=task,
    )
    parse_result.parsed_json = {"space_type": "卧室"}
    db.commit()

    with pytest.raises(
        evaluation_binding_service.EvaluationBindingError,
        match="预测证据",
    ):
        evaluation_binding_service.validate_persisted_binding(db, run=run)


def test_legacy_binding_without_prediction_snapshot_fails_closed(db, tmp_path):
    dataset = _dataset(tmp_path)
    task, _, _ = _task_with_predictions(db, dataset)
    run = bind_evaluation_run(
        db,
        dataset=dataset,
        split="regression",
        case_id=dataset.cases[0].id,
        task=task,
    )
    binding = db.query(EvaluationRunBinding).filter_by(generation_run_id=run.id).one()
    binding.prediction_snapshot_json = None
    binding.prediction_digest = None
    db.commit()

    with pytest.raises(
        evaluation_binding_service.EvaluationBindingError,
        match="历史评测绑定缺少预测证据",
    ):
        evaluation_binding_service.validate_persisted_binding(db, run=run)
