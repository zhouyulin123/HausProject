"""AI 不得越过冻结模型契约，迁移保持可回退。"""

import importlib.util
from pathlib import Path
import pytest
from sqlalchemy import create_engine, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.db.database import Base
from app.schemas.home_design import HomeDesignDocument
from app.services.home_design_agent_service import apply_plan
from tests.unit.test_home_design import document
from tests.unit.test_home_design_agent import plan


@pytest.mark.parametrize(
    "field,value",
    [
        ("size", {"width": 2, "height": 1, "depth": 1}),
        ("material", {"name": "木", "color": "#ffffff"}),
        ("position", {"x": 1, "y": 1, "z": 1}),
    ],
)
def test_agent_cannot_change_frozen_properties(field, value):
    raw = document()
    raw["objects"][0]["asset_id"] = 1
    with pytest.raises(ValueError):
        apply_plan(
            HomeDesignDocument.model_validate(raw),
            plan([{"type": "patch_object", "id": "o1", "changes": {field: value}}]),
        )


def test_agent_can_move_delete_but_not_add_asset():
    raw = document()
    raw["objects"][0]["asset_id"] = 1
    doc = HomeDesignDocument.model_validate(raw)
    moved = apply_plan(
        doc, plan([{"type": "patch_object", "id": "o1", "changes": {"rotation": 90}}])
    )
    assert moved.objects[0].asset_id == 1
    assert not apply_plan(doc, plan([{"type": "remove_object", "id": "o1"}])).objects
    raw["objects"][0]["id"] = "new"
    with pytest.raises(ValueError):
        apply_plan(doc, plan([{"type": "add_object", "object": raw["objects"][0]}]))


def test_assets_migration_upgrade_downgrade():
    path = (
        Path(__file__).resolve().parents[2]
        / "backend/migrations/versions/d4e5f6a7b8c9_add_home_design_assets.py"
    )
    spec = importlib.util.spec_from_file_location("assets_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE design_tasks (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert {
                c["name"] for c in inspect(connection).get_columns("home_design_assets")
            } == set(Base.metadata.tables["home_design_assets"].columns.keys())
            assert inspect(connection).get_unique_constraints("home_design_assets")[0][
                "column_names"
            ] == ["task_id", "client_mutation_id"]
            migration.downgrade()
            assert "home_design_assets" not in inspect(connection).get_table_names()
    engine.dispose()
