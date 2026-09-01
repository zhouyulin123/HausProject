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
)
from app.services import generation_run_service


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
    assert generation_run_service.mark_completed(
        db,
        run_id=claimed.id,
        worker_id="worker-a",
        worker_attempt=1,
        generator="llm",
    )
    db.refresh(claimed)
    assert claimed.status == "completed"
    assert claimed.worker_id is None
    assert claimed.lease_expires_at is None


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
    assert terminal == "failed"
    assert second.status == "failed"
    assert second.next_retry_at is None


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
        lease_seconds=10,
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
    assert run.usage_json["total_tokens"] == 2000
    assert run.cost_cny == 0.0028


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
