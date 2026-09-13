"""运营质量指标聚合，不读取用户原始输入或模型思维过程。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from math import floor
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    BlenderRenderJob,
    DesignAgentEvent,
    DesignAgentTurn,
    DesignFeedbackEvent,
    EffectRenderJob,
    GenerationRun,
    GenerationRunEvent,
    LayoutRun,
    ModelCallLedger,
)


_FEEDBACK_ACTIONS = ("adopt", "remove", "replace", "move", "final_select")
_ASSET_FAILURE_ACTION = "glb_load_failed"
_MODIFICATION_ACTIONS = ("remove", "replace", "move")
_GENERATION_FAILURE_STATUSES = (
    "failed",
    "dead_letter",
    "provider_unavailable",
    "cost_limit_exceeded",
)
_FAILED_EVENT_STATUSES = {"failed", "error", "rejected"}
_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_:-]{0,99}$")
_VERSION_DIMENSIONS = (
    "model",
    "prompt_digest",
    "rules_digest",
    "data_digest",
)


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _duration_ms(run: GenerationRun) -> int | None:
    if run.started_at is None or run.completed_at is None:
        return None
    return max(0, round((run.completed_at - run.started_at).total_seconds() * 1000))


def _total_tokens(run: GenerationRun) -> int:
    usage = run.usage_json
    if not isinstance(usage, dict):
        return 0
    value = usage.get("total_tokens")
    return value if isinstance(value, int) and value >= 0 else 0


def _is_missing_version(value: str | None) -> bool:
    return value is None or not value.strip()


def _version_cohort_metrics(
    runs: list[GenerationRun],
    *,
    limit: int,
) -> dict[str, Any]:
    grouped: dict[tuple[str | None, ...], list[GenerationRun]] = {}
    for run in runs:
        key = tuple(getattr(run, dimension) for dimension in _VERSION_DIMENSIONS)
        grouped.setdefault(key, []).append(run)

    items: list[dict[str, Any]] = []
    for key, cohort_runs in grouped.items():
        statuses = Counter(run.status for run in cohort_runs)
        completed = statuses["completed"]
        failed = sum(statuses[status] for status in _GENERATION_FAILURE_STATUSES)
        completed_runs = [run for run in cohort_runs if run.status == "completed"]
        durations = [
            duration
            for run in cohort_runs
            if (duration := _duration_ms(run)) is not None
        ]
        missing_dimensions = [
            dimension
            for dimension, value in zip(_VERSION_DIMENSIONS, key, strict=True)
            if _is_missing_version(value)
        ]
        items.append(
            {
                **dict(zip(_VERSION_DIMENSIONS, key, strict=True)),
                "version_complete": not missing_dimensions,
                "missing_dimensions": missing_dimensions,
                "total": len(cohort_runs),
                "completed": completed,
                "failed": failed,
                "cancelled": statuses["cancelled"],
                "active": statuses["queued"] + statuses["running"],
                "success_rate": _rate(completed, completed + failed),
                "fallback_rate": _rate(
                    sum(1 for run in completed_runs if run.generator == "template"),
                    len(completed_runs),
                ),
                "duration_p50_ms": _percentile(durations, 0.5),
                "duration_p95_ms": _percentile(durations, 0.95),
                "total_tokens": sum(_total_tokens(run) for run in cohort_runs),
                "known_cost_cny": sum(
                    float(run.cost_cny)
                    for run in cohort_runs
                    if run.cost_cny is not None and run.cost_cny >= 0
                ),
                "unknown_cost_run_count": sum(
                    1
                    for run in cohort_runs
                    if run.cost_cny is None or run.cost_cny < 0
                ),
            }
        )

    items.sort(
        key=lambda item: (
            -item["total"],
            *(item[dimension] or "" for dimension in _VERSION_DIMENSIONS),
            *(item[dimension] is not None for dimension in _VERSION_DIMENSIONS),
        )
    )
    selected = items[:limit]
    return {
        "total_cohorts": len(items),
        "returned_cohorts": len(selected),
        "truncated": len(selected) < len(items),
        "items": selected,
    }


def _node_latency(events: list[GenerationRunEvent]) -> dict[str, dict[str, int]]:
    durations: dict[str, list[int]] = {}
    for event in events:
        node = event.node.strip() if isinstance(event.node, str) else ""
        if (
            not _CODE_PATTERN.fullmatch(node)
            or not isinstance(event.duration_ms, int)
            or event.duration_ms < 0
        ):
            continue
        durations.setdefault(node, []).append(event.duration_ms)
    return {
        node: {
            "samples": len(values),
            "p50_ms": _percentile(values, 0.5),
            "p95_ms": _percentile(values, 0.95),
        }
        for node, values in sorted(durations.items())
    }


def _elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, round((end - start).total_seconds() * 1000))


def _render_queue_metrics(jobs: list[Any]) -> dict[str, Any]:
    statuses = Counter(job.status for job in jobs)
    queue_waits = [
        value
        for job in jobs
        if (value := _elapsed_ms(job.created_at, job.started_at)) is not None
    ]
    execution_durations = [
        value
        for job in jobs
        if (value := _elapsed_ms(job.started_at, job.completed_at)) is not None
    ]
    terminal_total = (
        statuses["completed"] + statuses["failed"] + statuses["dead_letter"]
    )
    return {
        "total": len(jobs),
        "queued": statuses["queued"],
        "running": statuses["running"],
        "completed": statuses["completed"],
        "failed": statuses["failed"],
        "dead_letter": statuses["dead_letter"],
        "cancelled": statuses["cancelled"],
        "success_rate": _rate(statuses["completed"], terminal_total),
        "queue_wait_p50_ms": _percentile(queue_waits, 0.5),
        "queue_wait_p95_ms": _percentile(queue_waits, 0.95),
        "execution_p50_ms": _percentile(execution_durations, 0.5),
        "execution_p95_ms": _percentile(execution_durations, 0.95),
    }


def _failure_codes(events: list[DesignAgentEvent]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for event in events:
        details = event.details_json
        if not isinstance(details, dict):
            continue
        codes = details.get("codes")
        if not isinstance(codes, list):
            continue
        counter.update(
            code
            for code in codes
            if isinstance(code, str) and code.strip()
        )
    return dict(sorted(counter.items()))


def _generation_failure_codes(
    runs: list[GenerationRun],
    events: list[GenerationRunEvent],
) -> Counter[str]:
    counter: Counter[str] = Counter(
        f"generation_status_{run.status}"
        for run in runs
        if run.status in _GENERATION_FAILURE_STATUSES
    )
    for event in events:
        if event.status not in _FAILED_EVENT_STATUSES:
            continue
        node = event.node.strip() if isinstance(event.node, str) else ""
        if _CODE_PATTERN.fullmatch(node):
            counter[f"generation_node_{node}"] += 1
        details = event.detail_json
        if not isinstance(details, dict):
            continue
        values: list[object] = []
        for key in ("code", "error_code", "reason_code"):
            values.append(details.get(key))
        codes = details.get("codes")
        if isinstance(codes, list):
            values.extend(codes)
        for value in values:
            if isinstance(value, str) and _CODE_PATTERN.fullmatch(value.strip()):
                counter[f"generation_code_{value.strip()}"] += 1
    return counter


def build_quality_summary(
    db: Session,
    *,
    now: datetime | None = None,
    window_days: int = 30,
    version_cohort_limit: int = 20,
) -> dict[str, Any]:
    if window_days < 1 or window_days > 365:
        raise ValueError("window_days 必须在 1 到 365 之间")
    if version_cohort_limit < 1 or version_cohort_limit > 100:
        raise ValueError("version_cohort_limit 必须在 1 到 100 之间")
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=window_days)

    generation_runs = db.scalars(
        select(GenerationRun).where(GenerationRun.created_at >= cutoff)
    ).all()
    agent_turns = db.scalars(
        select(DesignAgentTurn).where(DesignAgentTurn.created_at >= cutoff)
    ).all()
    layout_runs = db.scalars(
        select(LayoutRun).where(LayoutRun.created_at >= cutoff)
    ).all()
    validation_events = db.scalars(
        select(DesignAgentEvent).where(
            DesignAgentEvent.created_at >= cutoff,
            DesignAgentEvent.event_type == "validation_failed",
        )
    ).all()
    generation_events = db.scalars(
        select(GenerationRunEvent).where(GenerationRunEvent.created_at >= cutoff)
    ).all()
    effect_render_jobs = db.scalars(
        select(EffectRenderJob).where(EffectRenderJob.created_at >= cutoff)
    ).all()
    blender_render_jobs = db.scalars(
        select(BlenderRenderJob).where(BlenderRenderJob.created_at >= cutoff)
    ).all()
    model_calls = db.scalars(
        select(ModelCallLedger).where(ModelCallLedger.created_at >= cutoff)
    ).all()
    feedback_rows = db.execute(
        select(
            DesignFeedbackEvent.action_type,
            func.count(DesignFeedbackEvent.id),
            func.count(DesignFeedbackEvent.satisfaction_score),
            func.sum(DesignFeedbackEvent.satisfaction_score),
        )
        .where(
            DesignFeedbackEvent.created_at >= cutoff,
            DesignFeedbackEvent.action_type.in_(
                (*_FEEDBACK_ACTIONS, _ASSET_FAILURE_ACTION)
            ),
        )
        .group_by(DesignFeedbackEvent.action_type)
    ).all()

    generation_statuses = Counter(run.status for run in generation_runs)
    completed = generation_statuses["completed"]
    failed = sum(
        generation_statuses[status] for status in _GENERATION_FAILURE_STATUSES
    )
    cancelled = generation_statuses["cancelled"]
    active = generation_statuses["queued"] + generation_statuses["running"]
    completed_runs = [run for run in generation_runs if run.status == "completed"]
    durations = [
        duration
        for run in generation_runs
        if (duration := _duration_ms(run)) is not None
    ]

    agent_statuses = Counter(turn.status for turn in agent_turns)
    handoff_total = agent_statuses["needs_human"]
    layout_issue_codes: Counter[str] = Counter()
    for run in layout_runs:
        if isinstance(run.issue_codes, list):
            layout_issue_codes.update(
                code
                for code in run.issue_codes
                if isinstance(code, str) and code.strip()
            )
    layout_pass_total = sum(1 for run in layout_runs if run.best_valid)
    feedback_action_counts = dict.fromkeys(_FEEDBACK_ACTIONS, 0)
    satisfaction_count = 0
    satisfaction_total = 0
    glb_load_failure_total = 0
    for action_type, event_count, score_count, score_total in feedback_rows:
        if action_type == _ASSET_FAILURE_ACTION:
            glb_load_failure_total = int(event_count)
            continue
        feedback_action_counts[action_type] = int(event_count)
        satisfaction_count += int(score_count)
        satisfaction_total += int(score_total or 0)
    feedback_total = sum(feedback_action_counts.values())
    modification_total = sum(
        feedback_action_counts[action] for action in _MODIFICATION_ACTIONS
    )

    failure_codes = Counter(_failure_codes(validation_events))
    failure_codes.update(
        _generation_failure_codes(generation_runs, generation_events)
    )
    if glb_load_failure_total:
        failure_codes[_ASSET_FAILURE_ACTION] += glb_load_failure_total
    model_call_statuses = Counter(call.status for call in model_calls)
    provider_failures = Counter(
        f"{call.provider_key}:{call.failure_code}"
        for call in model_calls
        if call.failure_code
        and call.status == "failed"
        and _CODE_PATTERN.fullmatch(call.failure_code)
    )

    return {
        "generated_at": current.isoformat(),
        "window_days": window_days,
        "generation": {
            "total": len(generation_runs),
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "active": active,
            "success_rate": _rate(completed, completed + failed),
            "fallback_rate": _rate(
                sum(1 for run in completed_runs if run.generator == "template"),
                len(completed_runs),
            ),
            "duration_p50_ms": _percentile(durations, 0.5),
            "duration_p95_ms": _percentile(durations, 0.95),
            "total_tokens": sum(_total_tokens(run) for run in generation_runs),
            "total_cost_cny": sum(
                float(run.cost_cny)
                for run in generation_runs
                if run.cost_cny is not None and run.cost_cny >= 0
            ),
            "node_latency": _node_latency(generation_events),
        },
        "version_cohorts": _version_cohort_metrics(
            generation_runs,
            limit=version_cohort_limit,
        ),
        "agent": {
            "turn_total": len(agent_turns),
            "handoff_total": handoff_total,
            "handoff_rate": _rate(handoff_total, len(agent_turns)),
            "statuses": dict(sorted(agent_statuses.items())),
        },
        "model_calls": {
            "total": len(model_calls),
            "succeeded": model_call_statuses["succeeded"],
            "failed": model_call_statuses["failed"],
            "blocked": model_call_statuses["blocked"],
            "total_tokens": sum(
                int((call.usage_json or {}).get("total_tokens", 0))
                for call in model_calls
                if isinstance((call.usage_json or {}).get("total_tokens", 0), int)
            ),
            "known_actual_cost_cny": sum(
                float(call.actual_cost_cny)
                for call in model_calls
                if call.actual_cost_cny is not None
                and call.actual_cost_cny >= 0
            ),
            "unknown_cost_call_count": sum(
                1 for call in model_calls if call.billing_status == "unknown"
            ),
            "provider_failures": dict(sorted(provider_failures.items())),
        },
        "layout": {
            "total": len(layout_runs),
            "hard_pass_total": layout_pass_total,
            "hard_pass_rate": _rate(layout_pass_total, len(layout_runs)),
            "average_score": (
                round(sum(run.best_score for run in layout_runs) / len(layout_runs), 2)
                if layout_runs
                else None
            ),
            "issue_codes": dict(sorted(layout_issue_codes.items())),
        },
        "feedback": {
            "total": feedback_total,
            "action_counts": feedback_action_counts,
            "modification_total": modification_total,
            "modification_rate": _rate(modification_total, feedback_total),
            "final_select_total": feedback_action_counts["final_select"],
            "satisfaction_count": satisfaction_count,
            "satisfaction_mean": (
                round(satisfaction_total / satisfaction_count, 2)
                if satisfaction_count
                else None
            ),
            "glb_load_failure_total": glb_load_failure_total,
        },
        "effect_render": _render_queue_metrics(effect_render_jobs),
        "blender_render": _render_queue_metrics(blender_render_jobs),
        "failure_codes": dict(sorted(failure_codes.items())),
    }
