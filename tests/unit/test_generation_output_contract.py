from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import (
    DesignScene,
    DesignSceneVersion,
    DesignTask,
    GenerationRunSceneEvidence,
)
from app.services import (
    design_version_service,
    generation_output_service,
    generation_run_service,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _task(db: Session, *, requirement: dict | None = None) -> DesignTask:
    task = DesignTask(
        status="confirmed",
        progress=50,
        confirmed_requirement_json=requirement
        or {"space_type": "客厅", "style": "现代"},
    )
    db.add(task)
    db.commit()
    return task


def _plans(
    *,
    reverse_unordered_items: bool = False,
    reverse_plan_order: bool = False,
    total: int = 10000,
) -> list[dict]:
    plans = [
        {
            "id": "plan-a",
            "name": "方案 A",
            "style": "现代",
            "furnitureSuggestions": [
                {"sku": "SOFA-001", "id": "SOFA-001", "quantity": 1},
                {"sku": "LAMP-001", "id": "LAMP-001", "quantity": 1},
            ],
            "layoutConstraintResults": [
                {"constraintId": "inside-room", "passed": True}
            ],
            "shopQuote": {
                "currency": "CNY",
                "furnitureTotal": total,
                "customTotal": 0,
                "total": total,
                "lineItems": [
                    {"sku": "SOFA-001", "quantity": 1, "unitPrice": total - 1},
                    {"sku": "LAMP-001", "quantity": 1, "unitPrice": 1},
                ],
                "customLineItems": [],
                "catalogVersion": "catalog-v1",
                "priceVersion": "price-v1",
                "ruleVersion": "rules-v1",
            },
        },
        {
            "id": "plan-b",
            "name": "方案 B",
            "style": "现代",
            "furnitureSuggestions": [
                {"quantity": 1, "id": "TABLE-001", "sku": "TABLE-001"},
                {"quantity": 1, "id": "CHAIR-001", "sku": "CHAIR-001"},
            ],
            "layoutConstraintResults": [
                {"passed": True, "constraintId": "inside-room"}
            ],
            "shopQuote": {
                "ruleVersion": "rules-v1",
                "priceVersion": "price-v1",
                "catalogVersion": "catalog-v1",
                "customLineItems": [],
                "lineItems": [
                    {"unitPrice": total - 1, "quantity": 1, "sku": "TABLE-001"},
                    {"unitPrice": 1, "quantity": 1, "sku": "CHAIR-001"},
                ],
                "total": total,
                "customTotal": 0,
                "furnitureTotal": total,
                "currency": "CNY",
            },
        },
    ]
    if reverse_unordered_items:
        for plan in plans:
            plan["furnitureSuggestions"].reverse()
            plan["layoutConstraintResults"].reverse()
            plan["shopQuote"]["lineItems"].reverse()
    if reverse_plan_order:
        plans.reverse()
    return plans


def _revision(db: Session, task: DesignTask, *, plans: list[dict]):
    return design_version_service.persist_generation(
        db,
        task=task,
        plans=plans,
        generator="llm",
        image_context=["已脱敏空间事实"],
        workflow_trace=[{"node": "validate_quality", "status": "completed"}],
    )


def _scene_document(*, room_id: str, instance_id: str, x: float = 0) -> dict:
    return {
        "schemaVersion": "1.0",
        "unit": "m",
        "coordinateSystem": "right-handed-y-up",
        "room": {
            "id": room_id,
            "name": "客厅",
            "floorPolygon": [
                {"x": -3, "z": -3},
                {"x": 3, "z": -3},
                {"x": 3, "z": 3},
                {"x": -3, "z": 3},
            ],
            "ceilingHeight": 2.8,
            "wallThickness": 0.12,
        },
        "openings": [],
        "items": [
            {
                "instanceId": instance_id,
                "sku": "SOFA-001",
                "category": "沙发",
                "transform": {
                    "position": {"x": x, "y": 0.45, "z": 0},
                    "rotation": {"x": 0, "y": 0, "z": 0},
                    "scale": {"x": 1, "y": 1, "z": 1},
                },
                "dimensions": {"x": 2, "y": 0.9, "z": 1},
            }
        ],
    }


def _add_scenes(db: Session, revision, *, reverse: bool = False, x: float = 0):
    plans = list(revision.plans)
    if reverse:
        plans.reverse()
    by_key = {}
    for plan in plans:
        scene = DesignScene(plan_version_id=plan.id, current_version=1)
        db.add(scene)
        db.flush()
        document = _scene_document(
            room_id=f"room-{plan.plan_key}",
            instance_id=f"item-{plan.plan_key}",
            x=x,
        )
        version = DesignSceneVersion(
            scene_id=scene.id,
            version=1,
            scene_json=document,
            validation_json={"valid": True, "errors": [], "warnings": []},
            source="auto_layout",
        )
        db.add(version)
        db.flush()
        by_key[plan.plan_key] = (scene, version)
    return by_key


def test_output_digest_ignores_unordered_items_but_binds_plan_order_and_content(db):
    first_task = _task(db)
    second_task = _task(
        db,
        requirement={"style": "现代", "space_type": "客厅"},
    )
    third_task = _task(db)
    fourth_task = _task(db)
    first = _revision(db, first_task, plans=_plans())
    _add_scenes(db, first)
    unordered_items_reordered = _revision(
        db,
        second_task,
        plans=_plans(reverse_unordered_items=True),
    )
    _add_scenes(db, unordered_items_reordered)
    plans_reordered = _revision(
        db,
        third_task,
        plans=_plans(reverse_plan_order=True),
    )
    _add_scenes(db, plans_reordered)
    changed = _revision(db, fourth_task, plans=_plans(total=10001))
    _add_scenes(db, changed)

    first_digest = generation_output_service.revision_output_digest(
        db,
        revision_id=first.id,
    )
    unordered_items_digest = generation_output_service.revision_output_digest(
        db,
        revision_id=unordered_items_reordered.id,
    )
    plans_reordered_digest = generation_output_service.revision_output_digest(
        db,
        revision_id=plans_reordered.id,
    )
    changed_digest = generation_output_service.revision_output_digest(
        db,
        revision_id=changed.id,
    )

    assert first_digest.startswith("sha256:")
    assert unordered_items_digest == first_digest
    assert plans_reordered_digest != first_digest
    assert changed_digest != first_digest


def test_output_digest_binds_normalized_scene_document(db):
    first_task = _task(db)
    second_task = _task(db)
    first = _revision(db, first_task, plans=[_plans()[0]])
    second = _revision(db, second_task, plans=[_plans()[0]])
    _add_scenes(db, first, x=0)
    _add_scenes(db, second, x=1)

    assert generation_output_service.revision_output_digest(
        db,
        revision_id=first.id,
    ) != generation_output_service.revision_output_digest(
        db,
        revision_id=second.id,
    )


def test_completed_run_requires_revision_owned_by_the_same_task(db):
    task = _task(db)
    other_task = _task(db)
    run = generation_run_service.create_run(db, task=task)
    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="worker-output-owner",
        lease_seconds=60,
    )
    assert claimed is not None
    wrong_revision = _revision(db, other_task, plans=_plans())

    with pytest.raises(
        generation_output_service.GenerationOutputValidationError,
        match="不属于运行任务",
    ):
        generation_run_service.mark_completed(
            db,
            run_id=run.id,
            worker_id="worker-output-owner",
            worker_attempt=1,
            generator="llm",
            result_revision_id=wrong_revision.id,
        )

    db.refresh(run)
    assert run.status == "running"
    assert run.result_revision_id is None
    assert run.output_digest is None


