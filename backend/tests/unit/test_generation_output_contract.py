from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import DesignTask
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


def _plans(*, reverse: bool = False, total: int = 10000) -> list[dict]:
    plans = [
        {
            "id": "plan-a",
            "name": "方案 A",
            "style": "现代",
            "furnitureSuggestions": [
                {"sku": "SOFA-001", "id": "SOFA-001", "quantity": 1}
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
                    {"sku": "SOFA-001", "quantity": 1, "unitPrice": total}
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
                {"quantity": 1, "id": "TABLE-001", "sku": "TABLE-001"}
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
                    {"unitPrice": total, "quantity": 1, "sku": "TABLE-001"}
                ],
                "total": total,
                "customTotal": 0,
                "furnitureTotal": total,
                "currency": "CNY",
            },
        },
    ]
    return list(reversed(plans)) if reverse else plans


def _revision(db: Session, task: DesignTask, *, plans: list[dict]):
    return design_version_service.persist_generation(
        db,
        task=task,
        plans=plans,
        generator="llm",
        image_context=["已脱敏空间事实"],
        workflow_trace=[{"node": "validate_quality", "status": "completed"}],
    )


def test_output_digest_ignores_json_and_plan_reordering_but_binds_content(db):
    first_task = _task(db)
    second_task = _task(
        db,
        requirement={"style": "现代", "space_type": "客厅"},
    )
    third_task = _task(db)
    first = _revision(db, first_task, plans=_plans())
    reordered = _revision(db, second_task, plans=_plans(reverse=True))
    changed = _revision(db, third_task, plans=_plans(total=10001))

    first_digest = generation_output_service.revision_output_digest(
        db,
        revision_id=first.id,
    )
    reordered_digest = generation_output_service.revision_output_digest(
        db,
        revision_id=reordered.id,
    )
    changed_digest = generation_output_service.revision_output_digest(
        db,
        revision_id=changed.id,
    )

    assert first_digest.startswith("sha256:")
    assert reordered_digest == first_digest
    assert changed_digest != first_digest


def test_completed_run_requires_revision_owned_by_the_same_task(db):
    task = _task(db)
    other_task = _task(db)
    run = generation_run_service.create_run(db, task=task)
    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="worker-output-owner",
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
    )
    assert claimed is not None
    revision = _revision(db, task, plans=_plans())

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


def test_terminal_failure_clears_untrusted_output_fields(db):
    task = _task(db)
    run = generation_run_service.create_run(db, task=task, max_attempts=1)
    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="worker-output-failure",
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
