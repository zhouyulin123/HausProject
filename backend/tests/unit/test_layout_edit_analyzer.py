from app.schemas.scenes import (
    PositiveVector3,
    RoomGeometry,
    SceneDocument,
    SceneItem,
    Transform,
    Vector2XZ,
    Vector3,
)
from app.services.layout_service import (
    analyze_manual_edits,
    diff_scene_items,
    summarize_edits,
)


def _item(instance_id: str, sku: str, category: str, x: float, z: float, rot_y: float = 0.0):
    return SceneItem(
        instance_id=instance_id,
        sku=sku,
        category=category,
        transform=Transform(
            position=Vector3(x=x, y=0, z=z),
            rotation=Vector3(x=0, y=rot_y, z=0),
            scale=PositiveVector3(x=1, y=1, z=1),
        ),
    )


def _scene(items: list[SceneItem]) -> SceneDocument:
    return SceneDocument(
        room=RoomGeometry(
            id="r1",
            name="卧室",
            floor_polygon=[
                Vector2XZ(x=-2, z=-2),
                Vector2XZ(x=2, z=-2),
                Vector2XZ(x=2, z=2),
                Vector2XZ(x=-2, z=2),
            ],
            ceiling_height=2.8,
        ),
        items=items,
    )


def test_diff_scene_items_detects_move_remove_add():
    before = _scene(
        [
            _item("bed-1", "BED-001", "床", 0.0, -1.0),
            _item("cab-1", "CAB-001", "柜子", 1.5, 0.0),
        ]
    )
    after = _scene(
        [
            _item("bed-1", "BED-001", "床", 0.5, -1.0),  # 平移 0.5m
            _item("desk-1", "DESK-001", "书桌", -1.5, 0.0),  # 新增
        ]
    )

    diffs = diff_scene_items(before, after)
    by_kind = {d["kind"] for d in diffs}
    assert by_kind == {"moved", "removed", "added"}

    moved = next(d for d in diffs if d["kind"] == "moved")
    assert moved["instance_id"] == "bed-1"
    assert moved["distance"] == 0.5

    removed = next(d for d in diffs if d["kind"] == "removed")
    assert removed["instance_id"] == "cab-1"

    added = next(d for d in diffs if d["kind"] == "added")
    assert added["instance_id"] == "desk-1"


def test_diff_scene_items_ignores_unchanged():
    before = _scene([_item("bed-1", "BED-001", "床", 0.0, -1.0)])
    after = _scene([_item("bed-1", "BED-001", "床", 0.0, -1.0)])
    assert diff_scene_items(before, after) == []


def test_diff_scene_items_detects_rotation():
    before = _scene([_item("bed-1", "BED-001", "床", 0.0, -1.0, rot_y=0.0)])
    after = _scene([_item("bed-1", "BED-001", "床", 0.0, -1.0, rot_y=1.5708)])
    diffs = diff_scene_items(before, after)
    assert len(diffs) == 1
    assert diffs[0]["kind"] == "moved"
    assert abs(diffs[0]["rotation_delta"] - 1.5708) < 0.01


def test_summarize_edits_ranks_most_edited_category():
    diffs = [
        {"instance_id": "bed-1", "sku": "BED-001", "category": "床", "kind": "moved", "distance": 1.0},
        {"instance_id": "cab-1", "sku": "CAB-001", "category": "柜子", "kind": "removed", "distance": None},
        {"instance_id": "desk-1", "sku": "DESK-001", "category": "书桌", "kind": "added", "distance": None},
    ]
    summary = summarize_edits(diffs)
    assert summary["moved_count"] == 1
    assert summary["removed_count"] == 1
    assert summary["added_count"] == 1
    assert summary["top_moved_categories"][0]["category"] == "床"
    assert summary["top_moved_categories"][0]["avg_distance_m"] == 1.0


def test_analyze_manual_edits_from_db():
    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.database import Base
    from app.db.models import (
        DesignPlanVersion,
        DesignRevision,
        DesignScene,
        DesignSceneVersion,
        DesignTask,
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()

    task = DesignTask(status="completed", progress=100)
    db.add(task)
    db.commit()
    revision = DesignRevision(
        task_id=task.id, version=1, requirement_snapshot={}, generator="llm"
    )
    db.add(revision)
    db.commit()
    plan = DesignPlanVersion(
        revision_id=revision.id, plan_key="plan-a", plan_name="暖居", plan_json={}
    )
    db.add(plan)
    db.commit()
    scene = DesignScene(plan_version_id=plan.id, current_version=2)
    db.add(scene)
    db.commit()

    auto_doc = _scene([_item("bed-1", "BED-001", "床", 0.0, -1.0)])
    manual_doc = _scene([_item("bed-1", "BED-001", "床", 0.8, -1.0)])
    db.add(
        DesignSceneVersion(
            scene_id=scene.id,
            version=1,
            scene_json=auto_doc.model_dump(mode="json"),
            validation_json={},
            source="auto_layout",
        )
    )
    db.add(
        DesignSceneVersion(
            scene_id=scene.id,
            version=2,
            scene_json=manual_doc.model_dump(mode="json"),
            validation_json={},
            source="manual",
        )
    )
    db.commit()

    result = analyze_manual_edits(db, scene)
    assert result["edited"] is True
    assert result["moved_count"] == 1
    assert result["top_moved_categories"][0]["category"] == "床"

    db.close()


def test_analyze_manual_edits_without_auto_layout():
    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.database import Base
    from app.db.models import (
        DesignPlanVersion,
        DesignRevision,
        DesignScene,
        DesignTask,
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()

    task = DesignTask(status="completed", progress=100)
    db.add(task)
    db.commit()
    revision = DesignRevision(
        task_id=task.id, version=1, requirement_snapshot={}, generator="llm"
    )
    db.add(revision)
    db.commit()
    plan = DesignPlanVersion(
        revision_id=revision.id, plan_key="plan-a", plan_name="暖居", plan_json={}
    )
    db.add(plan)
    db.commit()
    scene = DesignScene(plan_version_id=plan.id, current_version=1)
    db.add(scene)
    db.commit()

    result = analyze_manual_edits(db, scene)
    assert result["edited"] is False
    assert "缺少" in result["reason"]

    db.close()