def test_completed_run_atomically_binds_revision_and_digest(db):
    task = _task(db)
    run = generation_run_service.create_run(db, task=task)
    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="worker-output-bind",
        lease_seconds=60,
    )
    assert claimed is not None
    revision = _revision(db, task, plans=_plans())
    scenes = _add_scenes(db, revision, reverse=True)

    assert generation_run_service.mark_completed(
        db,
        run_id=run.id,
        worker_id="worker-output-bind",
        worker_attempt=1,
        generator="llm",
        result_revision_id=revision.id,
    )

    db.refresh(run)
    assert run.status == "completed"
    assert run.result_revision_id == revision.id
    assert run.output_digest == generation_output_service.revision_output_digest(
        db,
        revision_id=revision.id,
    )
    evidence = {
        item.plan_version_id: item
        for item in db.query(GenerationRunSceneEvidence).all()
    }
    assert set(evidence) == {plan.id for plan in revision.plans}
    payload = generation_output_service.validated_run_output(db, run=run)
    assert {
        record["plan_key"]: record["scene"]["document"]["room"]["id"]
        for record in payload["plans"]
    } == {
        "plan-a": "room-plan-a",
        "plan-b": "room-plan-b",
    }
    for plan in revision.plans:
        assert evidence[plan.id].scene_version_id == scenes[plan.plan_key][1].id


def test_completed_run_fails_closed_when_any_plan_has_no_scene(db):
    task = _task(db)
    run = generation_run_service.create_run(db, task=task)
    generation_run_service.claim_next_run(
        db,
        worker_id="worker-output-missing-scene",
        lease_seconds=60,
    )
    revision = _revision(db, task, plans=_plans())
    first_plan = revision.plans[0]
    partial_revision = type("PartialRevision", (), {"plans": [first_plan]})()
    _add_scenes(db, partial_revision)

    with pytest.raises(
        generation_output_service.GenerationOutputValidationError,
        match="缺少冻结场景",
    ):
        generation_run_service.mark_completed(
            db,
            run_id=run.id,
            worker_id="worker-output-missing-scene",
            worker_attempt=1,
            generator="llm",
            result_revision_id=revision.id,
        )

    db.refresh(run)
    assert run.status == "running"
    assert run.result_revision_id is None
    assert db.query(GenerationRunSceneEvidence).count() == 0


