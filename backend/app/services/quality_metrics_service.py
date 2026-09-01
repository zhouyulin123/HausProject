"""运营质量指标聚合，不读取用户原始输入或模型思维过程。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from math import floor
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DesignAgentEvent,
    DesignAgentTurn,
    GenerationRun,
    LayoutRun,
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


def build_quality_summary(
    db: Session,
    *,
    now: datetime | None = None,
    window_days: int = 30,
) -> dict[str, Any]:
    if window_days < 1 or window_days > 365:
        raise ValueError("window_days 必须在 1 到 365 之间")
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

    generation_statuses = Counter(run.status for run in generation_runs)
    completed = generation_statuses["completed"]
    failed = generation_statuses["failed"]
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
        },
        "agent": {
            "turn_total": len(agent_turns),
            "handoff_total": handoff_total,
            "handoff_rate": _rate(handoff_total, len(agent_turns)),
            "statuses": dict(sorted(agent_statuses.items())),
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
        "failure_codes": _failure_codes(validation_events),
    }
