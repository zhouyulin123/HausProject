import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import (
    DesignTask,
    GenerationRun,
    GenerationRunEvent,
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