def test_bound_output_keeps_frozen_scene_after_current_scene_advances(db):
    task = _task(db)
    run = generation_run_service.create_run(db, task=task)
    generation_run_service.claim_next_run(
        db,
        worker_id="worker-output-frozen-scene",
        lease_seconds=60,
    )
    revision = _revision(db, task, plans=[_plans()[0]])
    scenes = _add_scenes(db, revision)
    assert generation_run_service.mark_completed(
        db,
        run_id=run.id,
        worker_id="worker-output-frozen-scene",
        worker_attempt=1,
        generator="llm",
        result_revision_id=revision.id,
    )
    original_digest = run.output_digest
    scene, _ = scenes["plan-a"]
    scene.current_version = 2
    db.add(
        DesignSceneVersion(
            scene_id=scene.id,
            version=2,
            scene_json=_scene_document(
                room_id="room-plan-a",
                instance_id="item-plan-a",
                x=1,
            ),
            validation_json={"valid": True, "errors": [], "warnings": []},
            source="manual",
        )
    )
    db.commit()

    payload = generation_output_service.validated_run_output(db, run=run)

    assert run.output_digest == original_digest
    assert payload["plans"][0]["scene"]["version"] == 1
    assert payload["plans"][0]["scene"]["document"]["items"][0]["transform"][
        "position"
    ]["x"] == 0


def test_bound_output_rejects_tampered_frozen_scene_content(db):
    task = _task(db)
    run = generation_run_service.create_run(db, task=task)
    generation_run_service.claim_next_run(
        db,
        worker_id="worker-output-scene-tamper",
        lease_seconds=60,
    )
    revision = _revision(db, task, plans=[_plans()[0]])
    scenes = _add_scenes(db, revision)
    assert generation_run_service.mark_completed(
        db,
        run_id=run.id,
        worker_id="worker-output-scene-tamper",
        worker_attempt=1,
        generator="llm",
        result_revision_id=revision.id,
    )
    _, version = scenes["plan-a"]
    version.scene_json = _scene_document(
        room_id="room-plan-a",
        instance_id="item-plan-a",
        x=2,
    )
    db.commit()

    with pytest.raises(
        generation_output_service.GenerationOutputValidationError,
        match="场景摘要不一致",
    ):
        generation_output_service.validated_run_output(db, run=run)


def test_bound_output_rejects_scene_reference_from_another_task(db):
    task = _task(db)
    run = generation_run_service.create_run(db, task=task)
    generation_run_service.claim_next_run(
        db,
        worker_id="worker-output-foreign-scene",
        lease_seconds=60,
    )
    revision = _revision(db, task, plans=[_plans()[0]])
    _add_scenes(db, revision)
    assert generation_run_service.mark_completed(
        db,
        run_id=run.id,
        worker_id="worker-output-foreign-scene",
        worker_attempt=1,
        generator="llm",
        result_revision_id=revision.id,
    )

    other_task = _task(db)
    other_revision = _revision(db, other_task, plans=[_plans()[0]])
    other_scene, other_version = _add_scenes(db, other_revision)["plan-a"]
    evidence = db.query(GenerationRunSceneEvidence).filter_by(
        generation_run_id=run.id
    ).one()
    evidence.scene_id = other_scene.id
    evidence.scene_version_id = other_version.id
    evidence.scene_version = other_version.version
    db.commit()

    with pytest.raises(
        generation_output_service.GenerationOutputValidationError,
        match="场景版本引用不一致",
    ):
        generation_output_service.validated_run_output(db, run=run)


def test_terminal_failure_clears_untrusted_output_fields(db):
    task = _task(db)
    run = generation_run_service.create_run(db, task=task, max_attempts=1)
    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="worker-output-failure",
        lease_seconds=60,
    )
    assert claimed is not None
    revision = _revision(db, task, plans=_plans())
    run.result_revision_id = revision.id
    run.output_digest = "sha256:" + "a" * 64
    run.output_snapshot = {"forged": "must not survive"}

    status = generation_run_service.mark_failed(
        db,
        run=run,
        worker_id="worker-output-failure",
        worker_attempt=1,
        error_message="确定性输出校验失败",
        retryable=False,
        now=datetime.now(timezone.utc),
    )

    assert status == "failed"
    assert run.result_revision_id is None
    assert run.output_digest is None
    assert run.output_snapshot is None
