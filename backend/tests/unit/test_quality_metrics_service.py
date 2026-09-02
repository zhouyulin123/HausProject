from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import (
    DesignAgentEvent,
    DesignAgentTurn,
    DesignFeedbackEvent,
    DesignPlanVersion,
    DesignRevision,
    DesignTask,
    GenerationRun,
    LayoutRun,
)
from app.services.quality_metrics_service import build_quality_summary


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def test_quality_summary_uses_explicit_denominators_and_no_user_content(db):
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    task = DesignTask(status="completed", progress=100)
    db.add(task)
    db.flush()
    for index, (status, generator, duration_seconds, tokens, cost) in enumerate(
        [
            ("completed", "llm", 1, 100, 0.10),
            ("completed", "template", 2, 200, 0.20),
            ("failed", None, 3, 0, 0.0),
            ("cancelled", None, 4, 0, 0.0),
        ],
        start=1,
    ):
        db.add(
            GenerationRun(
                task_id=task.id,
                attempt=index,
                status=status,
                progress=100,
                generator=generator,
                usage_json={"total_tokens": tokens},
                cost_cny=cost,
                started_at=now - timedelta(seconds=duration_seconds),
                completed_at=now,
                created_at=now - timedelta(days=1),
            )
        )

    completed_turn = DesignAgentTurn(
        task_id=task.id,
        client_turn_id="turn-completed",
        active_mode="catalog_design",
        intent="design",
        status="completed",
        request_json={"message": "敏感用户文本不能出现在指标响应"},
        response_json={},
        created_at=now,
    )
    handoff_turn = DesignAgentTurn(
        task_id=task.id,
        client_turn_id="turn-handoff",
        active_mode="catalog_design",
        intent="design",
        status="needs_human",
        request_json={"message": "另一个敏感输入"},
        response_json={},
        created_at=now,
    )
    db.add_all([completed_turn, handoff_turn])
    db.flush()
    db.add(
        DesignAgentEvent(
            task_id=task.id,
            turn_id=handoff_turn.id,
            sequence=1,
            event_type="validation_failed",
            node="verify_result",
            status="rejected",
            source="deterministic",
            summary="不应进入聚合响应",
            details_json={"codes": ["invalid_sku", "budget_exceeded"]},
            created_at=now,
        )
    )
    db.commit()

    summary = build_quality_summary(db, now=now, window_days=30)

    assert summary["generation"] == {
        "total": 4,
        "completed": 2,
        "failed": 1,
        "cancelled": 1,
        "active": 0,
        "success_rate": pytest.approx(2 / 3),
        "fallback_rate": 0.5,
        "duration_p50_ms": 2500,
        "duration_p95_ms": 3850,
        "total_tokens": 300,
        "total_cost_cny": pytest.approx(0.3),
    }
    assert summary["agent"]["turn_total"] == 2
    assert summary["agent"]["handoff_total"] == 1
    assert summary["agent"]["handoff_rate"] == 0.5
    assert summary["failure_codes"] == {
        "budget_exceeded": 1,
        "invalid_sku": 1,
    }
    assert "敏感" not in str(summary)
    assert "另一个" not in str(summary)


def test_quality_summary_aggregates_layout_hard_constraints(db):
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    task = DesignTask(status="completed", progress=100)
    db.add(task)
    db.flush()
    revision = DesignRevision(
        task_id=task.id,
        version=1,
        requirement_snapshot={},
        generator="llm",
        created_at=now,
    )
    db.add(revision)
    db.flush()
    plan = DesignPlanVersion(
        revision_id=revision.id,
        plan_key="plan-a",
        plan_name="方案 A",
        plan_json={},
        created_at=now,
    )
    db.add(plan)
    db.flush()
    db.add_all(
        [
            LayoutRun(
                plan_version_id=plan.id,
                best_score=96,
                best_valid=True,
                issue_codes=[],
                source="auto_layout",
                created_at=now,
            ),
            LayoutRun(
                plan_version_id=plan.id,
                best_score=60,
                best_valid=False,
                issue_codes=["collision", "out_of_bounds"],
                source="auto_layout",
                created_at=now,
            ),
        ]
    )
    db.commit()

    summary = build_quality_summary(db, now=now, window_days=30)

    assert summary["layout"] == {
        "total": 2,
        "hard_pass_total": 1,
        "hard_pass_rate": 0.5,
        "average_score": 78.0,
        "issue_codes": {"collision": 1, "out_of_bounds": 1},
    }


def test_quality_summary_returns_none_rates_without_evidence(db):
    summary = build_quality_summary(
        db,
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
        window_days=30,
    )

    assert summary["generation"]["success_rate"] is None
    assert summary["generation"]["fallback_rate"] is None
    assert summary["agent"]["handoff_rate"] is None
    assert summary["layout"]["hard_pass_rate"] is None
    assert summary["feedback"] == {
        "total": 0,
        "action_counts": {
            "adopt": 0,
            "remove": 0,
            "replace": 0,
            "move": 0,
            "final_select": 0,
        },
        "modification_total": 0,
        "modification_rate": None,
        "final_select_total": 0,
        "satisfaction_count": 0,
        "satisfaction_mean": None,
        "glb_load_failure_total": 0,
    }


def test_quality_summary_aggregates_anonymous_feedback_with_window_filter(db):
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    task = DesignTask(status="completed", progress=100)
    db.add(task)
    db.flush()
    events = [
        ("adopt", None, now - timedelta(days=1)),
        ("remove", None, now - timedelta(days=2)),
        ("replace", None, now - timedelta(days=3)),
        ("move", None, now - timedelta(days=4)),
        ("final_select", 5, now - timedelta(days=5)),
        ("final_select", 3, now - timedelta(days=6)),
        ("glb_load_failed", None, now - timedelta(days=7)),
        ("replace", 1, now - timedelta(days=31)),
    ]
    for index, (action_type, satisfaction_score, created_at) in enumerate(events):
        db.add(
            DesignFeedbackEvent(
                task_id=task.id,
                client_event_id=f"private-event-{index}",
                action_type=action_type,
                payload_hash=f"private-hash-{index}",
                room_id="private-room-id",
                instance_id="private-instance-id",
                source_sku="PRIVATE-SOURCE-SKU",
                target_sku="PRIVATE-TARGET-SKU",
                satisfaction_score=satisfaction_score,
                created_at=created_at,
            )
        )
    db.commit()

    summary = build_quality_summary(db, now=now, window_days=30)

    assert summary["feedback"] == {
        "total": 6,
        "action_counts": {
            "adopt": 1,
            "remove": 1,
            "replace": 1,
            "move": 1,
            "final_select": 2,
        },
        "modification_total": 3,
        "modification_rate": 0.5,
        "final_select_total": 2,
        "satisfaction_count": 2,
        "satisfaction_mean": 4.0,
        "glb_load_failure_total": 1,
    }
    assert summary["failure_codes"]["glb_load_failed"] == 1
    serialized = str(summary)
    assert "private-event" not in serialized
    assert "private-room" not in serialized
    assert "PRIVATE-SOURCE-SKU" not in serialized
