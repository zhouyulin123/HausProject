from datetime import datetime, timedelta, timezone
import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.api.routes import tasks as task_routes
from app.db.models import (
    DesignResult,
    DesignRevision,
    DesignScene,
    DesignTask,
    GenerationRun,
    GenerationRunSceneEvidence,
    Product,
)
from app.core.request_context import current_request_id
from app.services import (
    design_version_service,
    generation_run_service,
    generation_scene_service,
    llm_service,
)
from app.services.layout_evaluator import HARD_FAIL_CODES, LayoutIssue, LayoutScore
from app.workers import generation_worker


def _persist_worker_output(db, task, *, generator: str):
    if db.scalar(select(Product).where(Product.sku == "SOFA-001")) is None:
        db.add(
            Product(
                sku="SOFA-001",
                name="测试沙发",
                category="沙发",
                room="客厅",
                style="现代",
                price=1000,
                is_active=True,
                data_origin="merchant",
                source_name="测试供应商",
                source_product_id="SOFA-001",
                source_retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                price_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                verification_status="verified",
                verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                verified_by="test:fixture",
                data_version="catalog-test-v1",
                availability_status="in_stock",
                stock_quantity=10,
                price_valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                price_valid_to=datetime(2030, 1, 1, tzinfo=timezone.utc),
                region_codes=["*"],
                model_width_mm=2200,
                model_height_mm=850,
                model_depth_mm=950,
            )
        )
        db.flush()
    return design_version_service.persist_generation(
        db,
        task=task,
        generator=generator,
        plans=[
            {
                "id": "plan-worker",
                "name": "Worker 方案",
                "style": "现代",
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
            request_id="worker-request-001",
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
        assert current_request_id() == "worker-request-001"
        executed.append(task.id)
        on_step({"node": "prepare_context", "status": "completed"})
        before_persist()
        revision = _persist_worker_output(db, task, generator="template")
        on_success("template", revision.id)
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
        assert completed.result_revision_id is not None
        assert completed.output_digest.startswith("sha256:")
        assert db.scalar(select(DesignScene.id)) is not None
        assert db.scalar(select(GenerationRunSceneEvidence.id)) is not None
        assert completed.attempt_count == 1
        assert completed.execution_deadline_at is not None
        assert (
            completed.execution_deadline_at - completed.started_at
        ).total_seconds() == 90
    assert executed == [task.id]


def test_worker_success_completes_bound_agent_checkpoint(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="running", progress=50)
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(
            db,
            task=task,
            idempotency_key="agent-generation:1:success",
            request_digest="sha256:" + "a" * 64,
        )
        task.agent_state_json = {
            "status": "running",
            "current_node": "generation_queued",
            "exit_reason": "generation_queued",
            "run_id": run.id,
            "result": {"run_id": run.id, "generation_status": "queued"},
        }
        db.commit()
        run_id = run.id
        task_id = task.id

    monkeypatch.setattr(generation_worker, "SessionLocal", factory)

    def executor(db, *, task, on_step, on_meta, before_persist, on_success):
        before_persist()
        revision = _persist_worker_output(db, task, generator="llm")
        on_success("llm", revision.id)
        return type("Response", (), {"generator": "llm"})()

    assert generation_worker.process_one_run(
        worker_id="agent-worker-success",
        executor=executor,
        start_heartbeat=False,
    )
    with factory() as db:
        task = db.get(DesignTask, task_id)
        completed_run = db.get(type(run), run_id)
        assert task is not None
        assert completed_run is not None
        assert task.agent_state_json["status"] == "completed"
        assert task.agent_state_json["current_node"] == "generation_completed"
        assert task.agent_state_json["exit_reason"] == "goal_completed"
        assert task.agent_state_json["run_id"] == run_id
        assert task.agent_state_json["result"] == {
            "run_id": run_id,
            "generation_status": "completed",
            "result_revision_id": completed_run.result_revision_id,
            "output_digest": completed_run.output_digest,
        }


@pytest.mark.parametrize("hard_code", sorted(HARD_FAIL_CODES))
def test_worker_never_completes_layout_with_hard_issue(monkeypatch, hard_code):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="running", progress=50)
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(
            db,
            task=task,
            idempotency_key=f"agent-generation:1:hard-layout-{hard_code}",
            request_digest="sha256:" + "d" * 64,
        )
        task.agent_state_json = {
            "status": "running",
            "current_node": "generation_queued",
            "exit_reason": "generation_queued",
            "run_id": run.id,
            "result": {"run_id": run.id, "generation_status": "queued"},
        }
        db.commit()
        run_id = run.id
        task_id = task.id

    original_generate_layouts = generation_scene_service.layout_generator.generate_layouts

    def invalid_layouts(room, openings, furniture, **kwargs):
        generated = original_generate_layouts(room, openings, furniture, **kwargs)
        scene, _ = generated[0]
        return [
            (
                scene,
                LayoutScore(
                    total=95,
                    issues=[LayoutIssue(code=hard_code, message="硬布局约束未通过")],
                ),
            )
        ]

    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(
        generation_scene_service.layout_generator,
        "generate_layouts",
        invalid_layouts,
    )

    def executor(db, *, task, on_step, on_meta, before_persist, on_success):
        before_persist()
        revision = _persist_worker_output(db, task, generator="llm")
        on_success("llm", revision.id)
        return type("Response", (), {"generator": "llm"})()

    assert generation_worker.process_one_run(
        worker_id=f"agent-worker-hard-layout-{hard_code}",
        executor=executor,
        start_heartbeat=False,
    )
    with factory() as db:
        task = db.get(DesignTask, task_id)
        failed_run = db.get(type(run), run_id)
        assert task is not None
        assert failed_run is not None
        assert failed_run.status == "failed"
        assert failed_run.result_revision_id is None
        assert failed_run.output_digest is None
        assert hard_code in (failed_run.error_message or "")
        assert task.agent_state_json["status"] == "needs_human"
        assert task.agent_state_json["exit_reason"] == "generation_failed"


@pytest.mark.parametrize(
    "idempotency_key",
    [
        "agent-generation:1:no-template",
        "client-selected-key:1:no-template",
    ],
)
def test_default_worker_disables_template_fallback_for_all_run_keys(
    monkeypatch,
    idempotency_key,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="running", progress=50)
        db.add(task)
        db.commit()
        generation_run_service.create_run(
            db,
            task=task,
            idempotency_key=idempotency_key,
            request_digest="sha256:" + "c" * 64,
        )

    allow_template_values: list[bool] = []

    def executor(
        db,
        *,
        task,
        on_step,
        on_meta,
        before_persist,
        on_success,
        allow_template_fallback,
    ):
        allow_template_values.append(allow_template_fallback)
        before_persist()
        revision = _persist_worker_output(db, task, generator="llm")
        on_success("llm", revision.id)
        return type("Response", (), {"generator": "llm"})()

    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(task_routes, "_execute_generation", executor)

    assert generation_worker.process_one_run(
        worker_id="agent-worker-no-template",
        start_heartbeat=False,
    )
    assert allow_template_values == [False]


def test_worker_commits_known_model_cost_before_later_execution_failure(
    monkeypatch,
):
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
            idempotency_key="worker-paid-then-failed",
            request_digest="sha256:" + "d" * 64,
        )
        run_id = run.id

    def executor(
        _db,
        *,
        task,
        on_step,
        on_meta,
        before_persist,
        on_success,
    ):
        on_meta(
            {
                "meta": {
                    "model": "provider/model",
                    "prompt_snapshot": "prompt",
                    "prompt_digest": "sha256:" + "1" * 64,
                    "rules_digest": "sha256:" + "2" * 64,
                    "data_digest": "sha256:" + "3" * 64,
                    "input_snapshot": {"task_id": task.id},
                    "input_digest": "sha256:" + "4" * 64,
                    "provenance_schema_version": 4,
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 25,
                        "total_tokens": 125,
                    },
                    "cost_cny": 0.0004,
                },
                "output_snapshot": {"accepted": False},
            }
        )
        raise RuntimeError("模型输出结构校验失败")

    monkeypatch.setattr(generation_worker, "SessionLocal", factory)

    assert generation_worker.process_one_run(
        worker_id="worker-paid-then-failed",
        executor=executor,
        start_heartbeat=False,
    )

    with factory() as db:
        failed = db.get(GenerationRun, run_id)
        assert failed is not None
        assert failed.status == "queued"
        assert failed.usage_json["total_tokens"] == 125
        assert failed.cost_cny == pytest.approx(0.0004)


