"""统一动作规划开发评测，复用线上严格 Schema 并检查引用完整性。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import ceil
from time import perf_counter
from typing import Any, Callable, Literal

from pydantic import ValidationError

from app.schemas.agent_action_plan import (
    AgentActionPlan,
    MoveSceneItemAction,
    NearOpeningPlacement,
    PlaceOpenGeometryAction,
)
from app.services.llm_service import agent_action_planner_prompt_snapshot


ExecutionMode = Literal["deterministic_fixture", "online_llm"]
Planner = Callable[..., AgentActionPlan | dict[str, Any]]


@dataclass(frozen=True)
class ActionPlanCaseResult:
    case_id: str
    passed: bool
    outcome: str | None
    tools: tuple[str, ...]
    planner_calls: int
    valid_output: bool
    reference_integrity: bool
    latency_ms: float
    error_codes: tuple[str, ...]


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{sha256(payload).hexdigest()}"


def _known_references(context: dict[str, Any]) -> tuple[set[str], set[str]]:
    instances = {
        str(item.get("instanceId"))
        for item in context.get("openGeometryItems", [])
        if isinstance(item, dict) and item.get("instanceId")
    }
    scene = context.get("scene") if isinstance(context.get("scene"), dict) else {}
    openings = {
        str(item.get("id"))
        for item in scene.get("openings", [])
        if isinstance(item, dict) and item.get("id")
    }
    return instances, openings


def _validate_references(
    plan: AgentActionPlan,
    context: dict[str, Any],
) -> list[str]:
    instances, openings = _known_references(context)
    errors: list[str] = []
    for step in plan.steps:
        if isinstance(step, MoveSceneItemAction) and step.instance_id not in instances:
            errors.append("unknown_instance_reference")
        placement = (
            step.placement
            if isinstance(step, (MoveSceneItemAction, PlaceOpenGeometryAction))
            else None
        )
        if (
            isinstance(placement, NearOpeningPlacement)
            and placement.opening_id not in openings
        ):
            errors.append("unknown_opening_reference")
    if plan.question is not None and plan.question.candidate_ids:
        if any(item not in instances for item in plan.question.candidate_ids):
            errors.append("unknown_candidate_reference")
    return list(dict.fromkeys(errors))


def _validate_expectations(
    plan: AgentActionPlan,
    expected: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    tools = [step.tool for step in plan.steps]
    if plan.outcome != expected.get("outcome"):
        errors.append("unexpected_outcome")
    if "tools" in expected and tools != expected["tools"]:
        errors.append("unexpected_tools")
    placements = [
        step.placement.kind
        for step in plan.steps
        if isinstance(step, (MoveSceneItemAction, PlaceOpenGeometryAction))
    ]
    if "placement_kinds" in expected and placements != expected["placement_kinds"]:
        errors.append("unexpected_placement")
    move = next(
        (step for step in plan.steps if isinstance(step, MoveSceneItemAction)),
        None,
    )
    if expected.get("instance_id") is not None and (
        move is None or move.instance_id != expected["instance_id"]
    ):
        errors.append("unexpected_instance")
    if expected.get("opening_id") is not None and (
        move is None
        or not isinstance(move.placement, NearOpeningPlacement)
        or move.placement.opening_id != expected["opening_id"]
    ):
        errors.append("unexpected_opening")
    if expected.get("question_field") is not None and (
        plan.question is None or plan.question.field != expected["question_field"]
    ):
        errors.append("unexpected_question")
    if expected.get("reason_code") is not None and (
        plan.reason_code != expected["reason_code"]
    ):
        errors.append("unexpected_reason")
    return errors


def run_synthetic_development_eval(
    cases: list[dict[str, object]],
    *,
    planner: Planner,
    execution_mode: ExecutionMode,
) -> dict[str, object]:
    """逐例运行一次规划；失败仅输出稳定错误码，不外泄上下文或异常。"""
    if execution_mode not in {"deterministic_fixture", "online_llm"}:
        raise ValueError("不支持的动作规划评测执行模式")
    results: list[ActionPlanCaseResult] = []
    for case in cases:
        context = deepcopy(case["context"])
        before = deepcopy(context)
        errors: list[str] = []
        plan: AgentActionPlan | None = None
        started_at = perf_counter()
        try:
            candidate = planner(
                instruction=str(case["instruction"]),
                context=context,
            )
            plan = (
                candidate
                if isinstance(candidate, AgentActionPlan)
                else AgentActionPlan.model_validate(candidate)
            )
        except (ValidationError, TypeError, ValueError):
            errors.append("invalid_output")
        except Exception:
            errors.append("planner_failed")
        if context != before:
            errors.append("context_mutated")

        reference_errors: list[str] = []
        if plan is not None:
            reference_errors = _validate_references(plan, before)
            errors.extend(reference_errors)
            errors.extend(
                _validate_expectations(
                    plan,
                    dict(case.get("expected", {})),
                )
            )
        error_codes = tuple(dict.fromkeys(errors))
        results.append(
            ActionPlanCaseResult(
                case_id=str(case["id"]),
                passed=not error_codes,
                outcome=plan.outcome if plan is not None else None,
                tools=tuple(step.tool for step in plan.steps) if plan else (),
                planner_calls=1,
                valid_output=plan is not None,
                reference_integrity=not reference_errors,
                latency_ms=round((perf_counter() - started_at) * 1000, 3),
                error_codes=error_codes,
            )
        )

    count = len(results)
    passed = sum(result.passed for result in results)
    valid = sum(result.valid_output for result in results)
    references = sum(result.reference_integrity for result in results)
    latencies = sorted(result.latency_ms for result in results)
    p95_index = max(0, min(count - 1, ceil(count * 0.95) - 1)) if count else 0
    prompt = agent_action_planner_prompt_snapshot()
    return {
        "schema_version": "agent-action-plan-eval/1.0",
        "dataset_kind": "synthetic_development",
        "claim": "engineering_contract_only",
        "execution_mode": execution_mode,
        "overall_passed": count > 0 and passed == count,
        "versions": {
            "schema": "agent-action-plan/1.0",
            "prompt_version": prompt["version"],
            "prompt_digest": prompt["digest"],
            "context_policy_version": prompt["context_policy_version"],
            "dataset_digest": _canonical_digest(cases),
        },
        "metrics": {
            "case_count": count,
            "passed_case_count": passed,
            "valid_output_rate": valid / count if count else 0.0,
            "reference_integrity_rate": references / count if count else 0.0,
            "planner_call_count": count,
            "max_planner_calls_observed": 1 if count else 0,
            "latency_p95_ms": latencies[p95_index] if count else 0.0,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "llm_cost_cny": None,
            "llm_cost_status": (
                "not_measured_offline"
                if execution_mode == "deterministic_fixture"
                else "unknown"
            ),
        },
        "cases": [
            {
                **asdict(result),
                "tools": list(result.tools),
                "error_codes": list(result.error_codes),
            }
            for result in results
        ],
    }
