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
