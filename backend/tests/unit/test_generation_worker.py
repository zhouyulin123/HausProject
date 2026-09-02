from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import DesignResult, DesignTask
from app.services import generation_run_service
from app.workers import generation_worker


def test_worker_claims_and_completes_one_generation(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="confirmed", progress=50)
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(
            db,
            task=task,
            idempotency_key="worker-success-001",
            max_attempts=3,
        )
        run_id = run.id

    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(
        generation_worker.settings,
        "generation_worker_execution_timeout_seconds",
        90,
    )
    executed: list[int] = []

    def executor(db, *, task, on_step, on_meta, before_persist, on_success):
        executed.append(task.id)
        on_step({"node": "prepare_context", "status": "completed"})
        before_persist()
        on_success("template")
        return type("Response", (), {"generator": "template"})()

    assert generation_worker.process_one_run(
        worker_id="worker-a",
        executor=executor,
        start_heartbeat=False,
    )
    with factory() as db:
        completed = db.get(type(run), run_id)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.attempt_count == 1
        assert completed.execution_deadline_at is not None
        assert (
            completed.execution_deadline_at - completed.started_at
        ).total_seconds() == 90
    assert executed == [task.id]


def test_worker_requeues_retryable_execution_failure(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="confirmed", progress=50)
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(
            db,
            task=task,
            idempotency_key="worker-failure-001",
            max_attempts=3,
        )
        run_id = run.id

    monkeypatch.setattr(generation_worker, "SessionLocal", factory)

    def executor(*args, **kwargs):
        raise RuntimeError("provider timeout")

    assert generation_worker.process_one_run(
        worker_id="worker-a",
        executor=executor,
        start_heartbeat=False,
    )
    with factory() as db:
        failed = db.get(type(run), run_id)
        assert failed is not None
        assert failed.status == "queued"
        assert failed.next_retry_at is not None
        assert failed.worker_id is None


def test_worker_rolls_back_result_and_cost_when_deadline_expires(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="confirmed", progress=50)
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(
            db,
            task=task,
            idempotency_key="worker-deadline-001",
            max_attempts=3,
        )
        run_id = run.id
        task_id = task.id

    class MutableClock(datetime):
        current = datetime.now(timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(generation_run_service, "datetime", MutableClock)
    monkeypatch.setattr(
        generation_worker.settings,
        "generation_worker_execution_timeout_seconds",
        30,
    )

    def executor(db, *, task, on_step, on_meta, before_persist, on_success):
        before_persist()
        on_meta(
            {
                "meta": {"model": "provider/model", "cost_cny": 9.9},
                "output_snapshot": {"plan_count": 1},
            }
        )
        db.add(
            DesignResult(
                task_id=task.id,
                plans_json=[{"name": "过期方案"}],
                generator="llm",
            )
        )
        MutableClock.current += timedelta(seconds=31)
        on_success("llm")

    assert generation_worker.process_one_run(
        worker_id="worker-a",
        executor=executor,
        start_heartbeat=False,
    )
    with factory() as db:
        expired = db.get(type(run), run_id)
        task = db.get(DesignTask, task_id)
        assert expired is not None
        assert task is not None
        assert expired.status == "dead_letter"
        assert expired.cost_cny is None
        assert expired.output_snapshot is None
        assert db.scalar(select(DesignResult)) is None
        assert task.status == "failed"
