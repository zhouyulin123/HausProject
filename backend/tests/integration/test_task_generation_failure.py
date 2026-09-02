import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import tasks as task_routes
from app.db.database import Base
from app.db.models import DesignTask
from app.services.design_version_service import get_latest_revision
from app.services.generation_provenance import build_generation_provenance
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)


@pytest.mark.integration
def test_generate_design_persists_failed_status(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as db:
        anonymous_session = create_anonymous_session(db)
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
        attach_task(db, anonymous_session.id, task.id)

        monkeypatch.setattr(
            task_routes.catalog_service,
            "build_catalog_context",
            lambda _: (_ for _ in ()).throw(RuntimeError("商品库暂时不可用")),
        )

        with pytest.raises(HTTPException) as exc_info:
            task_routes.generate_design(task.id, anonymous_session.id, db)

        db.refresh(task)
        assert exc_info.value.status_code == 500
        assert task.status == "failed"
        assert task.progress == 0
        assert "商品库暂时不可用" in (task.error_message or "")


@pytest.mark.integration
def test_generate_design_persists_langgraph_node_trace(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as db:
        anonymous_session = create_anonymous_session(db)
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
        attach_task(db, anonymous_session.id, task.id)

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
            lambda _: "SOFA-001|原木沙发",
        )

        response = task_routes.generate_design(
            task.id,
            anonymous_session.id,
            db,
        )

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

        class FakeWorkflow:
            def run(self, **_):
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
            lambda _: catalog_context,
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
            catalog_context=catalog_context,
            plans=plans,
        )
        assert emitted[0]["meta"] == {
            "model": "model-runtime-v3",
            "prompt_snapshot": prompt_snapshot,
            "input_snapshot": {"requirement": {"rooms": ["客厅"]}},
            "usage": None,
            "cost_cny": None,
            **expected,
        }
