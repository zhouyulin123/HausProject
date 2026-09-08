from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import DesignTask
from app.services import task_timeline_service


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_timeline_is_append_only_idempotent_and_preserves_unknown_cost():
    engine, factory = _database()
    try:
        with factory() as db:
            task = DesignTask(status="processing", progress=50)
            db.add(task)
            db.flush()
            first = task_timeline_service.append_event(
                db,
                task_id=task.id,
                source_type="generation",
                source_id=11,
                attempt=1,
                event_code="generation.completed",
                billing_status="metered",
                cost_cny=1.25,
                event_key="generation:11:a1:completed",
                occurred_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
            )
            same = task_timeline_service.append_event(
                db,
                task_id=task.id,
                source_type="generation",
                source_id=11,
                attempt=1,
                event_code="generation.completed",
                billing_status="metered",
                cost_cny=1.25,
                event_key="generation:11:a1:completed",
                occurred_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
            )
            task_timeline_service.append_event(
                db,
                task_id=task.id,
                source_type="effect",
                source_id=21,
                attempt=1,
                event_code="effect.completed",
                billing_status="unknown",
                cost_cny=None,
                event_key="effect:21:a1:completed",
            )
            db.commit()

            events, next_cursor = task_timeline_service.list_events(
                db, task_id=task.id, after_id=None, limit=10
            )
            summary = task_timeline_service.cost_summary(db, task_id=task.id)

            assert same.id == first.id
            assert [event.event_code for event in events] == [
                "generation.completed",
                "effect.completed",
            ]
            assert next_cursor is None
            assert summary.known_cost_cny == 1.25
            assert summary.has_unknown_cost is True
            assert summary.unknown_cost_event_count == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"event_code": "generation.completed", "billing_status": "metered", "cost_cny": None},
        {"event_code": "effect.completed", "billing_status": "unknown", "cost_cny": 0},
        {"event_code": "generation.raw_prompt", "billing_status": "not_billable", "cost_cny": None},
    ],
)
def test_timeline_rejects_ambiguous_billing_and_unstable_event_codes(kwargs):
    engine, factory = _database()
    try:
        with factory() as db:
            task = DesignTask(status="processing", progress=50)
            db.add(task)
            db.flush()
            with pytest.raises(ValueError):
                task_timeline_service.append_event(
                    db,
                    task_id=task.id,
                    source_type="generation",
                    source_id=1,
                    attempt=1,
                    event_key="invalid-event",
                    **kwargs,
                )
    finally:
        engine.dispose()


def test_timeline_cursor_is_monotonic_and_cost_is_null_when_only_unknown():
    engine, factory = _database()
    try:
        with factory() as db:
            task = DesignTask(status="processing", progress=50)
            db.add(task)
            db.flush()
            for source_id in range(1, 4):
                task_timeline_service.append_event(
                    db,
                    task_id=task.id,
                    source_type="blender",
                    source_id=source_id,
                    attempt=1,
                    event_code="blender.completed",
                    billing_status="unknown",
                    cost_cny=None,
                    event_key=f"blender:{source_id}:a1:completed",
                )
            db.commit()

            first_page, cursor = task_timeline_service.list_events(
                db, task_id=task.id, after_id=None, limit=2
            )
            second_page, final_cursor = task_timeline_service.list_events(
                db, task_id=task.id, after_id=cursor, limit=2
            )
            summary = task_timeline_service.cost_summary(db, task_id=task.id)

            assert len(first_page) == 2
            assert [event.id for event in second_page] == [3]
            assert final_cursor is None
            assert summary.known_cost_cny is None
            assert summary.has_unknown_cost is True
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("source_type", "state", "attempt", "expected_code", "expected_billing"),
    [
        ("agent", "completed", 1, "agent.turn.completed", "unknown"),
        (
            "effect",
            "provider_unavailable",
            1,
            "effect.provider_unavailable",
            "unknown",
        ),
    ],
)
def test_timeline_preserves_model_attempt_and_provider_terminal_semantics(
    source_type,
    state,
    attempt,
    expected_code,
    expected_billing,
):
    engine, factory = _database()
    try:
        with factory() as db:
            task = DesignTask(status="processing", progress=50)
            db.add(task)
            db.flush()

            event = task_timeline_service.record_lifecycle_event(
                db,
                task_id=task.id,
                source_type=source_type,
                source_id=9,
                state=state,
                attempt=attempt,
            )

            assert event.event_code == expected_code
            assert event.billing_status == expected_billing
            assert event.cost_cny is None
    finally:
        engine.dispose()
