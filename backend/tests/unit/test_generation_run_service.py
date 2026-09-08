from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import (
    DesignPlanVersion,
    DesignRevision,
    DesignTask,
    GenerationRun,
    GenerationRunEvent,
    LayoutRun,
    TaskExecutionEvent,
)
from app.services import design_version_service, generation_run_service
from tests.scene_fixtures import attach_scene_versions


def _persist_run_output(db, task, *, generator: str = "llm"):
    revision = design_version_service.persist_generation(
        db,
        task=task,
        generator=generator,
        plans=[
            {
                "id": "plan-run",
                "name": "运行方案",
                "furnitureSuggestions": [{"id": "SOFA-001"}],
                "shopQuote": {
                    "furnitureTotal": 1000,
                    "customTotal": 0,
                    "total": 1000,
                    "lineItems": [
                        {"sku": "SOFA-001", "unitPrice": 1000, "quantity": 1}
                    ],
                    "customLineItems": [],
                },
            }
        ],
    )
    attach_scene_versions(db, revision)
    return revision


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.mark.unit
def test_generation_run_records_durable_node_progress(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()

    run = generation_run_service.create_run(db, task=task)
    generation_run_service.mark_running(db, run=run)
    generation_run_service.record_step(
        db,
        run=run,
        step={
            "node": "generate_plans",
            "status": "completed",
            "duration_ms": 24000,
            "source": "llm",
        },
    )

    db.refresh(run)
    event = db.scalar(select(GenerationRunEvent))
    assert run.status == "running"
    assert run.current_node == "generate_plans"
    assert run.progress == 60
    assert event is not None
    assert event.source == "llm"
    assert event.duration_ms == 24000


@pytest.mark.unit
def test_generation_run_reuses_active_run_and_allows_retry_after_failure(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()

    first = generation_run_service.create_run(db, task=task)
    duplicate = generation_run_service.create_run(db, task=task)
    generation_run_service.mark_failed(
        db,
        run=first,
        error_message="模型超时",
    )
    retry = generation_run_service.create_run(db, task=task)

    assert duplicate.id == first.id
    assert retry.id != first.id
    assert retry.attempt == 2
    assert len(db.scalars(select(GenerationRun)).all()) == 2


@pytest.mark.unit
def test_generation_run_idempotency_key_reuses_terminal_run(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()

    first = generation_run_service.create_run(
        db,
        task=task,
        idempotency_key="design-request-001",
        max_attempts=3,
    )
    generation_run_service.mark_failed(
        db,
        run=first,
        error_message="不可重试失败",
        retryable=False,
    )
    duplicate = generation_run_service.create_run(
        db,
        task=task,
        idempotency_key="design-request-001",
        max_attempts=3,
    )

    assert duplicate.id == first.id
    assert len(db.scalars(select(GenerationRun)).all()) == 1


@pytest.mark.unit
def test_different_key_cannot_attach_changed_input_to_active_run(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    generation_run_service.create_run(
        db,
        task=task,
        idempotency_key="agent-generation:1:first",
        request_digest="sha256:" + "a" * 64,
    )

    with pytest.raises(generation_run_service.GenerationIdempotencyConflict):
        generation_run_service.create_run(
            db,
            task=task,
            idempotency_key="agent-generation:1:second",
            request_digest="sha256:" + "b" * 64,
        )

    assert len(db.scalars(select(GenerationRun)).all()) == 1


@pytest.mark.unit
def test_worker_claim_sets_lease_and_only_owner_can_renew_or_complete(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    generation_run_service.create_run(
        db,
        task=task,
        idempotency_key="claim-001",
        max_attempts=3,
    )
    now = datetime.now(timezone.utc)

    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="worker-a",
        lease_seconds=120,
        now=now,
    )
    second = generation_run_service.claim_next_run(
        db,
        worker_id="worker-b",
        lease_seconds=120,
        now=now,
    )

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.worker_id == "worker-a"
    assert claimed.attempt_count == 1
    assert claimed.heartbeat_at == now
    assert claimed.lease_expires_at == now + timedelta(seconds=120)
    assert second is None
    assert not generation_run_service.renew_lease(
        db,
        run_id=claimed.id,
        worker_id="worker-b",
        lease_seconds=120,
        now=now + timedelta(seconds=10),
    )
    assert generation_run_service.renew_lease(
        db,
        run_id=claimed.id,
        worker_id="worker-a",
        lease_seconds=120,
        now=now + timedelta(seconds=10),
    )
    assert not generation_run_service.mark_completed(
        db,
        run_id=claimed.id,
        worker_id="worker-b",
        worker_attempt=1,
        generator="llm",
    )
    claimed.cost_cny = 1.5
    db.commit()
    revision = _persist_run_output(db, task)
    assert generation_run_service.mark_completed(
        db,
        run_id=claimed.id,
        worker_id="worker-a",
        worker_attempt=1,
        generator="llm",
        result_revision_id=revision.id,
    )
    db.refresh(claimed)
    assert claimed.status == "completed"
    assert claimed.worker_id is None
    assert claimed.lease_expires_at is None
    timeline = db.scalars(
        select(TaskExecutionEvent).where(TaskExecutionEvent.task_id == task.id)
        .order_by(TaskExecutionEvent.id)
    ).all()
    assert [event.event_code for event in timeline] == [
        "generation.queued",
        "generation.claimed",
        "generation.completed",
    ]
    assert timeline[-1].billing_status == "metered"
    assert timeline[-1].cost_cny == 1.5


@pytest.mark.unit
def test_retryable_failure_waits_for_backoff_and_stops_at_max_attempts(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    generation_run_service.create_run(
        db,
        task=task,
        idempotency_key="retry-001",
        max_attempts=2,
    )
    now = datetime.now(timezone.utc)
    first = generation_run_service.claim_next_run(
        db,
        worker_id="worker-a",
        lease_seconds=60,
        now=now,
    )
    assert first is not None

    state = generation_run_service.mark_failed(
        db,
        run=first,
        worker_id="worker-a",
        worker_attempt=1,
        error_message="模型超时",
        retryable=True,
        retry_delay_seconds=30,
        now=now,
    )

    assert state == "queued"
    assert first.next_retry_at == now + timedelta(seconds=30)
    assert generation_run_service.claim_next_run(
        db,
        worker_id="worker-b",
        lease_seconds=60,
        now=now + timedelta(seconds=29),
    ) is None
    second = generation_run_service.claim_next_run(
        db,
        worker_id="worker-b",
        lease_seconds=60,
        now=now + timedelta(seconds=30),
    )
    assert second is not None
    assert second.attempt_count == 2

    terminal = generation_run_service.mark_failed(
        db,
        run=second,
        worker_id="worker-b",
        worker_attempt=2,
        error_message="仍然超时",
        retryable=True,
        retry_delay_seconds=30,
        now=now + timedelta(seconds=30),
    )
    assert terminal == "dead_letter"
    assert second.status == "dead_letter"
    assert second.current_node == "dead_letter"
    assert second.dead_lettered_at == now + timedelta(seconds=30)
    assert second.next_retry_at is None
    db.refresh(task)
    assert task.status == "failed"


@pytest.mark.unit
def test_worker_heartbeat_cannot_extend_lease_past_execution_deadline(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    generation_run_service.create_run(db, task=task, max_attempts=3)
    now = datetime.now(timezone.utc)

    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="worker-a",
        lease_seconds=120,
        execution_timeout_seconds=90,
        now=now,
    )

    assert claimed is not None
    assert claimed.execution_deadline_at == now + timedelta(seconds=90)
    assert claimed.lease_expires_at == claimed.execution_deadline_at
    assert generation_run_service.renew_lease(
        db,
        run_id=claimed.id,
        worker_id="worker-a",
        worker_attempt=1,
        lease_seconds=120,
        now=now + timedelta(seconds=30),
    )
    db.refresh(claimed)
    assert claimed.lease_expires_at == claimed.execution_deadline_at
    assert not generation_run_service.renew_lease(
        db,
        run_id=claimed.id,
        worker_id="worker-a",
        worker_attempt=1,
        lease_seconds=120,
        now=claimed.execution_deadline_at,
    )


@pytest.mark.unit
def test_expired_execution_cannot_persist_metadata_or_complete(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    generation_run_service.create_run(db, task=task, max_attempts=3)
    now = datetime.now(timezone.utc)
    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="worker-a",
        lease_seconds=60,
        execution_timeout_seconds=30,
        now=now,
    )
    assert claimed is not None

    assert generation_run_service.record_step(
        db,
        run=claimed,
        step={"node": "generate_plans", "status": "completed"},
        worker_id="worker-a",
        worker_attempt=1,
        now=now + timedelta(seconds=31),
    ) is None
    assert not generation_run_service.record_generation_meta(
        db,
        run=claimed,
        meta={"model": "provider/model", "cost_cny": 8.8},
        output_snapshot={"plan_count": 1},
        worker_id="worker-a",
        worker_attempt=1,
        now=now + timedelta(seconds=31),
    )
    assert not generation_run_service.mark_completed(
        db,
        run_id=claimed.id,
        worker_id="worker-a",
        worker_attempt=1,
        generator="llm",
        now=now + timedelta(seconds=31),
    )
    db.refresh(claimed)
    assert claimed.status == "running"
    assert claimed.cost_cny is None
    assert claimed.output_snapshot is None
    assert db.scalar(select(GenerationRunEvent)) is None


@pytest.mark.unit
def test_recovery_dead_letters_execution_deadline_even_with_live_lease(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    generation_run_service.create_run(db, task=task, max_attempts=3)
    now = datetime.now(timezone.utc)
    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="worker-a",
        lease_seconds=120,
        execution_timeout_seconds=30,
        now=now,
    )
    assert claimed is not None
    # 模拟旧版本或人工数据中租约晚于硬截止时间，恢复仍必须按 deadline 判定。
    claimed.lease_expires_at = now + timedelta(seconds=120)
    db.commit()

    recovered = generation_run_service.recover_expired_runs(
        db,
        now=now + timedelta(seconds=31),
    )

    assert recovered == 1
    db.refresh(claimed)
    db.refresh(task)
    assert claimed.status == "dead_letter"
    assert claimed.dead_lettered_at.replace(tzinfo=timezone.utc) == (
        now + timedelta(seconds=31)
    )
    assert claimed.worker_id is None
    assert task.status == "failed"


@pytest.mark.unit
def test_recovery_dead_letters_queued_run_with_exhausted_attempts(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    run = generation_run_service.create_run(db, task=task, max_attempts=2)
    run.attempt_count = 2
    db.commit()
    now = datetime.now(timezone.utc)

    recovered = generation_run_service.recover_expired_runs(db, now=now)

    assert recovered == 1
    db.refresh(run)
    db.refresh(task)
    assert run.status == "dead_letter"
    assert run.dead_lettered_at.replace(tzinfo=timezone.utc) == now
    assert task.status == "failed"


@pytest.mark.unit
def test_expired_lease_is_recovered_and_cancel_request_wins(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    generation_run_service.create_run(
        db,
        task=task,
        idempotency_key="expired-001",
        max_attempts=3,
    )
    now = datetime.now(timezone.utc)
    claimed = generation_run_service.claim_next_run(
        db,
        worker_id="dead-worker",
        lease_seconds=120,
        execution_timeout_seconds=10,
        now=now,
    )
    assert claimed is not None
    assert generation_run_service.request_cancel(
        db,
        run=claimed,
        now=now + timedelta(seconds=5),
    ) == "running"

    generation_run_service.recover_expired_runs(
        db,
        now=now + timedelta(seconds=11),
        retry_delay_seconds=20,
    )

    db.refresh(claimed)
    assert claimed.status == "cancelled"
    assert claimed.current_node == "cancelled"
    assert claimed.worker_id is None


@pytest.mark.unit
def test_queued_run_can_be_cancelled_immediately(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    run = generation_run_service.create_run(
        db,
        task=task,
        idempotency_key="cancel-queued-001",
        max_attempts=3,
    )

    status = generation_run_service.request_cancel(db, run=run)

    assert status == "cancelled"
    assert run.status == "cancelled"
    assert task.status == "cancelled"


@pytest.mark.unit
def test_generation_run_records_model_prompt_usage_and_cost(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()

    run = generation_run_service.create_run(db, task=task)
    generation_run_service.record_generation_meta(
        db,
        run=run,
        meta={
            "model": "deepseek-ai/DeepSeek-V3",
            "prompt_snapshot": "你是资深室内设计师…",
            "input_snapshot": {"requirement": {"area": 90}, "has_catalog_context": True},
            "prompt_digest": "sha256:" + "1" * 64,
            "rules_digest": "sha256:" + "2" * 64,
            "data_digest": "sha256:" + "3" * 64,
            "usage": {"prompt_tokens": 1200, "completion_tokens": 800, "total_tokens": 2000},
            "cost_cny": 0.0028,
        },
        output_snapshot={
            "plan_count": 3,
            "plans": [
                {"name": "暖居", "style": "原木风", "budget": 80000, "score": 95, "furniture_count": 4}
            ],
        },
    )

    db.refresh(run)
    assert run.model == "deepseek-ai/DeepSeek-V3"
    assert run.prompt_snapshot == "你是资深室内设计师…"
    assert run.input_snapshot["requirement"]["area"] == 90
    assert run.output_snapshot["plan_count"] == 3
    assert run.prompt_digest == "sha256:" + "1" * 64
    assert run.rules_digest == "sha256:" + "2" * 64
    assert run.data_digest == "sha256:" + "3" * 64
    assert run.usage_json["total_tokens"] == 2000
    assert run.cost_cny == 0.0028


@pytest.mark.unit
def test_generation_run_accumulates_usage_and_cost_across_budget_replans(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    run = generation_run_service.create_run(db, task=task)

    for retry_count in range(3):
        generation_run_service.record_generation_meta(
            db,
            run=run,
            meta={
                "model": "provider/model",
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
                "cost_cny": 0.1,
            },
            output_snapshot={"retry_count": retry_count},
        )

    db.refresh(run)
    assert run.usage_json == {
        "prompt_tokens": 30,
        "completion_tokens": 15,
        "total_tokens": 45,
    }
    assert run.cost_cny == pytest.approx(0.3)
    assert run.output_snapshot == {"retry_count": 2}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("model", "provider/changed-model"),
        ("prompt_snapshot", "changed prompt"),
        ("prompt_digest", "sha256:" + "9" * 64),
        ("rules_digest", "sha256:" + "8" * 64),
        ("data_digest", "sha256:" + "7" * 64),
        ("provenance_schema_version", 999),
    ],
)
def test_generation_meta_fails_closed_when_replan_static_version_drifts(
    db,
    field,
    changed_value,
):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    run = generation_run_service.create_run(db, task=task)
    initial_meta = {
        "model": "provider/model",
        "prompt_snapshot": "initial prompt",
        "prompt_digest": "sha256:" + "1" * 64,
        "rules_digest": "sha256:" + "2" * 64,
        "data_digest": "sha256:" + "3" * 64,
        "input_snapshot": {"requirement": {"budget_max": 10_000}},
        "input_digest": "sha256:" + "4" * 64,
        "provenance_schema_version": 3,
        "usage": {"total_tokens": 15},
        "cost_cny": 0.1,
    }
    generation_run_service.record_generation_meta(
        db,
        run=run,
        meta=initial_meta,
        output_snapshot={"retry_count": 0},
    )
    changed_meta = {
        **initial_meta,
        field: changed_value,
        "input_snapshot": {
            "requirement": {"budget_max": 10_000},
            "budget_replan": {"retry_count": 1},
        },
        "input_digest": "sha256:" + "5" * 64,
    }

    with pytest.raises(
        generation_run_service.GenerationMetadataDriftError,
        match="静态版本",
    ):
        generation_run_service.record_generation_meta(
            db,
            run=run,
            meta=changed_meta,
            output_snapshot={"retry_count": 1},
        )

    assert getattr(run, field) == initial_meta[field]
    assert run.input_snapshot == initial_meta["input_snapshot"]
    assert run.input_digest == initial_meta["input_digest"]
    assert run.usage_json == {"total_tokens": 15}
    assert run.cost_cny == pytest.approx(0.1)
    assert run.output_snapshot == {"retry_count": 0}


@pytest.mark.unit
def test_model_cost_reservation_accumulates_and_rejects_over_task_limit(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    generation_run_service.create_run(db, task=task, max_attempts=3)
    run = generation_run_service.claim_next_run(
        db,
        worker_id="worker-a",
        lease_seconds=60,
    )
    assert run is not None

    assert generation_run_service.reserve_model_cost(
        db,
        run_id=run.id,
        worker_id="worker-a",
        worker_attempt=1,
        estimated_cost_cny=0.4,
        cost_limit_cny=1.0,
    ) == pytest.approx(0.4)
    assert generation_run_service.mark_failed(
        db,
        run=run,
        worker_id="worker-a",
        worker_attempt=1,
        error_message="不可重试的上游错误",
        retryable=False,
    ) == "failed"

    second_run = generation_run_service.create_run(
        db,
        task=task,
        idempotency_key="second-run",
        max_attempts=3,
    )
    second_run = generation_run_service.claim_next_run(
        db,
        run_id=second_run.id,
        worker_id="worker-b",
        lease_seconds=60,
    )
    assert second_run is not None
    assert generation_run_service.reserve_model_cost(
        db,
        run_id=second_run.id,
        worker_id="worker-b",
        worker_attempt=1,
        estimated_cost_cny=0.5,
        cost_limit_cny=2.0,
    ) == pytest.approx(0.9)

    with pytest.raises(
        generation_run_service.GenerationCostLimitExceeded,
        match="成本上限",
    ):
        generation_run_service.reserve_model_cost(
            db,
            run_id=second_run.id,
            worker_id="worker-b",
            worker_attempt=1,
            estimated_cost_cny=0.2,
            cost_limit_cny=2.0,
        )

    db.refresh(run)
    db.refresh(second_run)
    assert run.cost_reserved_cny == pytest.approx(0.4)
    assert run.cost_limit_cny == pytest.approx(1.0)
    assert second_run.cost_reserved_cny == pytest.approx(0.5)
    assert second_run.cost_limit_cny == pytest.approx(1.0)


@pytest.mark.unit
def test_missing_cost_estimate_fails_closed_without_reservation(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    generation_run_service.create_run(db, task=task, max_attempts=3)
    run = generation_run_service.claim_next_run(
        db,
        worker_id="worker-a",
        lease_seconds=60,
    )
    assert run is not None

    with pytest.raises(
        generation_run_service.GenerationCostConfigurationError,
        match="单价",
    ):
        generation_run_service.reserve_model_cost(
            db,
            run_id=run.id,
            worker_id="worker-a",
            worker_attempt=1,
            estimated_cost_cny=None,
            cost_limit_cny=1.0,
        )

    db.refresh(run)
    assert run.cost_reserved_cny == pytest.approx(0.0)


@pytest.mark.unit
def test_layout_scores_for_task_aggregates_runs(db):
    task = DesignTask(status="completed", progress=100)
    db.add(task)
    db.commit()

    revision = DesignRevision(
        task_id=task.id,
        version=1,
        requirement_snapshot={},
        generator="llm",
    )
    db.add(revision)
    db.commit()

    plan = DesignPlanVersion(
        revision_id=revision.id,
        plan_key="plan-a",
        plan_name="暖居",
        plan_json={},
    )
    db.add(plan)
    db.commit()

    db.add(
        LayoutRun(
            plan_version_id=plan.id,
            best_score=95,
            best_valid=True,
            issue_codes=[],
            source="auto_layout",
        )
    )
    db.add(
        LayoutRun(
            plan_version_id=plan.id,
            best_score=60,
            best_valid=False,
            issue_codes=["collision", "out_of_bounds"],
            source="auto_layout",
        )
    )
    db.commit()

    summary = generation_run_service.layout_scores_for_task(db, task_id=task.id)
    assert summary["count"] == 2
    assert summary["avg_score"] == 77.5
    assert summary["pass_rate"] == 0.5
    assert summary["issues"] == {"collision": 1, "out_of_bounds": 1}

    empty = generation_run_service.layout_scores_for_task(db, task_id=99999)
    assert empty["count"] == 0
    assert empty["avg_score"] is None
