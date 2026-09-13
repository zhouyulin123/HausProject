from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import (
    BlenderRenderJob,
    DesignAgentEvent,
    DesignAgentTurn,
    DesignFeedbackEvent,
    DesignPlanVersion,
    DesignRevision,
    DesignTask,
    EffectRenderJob,
    GenerationRun,
    GenerationRunEvent,
    LayoutRun,
    ModelCallCostAccount,
    ModelCallLedger,
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
    account = ModelCallCostAccount(
        scope_kind="task",
        scope_id=str(task.id),
        task_id=task.id,
        cost_limit_cny=1.0,
        allocated_cost_cny=0.35,
        actual_cost_cny=0.25,
        unknown_cost_call_count=1,
        created_at=now,
    )
    db.add(account)
    db.flush()
    db.add_all(
        [
            ModelCallLedger(
                account_id=account.id,
                task_id=task.id,
                operation_key="requirement:1",
                call_index=1,
                provider_key="primary-llm",
                model="model-v1",
                modality="text",
                status="succeeded",
                estimated_cost_cny=0.3,
                actual_cost_cny=0.25,
                billing_status="metered",
                usage_json={"total_tokens": 150},
                created_at=now,
                completed_at=now,
            ),
            ModelCallLedger(
                account_id=account.id,
                task_id=task.id,
                operation_key="agent:1",
                call_index=1,
                provider_key="primary-llm",
                model="model-v1",
                modality="text",
                status="failed",
                estimated_cost_cny=0.1,
                billing_status="unknown",
                usage_json={},
                failure_code="timeout",
                created_at=now,
                completed_at=now,
            ),
        ]
    )
    db.add_all(
        [
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
            ),
            GenerationRunEvent(
                run_id=1,
                node="parse_requirements",
                status="completed",
                progress=30,
                source="llm",
                duration_ms=120,
                created_at=now,
            ),
            GenerationRunEvent(
                run_id=2,
                node="parse_requirements",
                status="completed",
                progress=30,
                source="llm",
                duration_ms=360,
                created_at=now,
            ),
        ]
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
        "node_latency": {
            "parse_requirements": {
                "samples": 2,
                "p50_ms": 240,
                "p95_ms": 348,
            }
        },
    }
    assert summary["agent"]["turn_total"] == 2
    assert summary["agent"]["handoff_total"] == 1
    assert summary["agent"]["handoff_rate"] == 0.5
    assert summary["model_calls"] == {
        "total": 2,
        "succeeded": 1,
        "failed": 1,
        "blocked": 0,
        "total_tokens": 150,
        "known_actual_cost_cny": pytest.approx(0.25),
        "unknown_cost_call_count": 1,
        "provider_failures": {"primary-llm:timeout": 1},
    }
    assert summary["failure_codes"] == {
        "budget_exceeded": 1,
        "generation_status_failed": 1,
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
    assert summary["generation"]["node_latency"] == {}
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
    assert summary["effect_render"] == {
        "total": 0,
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "dead_letter": 0,
        "cancelled": 0,
        "success_rate": None,
        "queue_wait_p50_ms": None,
        "queue_wait_p95_ms": None,
        "execution_p50_ms": None,
        "execution_p95_ms": None,
    }
    assert summary["blender_render"] == summary["effect_render"]


def test_quality_summary_aggregates_render_queue_health(db):
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

    common_effect = {
        "task_id": task.id,
        "plan_version_id": plan.id,
        "prompt_snapshot": "不应进入聚合响应",
        "prompt_digest": "sha256:prompt",
        "request_digest": "sha256:request",
        "execution_deadline_at": now + timedelta(minutes=10),
    }
    db.add_all(
        [
            EffectRenderJob(
                **common_effect,
                idempotency_key="effect-completed",
                status="completed",
                created_at=now - timedelta(seconds=10),
                started_at=now - timedelta(seconds=8),
                completed_at=now,
            ),
            EffectRenderJob(
                **common_effect,
                idempotency_key="effect-dead",
                status="dead_letter",
                created_at=now - timedelta(seconds=20),
                started_at=now - timedelta(seconds=16),
                completed_at=now - timedelta(seconds=10),
            ),
            EffectRenderJob(
                **common_effect,
                idempotency_key="effect-queued",
                status="queued",
                created_at=now,
            ),
        ]
    )
    db.add_all(
        [
            BlenderRenderJob(
                scene_id=1,
                scene_version_id=1,
                scene_version=1,
                profile="preview",
                status="completed",
                execution_deadline_at=now + timedelta(minutes=10),
                created_at=now - timedelta(seconds=9),
                started_at=now - timedelta(seconds=6),
                completed_at=now,
            ),
            BlenderRenderJob(
                scene_id=2,
                scene_version_id=2,
                scene_version=1,
                profile="preview",
                status="cancelled",
                execution_deadline_at=now + timedelta(minutes=10),
                created_at=now,
            ),
        ]
    )
    db.commit()

    summary = build_quality_summary(db, now=now, window_days=30)

    assert summary["effect_render"] == {
        "total": 3,
        "queued": 1,
        "running": 0,
        "completed": 1,
        "failed": 0,
        "dead_letter": 1,
        "cancelled": 0,
        "success_rate": 0.5,
        "queue_wait_p50_ms": 3000,
        "queue_wait_p95_ms": 3900,
        "execution_p50_ms": 7000,
        "execution_p95_ms": 7900,
    }
    assert summary["blender_render"] == {
        "total": 2,
        "queued": 0,
        "running": 0,
        "completed": 1,
        "failed": 0,
        "dead_letter": 0,
        "cancelled": 1,
        "success_rate": 1.0,
        "queue_wait_p50_ms": 3000,
        "queue_wait_p95_ms": 3000,
        "execution_p50_ms": 6000,
        "execution_p95_ms": 6000,
    }
    assert "不应进入聚合响应" not in str(summary)


def test_quality_summary_counts_every_failure_terminal_and_node_code(db):
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    task = DesignTask(status="failed", progress=100)
    db.add(task)
    db.flush()
    runs = []
    for index, status in enumerate(
        (
            "completed",
            "failed",
            "dead_letter",
            "provider_unavailable",
            "cost_limit_exceeded",
            "cancelled",
        ),
        start=1,
    ):
        run = GenerationRun(
            task_id=task.id,
            attempt=index,
            status=status,
            progress=100,
            created_at=now,
            completed_at=now,
        )
        db.add(run)
        runs.append(run)
    db.flush()
    db.add_all(
        [
            GenerationRunEvent(
                run_id=runs[3].id,
                node="provider_circuit",
                status="failed",
                progress=100,
                source="deterministic",
                detail_json={
                    "code": "provider_timeout",
                    "message": "不应进入指标响应的供应商错误原文",
                },
                created_at=now,
            ),
            GenerationRunEvent(
                run_id=runs[4].id,
                node="cost_guard",
                status="failed",
                progress=100,
                source="deterministic",
                detail_json={"reason_code": "task_cost_limit_exceeded"},
                created_at=now,
            ),
        ]
    )
    db.commit()

    summary = build_quality_summary(db, now=now, window_days=30)

    assert summary["generation"]["completed"] == 1
    assert summary["generation"]["failed"] == 4
    assert summary["generation"]["cancelled"] == 1
    assert summary["generation"]["success_rate"] == pytest.approx(0.2)
    assert summary["failure_codes"] == {
        "generation_code_provider_timeout": 1,
        "generation_code_task_cost_limit_exceeded": 1,
        "generation_node_cost_guard": 1,
        "generation_node_provider_circuit": 1,
        "generation_status_cost_limit_exceeded": 1,
        "generation_status_dead_letter": 1,
        "generation_status_failed": 1,
        "generation_status_provider_unavailable": 1,
    }
    assert "供应商错误原文" not in str(summary)


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


def test_quality_summary_groups_generation_metrics_by_exact_version_cohort(db):
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    task = DesignTask(status="completed", progress=100)
    db.add(task)
    db.flush()

    def add_run(
        *,
        attempt: int,
        status: str,
        versions: tuple[str | None, str | None, str | None, str | None],
        generator: str | None = None,
        duration_seconds: int | None = None,
        total_tokens: object = 0,
        cost_cny: float | None = 0,
    ) -> None:
        model, prompt_digest, rules_digest, data_digest = versions
        db.add(
            GenerationRun(
                task_id=task.id,
                attempt=attempt,
                status=status,
                progress=100,
                generator=generator,
                model=model,
                prompt_digest=prompt_digest,
                rules_digest=rules_digest,
                data_digest=data_digest,
                prompt_snapshot=f"PRIVATE-PROMPT-{attempt}",
                input_snapshot={"private": f"PRIVATE-INPUT-{attempt}"},
                usage_json={"total_tokens": total_tokens},
                cost_cny=cost_cny,
                started_at=(
                    now - timedelta(seconds=duration_seconds)
                    if duration_seconds is not None
                    else None
                ),
                completed_at=now if duration_seconds is not None else None,
                created_at=now,
            )
        )

    complete = (
        "model-a",
        "sha256:prompt-a",
        "sha256:rules-a",
        "sha256:data-a",
    )
    legacy = (None, None, None, None)
    partial = ("model-z", None, "sha256:rules-z", None)
    samples = [
        (1, "completed", complete, "llm", 1, 100, 0.10),
        (2, "completed", complete, "template", 2, 200, None),
        (3, "dead_letter", complete, None, 4, 30, 0.20),
        (4, "provider_unavailable", complete, "template", 3, 20, -4.0),
        (5, "queued", complete, None, None, 10, 0.0),
        (6, "cancelled", complete, None, None, 5, None),
        (7, "failed", legacy, None, 5, -2, None),
        (8, "completed", legacy, "template", 1, 40, 0.40),
        (9, "running", partial, None, None, 50, 0.05),
        (10, "cancelled", partial, None, None, 0, 0.06),
    ]
    for (
        attempt,
        status,
        versions,
        generator,
        duration_seconds,
        total_tokens,
        cost_cny,
    ) in samples:
        add_run(
            attempt=attempt,
            status=status,
            versions=versions,
            generator=generator,
            duration_seconds=duration_seconds,
            total_tokens=total_tokens,
            cost_cny=cost_cny,
        )
    db.commit()

    summary = build_quality_summary(
        db,
        now=now,
        window_days=30,
        version_cohort_limit=3,
    )

    cohorts = summary["version_cohorts"]
    assert cohorts["total_cohorts"] == 3
    assert cohorts["returned_cohorts"] == 3
    assert cohorts["truncated"] is False
    assert cohorts["items"] == [
        {
            "model": "model-a",
            "prompt_digest": "sha256:prompt-a",
            "rules_digest": "sha256:rules-a",
            "data_digest": "sha256:data-a",
            "version_complete": True,
            "missing_dimensions": [],
            "total": 6,
            "completed": 2,
            "failed": 2,
            "cancelled": 1,
            "active": 1,
            "success_rate": pytest.approx(0.5),
            "fallback_rate": pytest.approx(0.5),
            "duration_p50_ms": 2500,
            "duration_p95_ms": 3850,
            "total_tokens": 365,
            "known_cost_cny": pytest.approx(0.3),
            "unknown_cost_run_count": 3,
        },
        {
            "model": None,
            "prompt_digest": None,
            "rules_digest": None,
            "data_digest": None,
            "version_complete": False,
            "missing_dimensions": [
                "model",
                "prompt_digest",
                "rules_digest",
                "data_digest",
            ],
            "total": 2,
            "completed": 1,
            "failed": 1,
            "cancelled": 0,
            "active": 0,
            "success_rate": pytest.approx(0.5),
            "fallback_rate": pytest.approx(1.0),
            "duration_p50_ms": 3000,
            "duration_p95_ms": 4800,
            "total_tokens": 40,
            "known_cost_cny": pytest.approx(0.4),
            "unknown_cost_run_count": 1,
        },
        {
            "model": "model-z",
            "prompt_digest": None,
            "rules_digest": "sha256:rules-z",
            "data_digest": None,
            "version_complete": False,
            "missing_dimensions": ["prompt_digest", "data_digest"],
            "total": 2,
            "completed": 0,
            "failed": 0,
            "cancelled": 1,
            "active": 1,
            "success_rate": None,
            "fallback_rate": None,
            "duration_p50_ms": None,
            "duration_p95_ms": None,
            "total_tokens": 50,
            "known_cost_cny": pytest.approx(0.11),
            "unknown_cost_run_count": 0,
        },
    ]
    serialized = str(cohorts)
    assert "PRIVATE-PROMPT" not in serialized
    assert "PRIVATE-INPUT" not in serialized

    limited = build_quality_summary(
        db,
        now=now,
        window_days=30,
        version_cohort_limit=2,
    )["version_cohorts"]
    assert limited["total_cohorts"] == 3
    assert limited["returned_cohorts"] == 2
    assert limited["truncated"] is True
    assert [item["model"] for item in limited["items"]] == ["model-a", None]


@pytest.mark.parametrize("limit", [0, 101])
def test_quality_summary_rejects_invalid_version_cohort_limit(db, limit):
    with pytest.raises(ValueError, match="version_cohort_limit"):
        build_quality_summary(
            db,
            now=datetime(2026, 9, 1, tzinfo=timezone.utc),
            version_cohort_limit=limit,
        )


def test_quality_summary_default_limit_keeps_null_and_empty_version_groups_exact(db):
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    task = DesignTask(status="completed", progress=100)
    db.add(task)
    db.flush()
    models = [None, "", *(f"model-{index:02d}" for index in range(2, 21))]
    db.add_all(
        [
            GenerationRun(
                task_id=task.id,
                attempt=index,
                status="queued",
                progress=0,
                model=model,
                created_at=now,
            )
            for index, model in enumerate(models, start=1)
        ]
    )
    db.commit()

    cohorts = build_quality_summary(db, now=now)["version_cohorts"]

    assert cohorts["total_cohorts"] == 21
    assert cohorts["returned_cohorts"] == 20
    assert cohorts["truncated"] is True
    assert [item["model"] for item in cohorts["items"][:2]] == [None, ""]
    assert cohorts["items"][0]["missing_dimensions"] == [
        "model",
        "prompt_digest",
        "rules_digest",
        "data_digest",
    ]
    assert cohorts["items"][1]["missing_dimensions"] == [
        "model",
        "prompt_digest",
        "rules_digest",
        "data_digest",
    ]
