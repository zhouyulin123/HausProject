import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import DesignPlanVersion, QuoteSnapshot, DesignTask
from app.services.design_version_service import (
    get_plan_version_for_user,
    get_revision,
    list_user_designs,
    persist_generation,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def _plans(total: int) -> list[dict]:
    return [
        {
            "id": "plan-a",
            "name": "暖居方案",
            "style": "奶油风",
            "shopQuote": {
                "furnitureTotal": total - 5000,
                "customTotal": 5000,
                "total": total,
            },
        },
        {
            "id": "plan-b",
            "name": "留白方案",
            "style": "现代简约",
            "shopQuote": {
                "furnitureTotal": total - 3000,
                "customTotal": 3000,
                "total": total,
            },
        },
    ]


@pytest.mark.unit
def test_persist_generation_creates_immutable_plan_and_quote_snapshots(db):
    task = DesignTask(
        status="completed",
        confirmed_requirement_json={"rooms": ["客厅"], "budgetRange": "8-15 万"},
    )
    db.add(task)
    db.commit()

    first = persist_generation(
        db,
        task=task,
        plans=_plans(36000),
        generator="llm",
        image_context=["客厅采光良好"],
        workflow_trace=[
            {
                "node": "calculate_quote",
                "status": "completed",
                "duration_ms": 8,
                "source": "deterministic",
            }
        ],
    )
    second = persist_generation(
        db,
        task=task,
        plans=_plans(42000),
        generator="llm",
        image_context=["客厅采光良好"],
    )
    db.commit()

    assert first.version == 1
    assert second.version == 2
    assert len(db.scalars(select(DesignPlanVersion)).all()) == 4
    assert len(db.scalars(select(QuoteSnapshot)).all()) == 4

    restored = get_revision(db, task_id=task.id, version=1)
    assert restored is not None
    assert restored.requirement_snapshot["rooms"] == ["客厅"]
    assert restored.workflow_trace_snapshot[0]["node"] == "calculate_quote"
    assert restored.plans[0].quote_snapshot.grand_total == 36000
    assert restored.plans[0].plan_json["name"] == "暖居方案"


@pytest.mark.unit
def test_list_user_designs_returns_latest_plans_for_owner(db):
    task = DesignTask(
        status="completed",
        user_id=42,
        style="奶油风",
        space_type="客厅",
    )
    db.add(task)
    db.commit()
    persist_generation(db, task=task, plans=_plans(36000), generator="llm")
    db.commit()

    designs = list_user_designs(db, user_id=42)
    assert len(designs) == 1
    assert designs[0]["task_id"] == task.id
    assert designs[0]["style"] == "奶油风"
    assert designs[0]["space_type"] == "客厅"
    assert len(designs[0]["plans"]) == 2
    assert designs[0]["plans"][0]["planKey"] == "plan-a"
    assert designs[0]["plans"][0]["planVersionId"] is not None

    # 其他用户看不到
    assert list_user_designs(db, user_id=999) == []


@pytest.mark.unit
def test_get_plan_version_for_user_checks_ownership(db):
    task = DesignTask(status="completed", user_id=42)
    db.add(task)
    db.commit()
    persist_generation(db, task=task, plans=_plans(36000), generator="llm")
    db.commit()

    plan_version = db.scalar(
        select(DesignPlanVersion).where(DesignPlanVersion.plan_key == "plan-a")
    )
    assert plan_version is not None

    found = get_plan_version_for_user(
        db,
        plan_version_id=plan_version.id,
        user_id=42,
    )
    assert found is not None
    assert found.id == plan_version.id

    # 其他用户查不到，避免越权
    assert (
        get_plan_version_for_user(
            db,
            plan_version_id=plan_version.id,
            user_id=999,
        )
        is None
    )
