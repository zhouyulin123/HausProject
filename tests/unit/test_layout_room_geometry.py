"""无图任务的已确认尺寸必须进入房间几何，不能被预览默认值替代。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import DesignTask, UploadedImage
from app.services import layout_service
from tests.unit.test_room_model import _valid_room_model


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def task_with_facts(db, facts):
    task = DesignTask(confirmed_requirement_json=facts, space_type="客厅")
    db.add(task)
    db.flush()
    return task


def extents(room):
    return (
        max(p.x for p in room.floor_polygon) - min(p.x for p in room.floor_polygon),
        max(p.z for p in room.floor_polygon) - min(p.z for p in room.floor_polygon),
    )


@pytest.mark.parametrize("keys", [
    ("room_width_m", "room_depth_m", "ceiling_height_m"),
    ("roomWidthM", "roomDepthM", "ceilingHeightM"),
    ("roomWidth", "roomDepth", "ceilingHeight"),
])
@pytest.mark.parametrize("dimensions", [(4.8, 5.6, 2.9), (3.25, 4.75, 3.1), (8.2, 6.4, 4.0)])
def test_no_image_uses_complete_confirmed_dimensions(db, keys, dimensions):
    task = task_with_facts(db, dict(zip(keys, dimensions)))
    room, openings = layout_service._room_geometry_from_task(db, task.id)
    assert extents(room) == dimensions[:2]
    assert room.ceiling_height == dimensions[2]
    assert openings == []


@pytest.mark.parametrize("facts", [{}, {"room_width_m": 4.8}, {"room_depth_m": 5.6}])
def test_incomplete_dimensions_do_not_invent_missing_axis(db, facts):
    task = task_with_facts(db, facts)
    assert layout_service._room_geometry_from_task(db, task.id) is None


@pytest.mark.parametrize("value", [0, -2, True, "invalid", "nan", 51])
def test_invalid_complete_dimensions_are_rejected_not_defaulted(db, value):
    task = task_with_facts(db, {"room_width_m": value, "room_depth_m": 5.6})
    with pytest.raises(ValueError, match="已确认房间尺寸"):
        layout_service._room_geometry_from_task(db, task.id)


@pytest.mark.parametrize("height", [0, 1.8, 9, True, "nan"])
def test_invalid_confirmed_ceiling_is_not_replaced_with_default(db, height):
    task = task_with_facts(db, {"room_width_m": 4.8, "room_depth_m": 5.6, "ceiling_height_m": height})
    with pytest.raises(ValueError, match="已确认房间尺寸"):
        layout_service._room_geometry_from_task(db, task.id)


def test_existing_calibrated_room_model_keeps_geometry_and_openings(db):
    task = task_with_facts(db, {"room_width_m": 4.8, "room_depth_m": 5.6})
    model = _valid_room_model()
    model["rooms"][0].update(widthM=6.2, depthM=7.1, ceilingHeight=3.3)
    db.add(UploadedImage(task_id=task.id, file_name="plan.png", file_url="/uploads/plan.png", analysis_json={"room_model": model}))
    db.flush()
    room, openings = layout_service._room_geometry_from_task(db, task.id)
    assert extents(room) == (6.2, 7.1)
    assert room.ceiling_height == 3.3
    assert len(openings) == 2