def test_worker_budget_replan_exhaustion_moves_agent_to_explicit_needs_human(
    monkeypatch,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(
            status="running",
            progress=50,
            confirmed_requirement_json={"budget_max": 10_000},
        )
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(
            db,
            task=task,
            idempotency_key="agent-generation:1:budget-exhausted",
            request_digest="sha256:" + "e" * 64,
        )
        task.agent_state_json = {
            "status": "running",
            "current_node": "generation_queued",
            "exit_reason": "generation_queued",
            "retry_count": 0,
            "run_id": run.id,
            "result": {"run_id": run.id, "generation_status": "queued"},
        }
        db.commit()
        task_id = task.id
        run_id = run.id

    model_calls = 0

    class AlwaysOverBudgetWorkflow:
        def __init__(self, **_):
            pass

        def run(self, **_):
            nonlocal model_calls
            model_calls += 1
            guard = llm_service._model_cost_guard.get()
            assert guard is not None
            guard(0.1)
            return {
                "plans": [{
                    "id": "plan-a",
                    "name": "超预算方案",
                    "furnitureSuggestions": [{"id": "SOFA-001"}],
                    "shopQuote": {
                        "furnitureTotal": 12_000,
                        "customTotal": 0,
                        "total": 12_000,
                    },
                }],
                "generator": "llm",
                "node_trace": [],
            }

    worker_settings = SimpleNamespace(**generation_worker.settings.model_dump())
    worker_settings.generation_task_cost_limit_cny = 1.0
    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(generation_worker, "settings", worker_settings)
    monkeypatch.setattr(task_routes, "DesignWorkflow", AlwaysOverBudgetWorkflow)
    monkeypatch.setattr(
        task_routes.catalog_service,
        "build_catalog_context",
        lambda _: "SOFA-001|测试沙发",
    )
    monkeypatch.setattr(
        task_routes.llm_service,
        "last_generation_meta",
        lambda: {
            "model": "provider/model",
            "prompt_snapshot": "prompt",
            "input_snapshot": {"requirement": {"budget_max": 10_000}},
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
            "cost_cny": 0.1,
        },
    )

    assert generation_worker.process_one_run(
        worker_id="agent-worker-budget-exhausted",
        start_heartbeat=False,
    )
    with factory() as db:
        task = db.get(DesignTask, task_id)
        failed = db.get(type(run), run_id)
        assert task is not None
        assert failed is not None
        assert failed.status == "failed"
        assert failed.current_node == "budget_guard"
        assert failed.attempt_count == 1
        assert failed.cost_reserved_cny == pytest.approx(0.3)
        assert failed.cost_cny == pytest.approx(0.3)
        assert failed.usage_json["total_tokens"] == 45
        assert failed.result_revision_id is None
        assert task.status == "needs_human"
        assert task.agent_state_json["status"] == "needs_human"
        assert task.agent_state_json["current_node"] == "budget_guard"
        assert task.agent_state_json["exit_reason"] == "budget_replan_exhausted"
        assert task.agent_state_json["retry_count"] == 2
        assert task.agent_state_json["result"]["reason_code"] == (
            "budget_replan_exhausted"
        )
        assert [event.node for event in failed.events].count("budget_replan") == 2
        assert failed.events[-1].node == "budget_guard"
        assert failed.events[-1].detail_json["reason_code"] == (
            "budget_replan_exhausted"
        )
    assert model_calls == 3


def test_worker_budget_replan_success_completes_same_run_and_checkpoint(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(
            status="running",
            progress=50,
            confirmed_requirement_json={"budget_max": 10_000},
        )
        db.add(task)
        db.add(
            Product(
                sku="SOFA-001",
                name="测试沙发",
                category="沙发",
                room="客厅",
                style="现代",
                price=9_000,
                is_active=True,
                data_origin="merchant",
                source_name="测试供应商",
                source_product_id="SOFA-001",
                source_retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                price_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                verification_status="verified",
                verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                verified_by="test:fixture",
                data_version="catalog-test-v1",
                availability_status="in_stock",
                stock_quantity=10,
                price_valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                price_valid_to=datetime(2030, 1, 1, tzinfo=timezone.utc),
                region_codes=["*"],
                model_width_mm=2200,
                model_height_mm=850,
                model_depth_mm=950,
            )
        )
        db.commit()
        run = generation_run_service.create_run(
            db,
            task=task,
            idempotency_key="agent-generation:1:budget-replan-success",
            request_digest="sha256:" + "f" * 64,
        )
        task.agent_state_json = {
            "status": "running",
            "current_node": "generation_queued",
            "exit_reason": "generation_queued",
            "retry_count": 0,
            "run_id": run.id,
            "result": {"run_id": run.id, "generation_status": "queued"},
        }
        db.commit()
        task_id = task.id
        run_id = run.id

    totals = iter((12_000, 9_000))

    class ReplannedWorkflow:
        def __init__(self, **_):
            pass

        def run(self, **_):
            total = next(totals)
            return {
                "plans": [{
                    "id": "plan-a",
                    "name": "预算内方案",
                    "style": "现代",
                    "furnitureSuggestions": [{"id": "SOFA-001"}],
                    "shopQuote": {
                        "furnitureTotal": total,
                        "customTotal": 0,
                        "total": total,
                        "lineItems": [{
                            "sku": "SOFA-001",
                            "unitPrice": total,
                            "quantity": 1,
                        }],
                        "customLineItems": [],
                    },
                }],
                "generator": "llm",
                "node_trace": [],
            }

    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(task_routes, "DesignWorkflow", ReplannedWorkflow)
    monkeypatch.setattr(
        task_routes.catalog_service,
        "build_catalog_context",
        lambda _: "SOFA-001|测试沙发",
    )
    monkeypatch.setattr(task_routes.llm_service, "last_generation_meta", lambda: None)

    assert generation_worker.process_one_run(
        worker_id="agent-worker-budget-replan-success",
        start_heartbeat=False,
    )
    with factory() as db:
        task = db.get(DesignTask, task_id)
        completed = db.get(type(run), run_id)
        assert task is not None
        assert completed is not None
        assert completed.status == "completed"
        assert completed.attempt_count == 1
        assert len(db.scalars(select(type(run))).all()) == 1
        assert task.agent_state_json["status"] == "completed"
        assert task.agent_state_json["current_node"] == "generation_completed"
        assert task.agent_state_json["exit_reason"] == "goal_completed"
        assert task.agent_state_json["retry_count"] == 1
        assert [event.node for event in completed.events].count("budget_replan") == 1


def test_worker_static_version_drift_during_budget_replan_fails_without_retry(
    monkeypatch,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(
            status="running",
            progress=50,
            confirmed_requirement_json={"budget_max": 10_000},
        )
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(
            db,
            task=task,
            idempotency_key="agent-generation:1:static-drift",
            request_digest="sha256:" + "6" * 64,
            max_attempts=3,
        )
        task.agent_state_json = {
            "status": "running",
            "current_node": "generation_queued",
            "exit_reason": "generation_queued",
            "retry_count": 0,
            "run_id": run.id,
            "result": {"run_id": run.id, "generation_status": "queued"},
        }
        db.commit()
        task_id = task.id
        run_id = run.id

    totals = iter((12_000, 9_000))
    model_calls = 0

    class StaticDriftWorkflow:
        def __init__(self, **_):
            pass

        def run(self, **_):
            nonlocal model_calls
            model_calls += 1
            total = next(totals)
            return {
                "plans": [{
                    "id": "plan-a",
                    "name": "静态版本漂移方案",
                    "furnitureSuggestions": [{"id": "SOFA-001"}],
                    "shopQuote": {
                        "furnitureTotal": total,
                        "customTotal": 0,
                        "total": total,
                    },
                }],
                "generator": "llm",
                "node_trace": [],
            }

    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(task_routes, "DesignWorkflow", StaticDriftWorkflow)
    monkeypatch.setattr(
        task_routes.catalog_service,
        "build_catalog_context",
        lambda _: "SOFA-001|测试沙发",
    )
    monkeypatch.setattr(
        task_routes.llm_service,
        "last_generation_meta",
        lambda: {
            "model": "provider/model-v1" if model_calls == 1 else "provider/model-v2",
            "prompt_snapshot": "prompt",
            "input_snapshot": {
                "requirement": {"budget_max": 10_000},
                "model_call": model_calls,
            },
            "provenance_schema_version": 3,
            "usage": {"total_tokens": 15},
            "cost_cny": 0.1,
        },
    )

    assert generation_worker.process_one_run(
        worker_id="agent-worker-static-drift",
        start_heartbeat=False,
    )
    with factory() as db:
        task = db.get(DesignTask, task_id)
        failed = db.get(type(run), run_id)
        assert task is not None
        assert failed is not None
        assert failed.status == "failed"
        assert failed.attempt_count == 1
        assert failed.next_retry_at is None
        assert failed.result_revision_id is None
        assert "model" in (failed.error_message or "")
        assert task.status == "failed"
        assert task.agent_state_json["status"] == "needs_human"
    assert model_calls == 2


@pytest.mark.parametrize(
    ("boundary", "lease_seconds", "timeout_seconds", "advance_seconds", "expected"),
    [
        ("lease", 10, 120, 11, "queued"),
        ("deadline", 120, 10, 11, "dead_letter"),
    ],
)
def test_budget_replan_never_starts_after_worker_boundary_expires(
    monkeypatch,
    boundary,
    lease_seconds,
    timeout_seconds,
    advance_seconds,
    expected,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(
            status="confirmed",
            progress=50,
            confirmed_requirement_json={"budget_max": 10_000},
        )
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(db, task=task, max_attempts=3)
        run_id = run.id

    class MutableClock(datetime):
        current = datetime.now(timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    model_calls = 0

    class OverBudgetWorkflow:
        def __init__(self, **_):
            pass

        def run(self, **_):
            nonlocal model_calls
            model_calls += 1
            return {
                "plans": [{
                    "id": "plan-a",
                    "name": "超预算方案",
                    "furnitureSuggestions": [{"id": "SOFA-001"}],
                    "shopQuote": {
                        "furnitureTotal": 12_000,
                        "customTotal": 0,
                        "total": 12_000,
                    },
                }],
                "generator": "llm",
                "node_trace": [],
            }

    worker_settings = SimpleNamespace(**generation_worker.settings.model_dump())
    worker_settings.generation_worker_lease_seconds = lease_seconds
    worker_settings.generation_worker_execution_timeout_seconds = timeout_seconds
    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(generation_worker, "settings", worker_settings)
    monkeypatch.setattr(generation_run_service, "datetime", MutableClock)
    monkeypatch.setattr(task_routes, "DesignWorkflow", OverBudgetWorkflow)
    monkeypatch.setattr(
        task_routes.catalog_service,
        "build_catalog_context",
        lambda _: "SOFA-001|测试沙发",
    )
    monkeypatch.setattr(
        task_routes.llm_service,
        "last_generation_meta",
        lambda: {
            "model": "provider/model",
            "prompt_snapshot": "prompt",
            "input_snapshot": {"requirement": {"budget_max": 10_000}},
            "usage": {"total_tokens": 10},
            "cost_cny": 0.1,
        },
    )
    original_record_meta = generation_run_service.record_generation_meta

    def record_then_expire(*args, **kwargs):
        recorded = original_record_meta(*args, **kwargs)
        MutableClock.current += timedelta(seconds=advance_seconds)
        return recorded

    monkeypatch.setattr(
        generation_run_service,
        "record_generation_meta",
        record_then_expire,
    )

    assert generation_worker.process_one_run(
        worker_id=f"worker-budget-{boundary}",
        start_heartbeat=False,
    )
    with factory() as db:
        stopped = db.get(type(run), run_id)
        assert stopped is not None
        assert stopped.status == expected
        assert stopped.result_revision_id is None
    assert model_calls == 1


def test_worker_dead_letter_moves_bound_agent_checkpoint_to_needs_human(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="running", progress=50)
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(
            db,
            task=task,
            idempotency_key="agent-generation:1:failure",
            max_attempts=1,
            request_digest="sha256:" + "b" * 64,
        )
        task.agent_state_json = {
            "status": "running",
            "current_node": "generation_queued",
            "exit_reason": "generation_queued",
            "run_id": run.id,
            "result": {"run_id": run.id, "generation_status": "queued"},
        }
        db.commit()
        run_id = run.id
        task_id = task.id

    monkeypatch.setattr(generation_worker, "SessionLocal", factory)

    def executor(*_args, **_kwargs):
        raise RuntimeError("provider timeout")

    assert generation_worker.process_one_run(
        worker_id="agent-worker-failure",
        executor=executor,
        start_heartbeat=False,
    )
    with factory() as db:
        task = db.get(DesignTask, task_id)
        run = db.get(type(run), run_id)
        assert task is not None
        assert run is not None and run.status == "dead_letter"
        assert task.agent_state_json["status"] == "needs_human"
        assert task.agent_state_json["current_node"] == "generation_failed"
        assert task.agent_state_json["exit_reason"] == "generation_failed"
        assert task.agent_state_json["result"] == {
            "run_id": run_id,
            "generation_status": "dead_letter",
        }


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


def test_worker_rolls_back_result_but_preserves_cost_when_deadline_expires(
    monkeypatch,
):
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
        revision = _persist_worker_output(db, task, generator="llm")
        MutableClock.current += timedelta(seconds=31)
        on_success("llm", revision.id)

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
        assert expired.cost_cny == pytest.approx(9.9)
        assert expired.output_snapshot is None
        assert db.scalar(select(DesignResult)) is None
        assert db.scalar(select(DesignRevision)) is None
        assert task.status == "failed"


def test_worker_reserves_model_cost_before_provider_call(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="confirmed", progress=50)
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(db, task=task, max_attempts=3)
        run_id = run.id

    provider_calls = 0

    class Completions:
        def create(self, **kwargs):
            nonlocal provider_calls
            provider_calls += 1
            message = type("Message", (), {"content": "{}"})()
            choice = type("Choice", (), {"message": message})()
            usage = type(
                "Usage",
                (),
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            )()
            return type("Response", (), {"choices": [choice], "usage": usage})()

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    worker_settings = SimpleNamespace(**generation_worker.settings.model_dump())
    worker_settings.generation_task_cost_limit_cny = 1.0
    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(generation_worker, "settings", worker_settings)
    monkeypatch.setattr(llm_service, "get_client", lambda: client)
    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 8.0)

    def executor(db, *, task, on_step, on_meta, before_persist, on_success):
        llm_service._chat_json("system", "user", max_tokens=100)
        before_persist()
        revision = _persist_worker_output(db, task, generator="template")
        on_success("template", revision.id)
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
        assert completed.cost_reserved_cny > 0
        assert completed.cost_limit_cny == pytest.approx(1.0)
    assert provider_calls == 1


def test_worker_cost_limit_blocks_provider_without_retry_or_fake_success(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="confirmed", progress=50)
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(db, task=task, max_attempts=3)
        run_id = run.id
        task_id = task.id

    provider_calls = 0

    class Completions:
        def create(self, **kwargs):
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("超过成本上限后不能调用供应商")

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    worker_settings = SimpleNamespace(**generation_worker.settings.model_dump())
    worker_settings.generation_task_cost_limit_cny = 0.000001
    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(generation_worker, "settings", worker_settings)
    monkeypatch.setattr(llm_service, "get_client", lambda: client)
    monkeypatch.setattr(llm_service.settings, "llm_provider_key", "primary-llm")
    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 100.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 100.0)

    def executor(db, *, task, on_step, on_meta, before_persist, on_success):
        llm_service._chat_json("system", "user", max_tokens=100)

    assert generation_worker.process_one_run(
        worker_id="worker-a",
        executor=executor,
        start_heartbeat=False,
    )
    with factory() as db:
        blocked = db.get(type(run), run_id)
        task = db.get(DesignTask, task_id)
        assert blocked is not None
        assert task is not None
        assert blocked.status == "cost_limit_exceeded"
        assert blocked.attempt_count == 1
        assert blocked.next_retry_at is None
        assert blocked.cost_reserved_cny == pytest.approx(0.0)
        assert task.status == "needs_human"
        assert len(blocked.events) == 1
        assert blocked.events[0].node == "cost_guard"
        circuit_service = importlib.import_module(
            "app.services.provider_circuit_service"
        )
        assert (
            circuit_service.get_provider_state(db, "primary-llm") is None
        )
    assert provider_calls == 0


def test_worker_opens_persistent_circuit_and_next_run_fails_fast(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        first_task = DesignTask(status="confirmed", progress=50)
        db.add(first_task)
        db.commit()
        first_run = generation_run_service.create_run(
            db,
            task=first_task,
            idempotency_key="provider-failure-first",
            max_attempts=3,
        )
        first_task_id = first_task.id
        first_run_id = first_run.id

    provider_calls = 0

    class Completions:
        def create(self, **kwargs):
            nonlocal provider_calls
            provider_calls += 1
            raise TimeoutError("provider timed out")

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    worker_settings = SimpleNamespace(**generation_worker.settings.model_dump())
    worker_settings.generation_task_cost_limit_cny = 1.0
    worker_settings.provider_circuit_failure_threshold = 1
    worker_settings.provider_circuit_cooldown_seconds = 30
    worker_settings.provider_circuit_probe_lease_seconds = 10
    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(generation_worker, "settings", worker_settings)
    monkeypatch.setattr(llm_service, "get_client", lambda: client)
    monkeypatch.setattr(llm_service.settings, "llm_provider_key", "primary-llm")
    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 8.0)

    def executor(db, *, task, on_step, on_meta, before_persist, on_success):
        llm_service._chat_json("system", "user", max_tokens=100)

    assert generation_worker.process_one_run(
        worker_id="worker-a",
        executor=executor,
        start_heartbeat=False,
    )
    with factory() as db:
        first = db.get(type(first_run), first_run_id)
        task = db.get(DesignTask, first_task_id)
        assert first is not None
        assert task is not None
        assert first.status == "provider_unavailable"
        assert first.next_retry_at is None
        assert task.status == "needs_human"
        assert first.events[-1].node == "provider_circuit"
        assert (
            first.events[-1].detail_json["code"]
            == "provider_call_unavailable"
        )

        second_task = DesignTask(status="confirmed", progress=50)
        db.add(second_task)
        db.commit()
        second_run = generation_run_service.create_run(
            db,
            task=second_task,
            idempotency_key="provider-failure-second",
            max_attempts=3,
        )
        second_run_id = second_run.id

    assert generation_worker.process_one_run(
        worker_id="worker-b",
        executor=executor,
        start_heartbeat=False,
    )
    with factory() as db:
        second = db.get(type(first_run), second_run_id)
        assert second is not None
        assert second.status == "provider_unavailable"
        assert (
            second.events[-1].detail_json["code"]
            == "provider_circuit_open"
        )
    assert provider_calls == 1


def test_worker_code_error_does_not_increment_provider_circuit(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="confirmed", progress=50)
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(db, task=task, max_attempts=3)
        run_id = run.id

    class Completions:
        def create(self, **kwargs):
            raise ValueError("application parsing bug")

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    worker_settings = SimpleNamespace(**generation_worker.settings.model_dump())
    worker_settings.generation_task_cost_limit_cny = 1.0
    worker_settings.provider_circuit_failure_threshold = 1
    worker_settings.provider_circuit_cooldown_seconds = 30
    worker_settings.provider_circuit_probe_lease_seconds = 10
    monkeypatch.setattr(generation_worker, "SessionLocal", factory)
    monkeypatch.setattr(generation_worker, "settings", worker_settings)
    monkeypatch.setattr(llm_service, "get_client", lambda: client)
    monkeypatch.setattr(llm_service.settings, "llm_provider_key", "primary-llm")
    monkeypatch.setattr(llm_service.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(llm_service.settings, "llm_output_price_per_mtok", 8.0)

    def executor(db, *, task, on_step, on_meta, before_persist, on_success):
        llm_service._chat_json("system", "user", max_tokens=100)

    assert generation_worker.process_one_run(
        worker_id="worker-a",
        executor=executor,
        start_heartbeat=False,
    )
    circuit_service = importlib.import_module(
        "app.services.provider_circuit_service"
    )
    with factory() as db:
        failed = db.get(type(run), run_id)
        state = circuit_service.get_provider_state(db, "primary-llm")
        assert failed is not None
        assert failed.status == "queued"
        assert state is None
