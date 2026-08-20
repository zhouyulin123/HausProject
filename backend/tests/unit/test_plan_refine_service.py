import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import DesignScene, DesignTask
from app.services import (
    catalog_service,
    design_version_service,
    llm_service,
    plan_refine_service,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def _initial_plans():
    return [
        {
            "id": "plan-a",
            "name": "暖居",
            "style": "奶油风",
            "budget": 100000,
            "furnitureSuggestions": [{"id": "SKU-1"}],
            "shopQuote": {"furnitureTotal": 100, "customTotal": 50, "total": 150},
        },
        {
            "id": "plan-b",
            "name": "留白",
            "style": "现代简约",
            "budget": 90000,
            "furnitureSuggestions": [{"id": "SKU-2"}],
            "shopQuote": {"furnitureTotal": 100, "customTotal": 50, "total": 150},
        },
    ]


@pytest.mark.unit
def test_refine_plan_version_writes_new_revision(db, monkeypatch):
    task = DesignTask(
        status="completed",
        confirmed_requirement_json={"rooms": ["客厅"]},
    )
    db.add(task)
    db.commit()
    design_version_service.persist_generation(
        db,
        task=task,
        plans=_initial_plans(),
        generator="llm",
    )
    db.commit()

    def fake_refine(plan, instruction, catalog):
        refined = dict(plan)
        refined["style"] = "暖调奶油风"
        return refined, "已调整风格"

    def fake_enrich(db, plans_list):
        for p in plans_list:
            p["furnitureSuggestions"] = [{"id": "SKU-1", "name": "沙发"}]
            p["shopQuote"] = {
                "furnitureTotal": 100,
                "customTotal": 50,
                "total": 150,
            }

    monkeypatch.setattr(llm_service, "refine_plan", fake_refine)
    monkeypatch.setattr(catalog_service, "verify_and_enrich_plans", fake_enrich)
    monkeypatch.setattr(catalog_service, "build_catalog_context", lambda db: "")

    result = plan_refine_service.refine_plan_version(
        db,
        task=task,
        plan_id="plan-a",
        instruction="换个暖色调",
    )
    assert result["plan"]["style"] == "暖调奶油风"
    assert result["version"] == 2
    assert result["plan"]["planVersionId"] is not None

    # 新版本里 plan-b 保持不变
    latest = design_version_service.get_latest_revision(db, task_id=task.id)
    assert latest.version == 2
    plan_b = next(p for p in latest.plans if p.plan_key == "plan-b")
    assert plan_b.plan_json["style"] == "现代简约"


@pytest.mark.unit
def test_refine_plan_version_missing_plan_raises(db):
    task = DesignTask(status="completed")
    db.add(task)
    db.commit()
    design_version_service.persist_generation(
        db,
        task=task,
        plans=_initial_plans(),
        generator="llm",
    )
    db.commit()

    with pytest.raises(plan_refine_service.PlanRefineError):
        plan_refine_service.refine_plan_version(
            db,
            task=task,
            plan_id="plan-c",
            instruction="随便改改",
        )


@pytest.mark.unit
def test_refine_plan_version_inherits_3d_scene(db, monkeypatch):
    task = DesignTask(
        status="completed",
        confirmed_requirement_json={"rooms": ["客厅"]},
    )
    db.add(task)
    db.commit()
    revision = design_version_service.persist_generation(
        db,
        task=task,
        plans=_initial_plans(),
        generator="llm",
    )
    db.commit()

    old_plan_a = next(p for p in revision.plans if p.plan_key == "plan-a")
    scene = DesignScene(plan_version_id=old_plan_a.id, current_version=1)
    db.add(scene)
    db.commit()

    def fake_refine(plan, instruction, catalog):
        refined = dict(plan)
        refined["style"] = "暖调奶油风"
        return refined, "已调整风格"

    def fake_enrich(db, plans_list):
        for p in plans_list:
            p["furnitureSuggestions"] = [{"id": "SKU-1", "name": "沙发"}]
            p["shopQuote"] = {
                "furnitureTotal": 100,
                "customTotal": 50,
                "total": 150,
            }

    monkeypatch.setattr(llm_service, "refine_plan", fake_refine)
    monkeypatch.setattr(catalog_service, "verify_and_enrich_plans", fake_enrich)
    monkeypatch.setattr(catalog_service, "build_catalog_context", lambda db: "")

    result = plan_refine_service.refine_plan_version(
        db,
        task=task,
        plan_id="plan-a",
        instruction="换个暖色调",
    )
    new_plan_version_id = result["plan"]["planVersionId"]

    db.refresh(scene)
    assert scene.plan_version_id == new_plan_version_id
    assert scene.id is not None
