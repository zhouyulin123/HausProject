from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import DesignTask
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
    executed: list[int] = []

    def executor(db, *, task, on_step, on_meta, before_persist):
        executed.append(task.id)
        on_step({"node": "prepare_context", "status": "completed"})
        before_persist()
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
