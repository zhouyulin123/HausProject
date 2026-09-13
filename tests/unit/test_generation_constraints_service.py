from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import tasks as task_routes
from app.db.database import Base
from app.db.models import DesignTask
from app.services import (
    catalog_service,
    design_version_service,
    generation_constraints_service,
    generation_request_service,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def _constrained_task(db) -> DesignTask:
    task = DesignTask(
        status="confirmed",
        budget_max=100_000,
        confirmed_requirement_json={
            "deliveryRegion": " cn-sh ",
            "budgetRange": "8-12万",
            "roomWidthM": 4.2,
            "roomDepth": 3.5,
            "ceilingHeight": 2.7,
        },
    )
    db.add(task)
    db.commit()
    return task


@pytest.mark.unit
def test_generation_context_normalizes_and_scopes_catalog(db, monkeypatch):
    task = _constrained_task(db)
    catalog_calls: list[dict] = []

    def fake_catalog(_db, **kwargs):
        catalog_calls.append(deepcopy(kwargs))
        return "SCOPED-CATALOG"

    monkeypatch.setattr(catalog_service, "build_catalog_context", fake_catalog)

    context = generation_constraints_service.build_generation_context(db, task)

    assert context.constraints.as_dict() == {
        "delivery_region": "CN-SH",
        "budget_max": 100_000,
        "room_width_m": 4.2,
        "room_depth_m": 3.5,
        "ceiling_height_m": 2.7,
    }
    assert context.requirement["delivery_region"] == "CN-SH"
    assert context.requirement["budget_max"] == 100_000
    assert context.requirement["room_width_m"] == 4.2
    assert context.requirement["room_depth_m"] == 3.5
    assert context.requirement["ceiling_height_m"] == 2.7
    assert catalog_calls[0].pop("at").tzinfo is not None
    assert catalog_calls == [{
        "region": "CN-SH",
        "max_dimensions_mm": {
            "width": 4200,
            "depth": 3500,
            "height": 2700,
        },
    }]
    assert "SCOPED-CATALOG" in context.catalog_context
    assert "CN-SH" in context.catalog_context


@pytest.mark.unit
def test_request_digest_uses_same_scoped_catalog_as_generation_context(
    db,
    monkeypatch,
):
    task = _constrained_task(db)
    catalog_calls: list[dict] = []

    def fake_catalog(_db, **kwargs):
        catalog_calls.append(deepcopy(kwargs))
        return f"CATALOG:{kwargs}"

    monkeypatch.setattr(catalog_service, "build_catalog_context", fake_catalog)

    digest = generation_request_service.build_request_digest(db, task)

    assert digest.startswith("sha256:")
    assert catalog_calls[0].pop("at").tzinfo is not None
    assert catalog_calls == [{
        "region": "CN-SH",
        "max_dimensions_mm": {
            "width": 4200,
            "depth": 3500,
            "height": 2700,
        },
    }]


@pytest.mark.unit
def test_formal_generation_executor_reuses_scope_for_prompt_and_enrichment(
    db,
    monkeypatch,
):
    task = _constrained_task(db)
    observed: dict = {}

    def fake_catalog(_db, **kwargs):
        observed["catalog_kwargs"] = deepcopy(kwargs)
        return "SCOPED-CATALOG"

    def fake_enrich(_db, plans, **kwargs):
        observed["enrich_kwargs"] = deepcopy(kwargs)
        for plan in plans:
            plan["furnitureSuggestions"] = [{"id": "SOFA-001"}]
            plan["shopQuote"] = {
                "furnitureTotal": 90_000,
                "customTotal": 0,
                "total": 90_000,
            }

    class CapturingWorkflow:
        def __init__(self, *, enrich_plans, **_kwargs):
            self.enrich_plans = enrich_plans

        def run(self, *, requirement, image_context, catalog_context):
            observed["requirement"] = deepcopy(requirement)
            observed["catalog_context"] = catalog_context
            plans = [{"id": "plan-a", "name": "约束方案"}]
            self.enrich_plans(plans)
            return {"plans": plans, "generator": "llm", "node_trace": []}

    monkeypatch.setattr(catalog_service, "build_catalog_context", fake_catalog)
    monkeypatch.setattr(catalog_service, "verify_and_enrich_plans", fake_enrich)
    monkeypatch.setattr(task_routes, "DesignWorkflow", CapturingWorkflow)
    monkeypatch.setattr(task_routes.llm_service, "last_generation_meta", lambda: None)

    response = task_routes._execute_generation(db, task=task)

    expected_scope = {
        "region": "CN-SH",
        "budget_max": 100_000,
        "max_dimensions_mm": {
            "width": 4200,
            "depth": 3500,
            "height": 2700,
        },
    }
    assert response.generator == "llm"
    assert observed["catalog_kwargs"].pop("at").tzinfo is not None
    assert observed["catalog_kwargs"] == {
        "region": expected_scope["region"],
        "max_dimensions_mm": expected_scope["max_dimensions_mm"],
    }
    assert observed["enrich_kwargs"] == expected_scope
    assert observed["requirement"]["delivery_region"] == "CN-SH"
    assert observed["requirement"]["budget_max"] == 100_000
    assert observed["requirement"]["room_width_m"] == 4.2
    assert observed["requirement"]["room_depth_m"] == 3.5
    assert "SCOPED-CATALOG" in observed["catalog_context"]
    revision = design_version_service.get_latest_revision(db, task_id=task.id)
    assert revision.requirement_snapshot["delivery_region"] == "CN-SH"
    assert revision.requirement_snapshot["budget_max"] == 100_000
    assert revision.requirement_snapshot["room_width_m"] == 4.2


@pytest.mark.unit
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_generation_constraints_reject_non_finite_numbers(invalid):
    task = SimpleNamespace(budget_max=None)

    constraints = generation_constraints_service.constraints_for_task(
        task,
        requirement={
            "budget_max": invalid,
            "room_width_m": invalid,
            "room_depth_m": invalid,
            "ceiling_height_m": invalid,
        },
    )

    assert constraints.budget_max is None
    assert constraints.room_width_m is None
    assert constraints.room_depth_m is None
    assert constraints.ceiling_height_m is None
    assert constraints.catalog_kwargs() == {}


@pytest.mark.unit
def test_generation_constraints_reject_values_that_round_to_zero():
    constraints = generation_constraints_service.constraints_from_facts(
        {
            "budget_max": 0.1,
            "room_width_m": 0.0001,
            "room_depth_m": 0.0001,
        }
    )

    assert constraints.budget_max is None
    assert constraints.max_dimensions_mm() is None
    assert constraints.catalog_kwargs() == {}


@pytest.mark.unit
def test_total_budget_and_single_item_price_limit_are_not_conflated():
    constraints = generation_constraints_service.constraints_from_facts(
        {
            "budget_max": 100_000,
            "max_unit_price": 12_000,
        }
    )

    assert constraints.as_dict() == {
        "budget_max": 100_000,
        "max_unit_price": 12_000,
    }
    assert constraints.catalog_kwargs() == {"max_unit_price": 12_000}
    assert constraints.enrichment_kwargs() == {
        "budget_max": 100_000,
        "max_unit_price": 12_000,
    }


@pytest.mark.unit
def test_budget_range_parser_applies_units_to_each_endpoint():
    assert generation_constraints_service.parse_budget_range("5000-1万") == (
        5_000,
        10_000,
    )
    assert generation_constraints_service.parse_budget_range("1万-15000") == (
        10_000,
        15_000,
    )
