import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import tasks as task_routes
from app.db.database import Base
from app.db.models import DesignTask
from app.services.design_version_service import get_latest_revision
from app.services.generation_provenance import build_generation_provenance
from app.services import generation_run_service


@pytest.mark.integration
def test_generate_design_persists_failed_status(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as db:
        task = DesignTask(
            status="confirmed",
            progress=50,
            confirmed_requirement_json={
                "rooms": ["客厅"],
                "budgetRange": "8-15 万",
                "styles": ["现代简约"],
            },
        )
        db.add(task)
        db.commit()
        monkeypatch.setattr(
            task_routes.catalog_service,
            "build_catalog_context",
            lambda _db, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("商品库暂时不可用")
            ),
        )

        with pytest.raises(HTTPException) as exc_info:
            task_routes._execute_generation(db, task=task)

        db.refresh(task)
        assert exc_info.value.status_code == 500
        assert task.status == "failed"
        assert task.progress == 0
        assert "商品库暂时不可用" in (task.error_message or "")


@pytest.mark.integration
def test_agent_worker_generation_does_not_turn_llm_failure_into_template_success(
    monkeypatch,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as db:
        task = DesignTask(
            status="running",
            progress=50,
            confirmed_requirement_json={"rooms": ["客厅"]},
        )
        db.add(task)
        db.commit()
        monkeypatch.setattr(
            task_routes.llm_service,
            "generate_plans",
            lambda *_: (_ for _ in ()).throw(
                task_routes.llm_service.LLMUnavailable("provider timeout")
            ),
        )
        monkeypatch.setattr(
            task_routes.catalog_service,
            "build_catalog_context",
            lambda _db, **_kwargs: "",
        )

        with pytest.raises(HTTPException):
            task_routes._execute_generation(
                db,
                task=task,
                allow_template_fallback=False,
            )

        assert get_latest_revision(db, task_id=task.id) is None


@pytest.mark.integration
def test_generate_design_persists_langgraph_node_trace(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as db:
        task = DesignTask(
            status="confirmed",
            progress=50,
            confirmed_requirement_json={
                "rooms": ["客厅"],
                "styles": ["原木风"],
            },
        )
        db.add(task)
        db.commit()
        class FakeWorkflow:
            def run(self, **_):
                return {
                    "plans": [
                        {
                            "id": "plan-a",
                            "name": "暖居方案",
                            "style": "原木风",
                            "furnitureSuggestions": [{"id": "SOFA-001"}],
                            "shopQuote": {
                                "furnitureTotal": 5000,
                                "customTotal": 3000,
                                "total": 8000,
                            },
                        }
                    ],
                    "generator": "llm",
                    "node_trace": [
                        {
                            "node": "validate_quality",
                            "status": "completed",
                            "duration_ms": 2,
                            "source": "deterministic",
                        }
                    ],
                }

        monkeypatch.setattr(
            task_routes,
            "DesignWorkflow",
            lambda **_: FakeWorkflow(),
        )
        monkeypatch.setattr(
            task_routes.catalog_service,
            "build_catalog_context",
            lambda _db, **_kwargs: "SOFA-001|原木沙发",
        )

        response = task_routes._execute_generation(db, task=task)

        revision = get_latest_revision(db, task_id=task.id)
        assert response.generator == "llm"
        assert revision is not None
        assert revision.workflow_trace_snapshot[0]["node"] == "validate_quality"


@pytest.mark.integration
def test_generation_emits_provenance_from_actual_prompt_rules_and_catalog(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as db:
        task = DesignTask(
            status="confirmed",
            progress=50,
            confirmed_requirement_json={"rooms": ["客厅"]},
        )
        db.add(task)
        db.commit()
        plans = [
            {
                "id": "plan-a",
                "name": "方案 A",
                "style": "现代简约",
                "furnitureSuggestions": [{"id": "SOFA-001"}],
                "shopQuote": {
                    "furnitureTotal": 5000,
                    "customTotal": 0,
                    "total": 5000,
                    "catalogVersion": "catalog-runtime-v7",
                    "ruleVersion": "rules-runtime-v4",
                },
            }
        ]

        observed = {}

        class FakeWorkflow:
            def run(self, **kwargs):
                observed["catalog_context"] = kwargs["catalog_context"]
                return {
                    "plans": plans,
                    "generator": "llm",
                    "node_trace": [],
                }

        catalog_context = "actual runtime catalog context"
        prompt_snapshot = "actual runtime prompt snapshot"
        monkeypatch.setattr(task_routes, "DesignWorkflow", lambda **_: FakeWorkflow())
        monkeypatch.setattr(
            task_routes.catalog_service,
            "build_catalog_context",
            lambda _db, **_kwargs: catalog_context,
        )
        monkeypatch.setattr(
            task_routes.llm_service,
            "last_generation_meta",
            lambda: {
                "model": "model-runtime-v3",
                "prompt_snapshot": prompt_snapshot,
                "input_snapshot": {"requirement": {"rooms": ["客厅"]}},
                "usage": None,
                "cost_cny": None,
            },
        )
        emitted = []

        task_routes._execute_generation(db, task=task, on_meta=emitted.append)

        expected = build_generation_provenance(
            prompt_snapshot=prompt_snapshot,
            input_snapshot={"requirement": {"rooms": ["客厅"]}},
            catalog_context=observed["catalog_context"],
        )
        assert catalog_context in observed["catalog_context"]
        assert emitted[0]["meta"] == {
            "model": "model-runtime-v3",
            "prompt_snapshot": prompt_snapshot,
            "input_snapshot": {"requirement": {"rooms": ["客厅"]}},
            "usage": None,
            "cost_cny": None,
            **expected,
        }


@pytest.mark.integration
def test_paid_model_failure_before_template_fallback_accumulates_run_cost(
    monkeypatch,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    plans = [{
        "id": "plan-a",
        "name": "受控降级方案",
        "style": "现代简约",
        "furnitureSuggestions": [],
        "shopQuote": {
            "furnitureTotal": 0,
            "customTotal": 0,
            "total": 0,
        },
    }]

    class FallbackWorkflow:
        def run(self, **_):
            return {
                "plans": plans,
                "generator": "template",
                "node_trace": [],
            }

    monkeypatch.setattr(task_routes, "DesignWorkflow", lambda **_: FallbackWorkflow())
    monkeypatch.setattr(
        task_routes.catalog_service,
        "build_catalog_context",
        lambda _db, **_kwargs: "catalog",
    )
    monkeypatch.setattr(
        task_routes.llm_service,
        "last_generation_meta",
        lambda: {
            "model": "provider/model",
            "prompt_snapshot": "prompt",
            "input_snapshot": {"requirement": {"space_type": "客厅"}},
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 25,
                "total_tokens": 125,
            },
            "cost_cny": 0.0004,
        },
    )

    with session_factory() as db:
        task = DesignTask(
            status="confirmed",
            progress=50,
            confirmed_requirement_json={"space_type": "客厅"},
        )
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(db, task=task)

        def persist_meta(payload):
            generation_run_service.record_generation_meta(
                db,
                run=run,
                meta=payload["meta"],
                output_snapshot=payload["output_snapshot"],
                commit=False,
            )

        response = task_routes._execute_generation(
            db,
            task=task,
            on_meta=persist_meta,
            allow_template_fallback=True,
        )
        db.refresh(run)

        assert response.generator == "template"
        assert run.usage_json["total_tokens"] == 125
        assert run.cost_cny == pytest.approx(0.0004)


@pytest.mark.integration
def test_generation_replans_once_when_first_deterministic_quote_exceeds_budget(
    monkeypatch,
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    workflow_requirements: list[dict] = []
    totals = iter((12_000, 9_000))

    class FakeWorkflow:
        def __init__(self, **_):
            pass

        def run(self, *, requirement, **_):
            workflow_requirements.append(requirement)
            total = next(totals)
            return {
                "plans": [{
                    "id": "plan-a",
                    "name": "预算重规划方案",
                    "style": "现代简约",
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

    monkeypatch.setattr(task_routes, "DesignWorkflow", FakeWorkflow)
    monkeypatch.setattr(
        task_routes.catalog_service,
        "build_catalog_context",
        lambda _db, **_kwargs: "SOFA-001|测试沙发",
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

    with session_factory() as db:
        task = DesignTask(
            status="confirmed",
            progress=50,
            confirmed_requirement_json={"budget_max": 10_000},
        )
        db.add(task)
        db.commit()
        emitted_steps: list[dict] = []
        emitted_meta: list[dict] = []

        response = task_routes._execute_generation(
            db,
            task=task,
            on_step=emitted_steps.append,
            on_meta=emitted_meta.append,
        )

        revision = get_latest_revision(db, task_id=task.id)
        assert response.status == "completed"
        assert revision is not None
        assert revision.plans[0].quote_snapshot.grand_total == 9_000

    assert len(workflow_requirements) == 2
    assert workflow_requirements[1]["budget_replan"] == {
        "reason_code": "budget_exceeded",
        "retry_count": 1,
        "max_retries": 2,
        "budget_max": 10_000,
        "previous_plan_totals": [12_000],
    }
    assert [step for step in emitted_steps if step["node"] == "budget_replan"] == [
        {
            "node": "budget_replan",
            "status": "completed",
            "source": "deterministic",
            "reason_code": "budget_exceeded",
            "retry_count": 1,
            "max_retries": 2,
            "budget_max": 10_000,
            "previous_plan_totals": [12_000],
        }
    ]
    assert len(emitted_meta) == 2


@pytest.mark.integration
def test_generation_budget_replan_exhaustion_is_not_wrapped_as_http_500(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    class AlwaysOverBudgetWorkflow:
        def __init__(self, **_):
            pass

        def run(self, **_):
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

    monkeypatch.setattr(task_routes, "DesignWorkflow", AlwaysOverBudgetWorkflow)
    monkeypatch.setattr(
        task_routes.catalog_service,
        "build_catalog_context",
        lambda _db, **_kwargs: "SOFA-001|测试沙发",
    )
    with session_factory() as db:
        task = DesignTask(
            status="confirmed",
            progress=50,
            confirmed_requirement_json={"budget_max": 10_000},
        )
        db.add(task)
        db.commit()

        with pytest.raises(generation_run_service.GenerationBudgetReplanExhausted) as caught:
            task_routes._execute_generation(db, task=task)

        assert caught.value.reason_code == "budget_replan_exhausted"
        assert caught.value.retry_count == 2
