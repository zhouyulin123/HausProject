"""开放几何离线开发评测；复用生产 DSL、合并、校验与编译实现。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from math import ceil
from time import perf_counter
from typing import Any

from pydantic import TypeAdapter

from app.schemas.open_geometry import OpenGeometryOperation
from app.services.open_geometry_service import OpenGeometryError, prepare_command


_operation_adapter = TypeAdapter(OpenGeometryOperation)


@dataclass(frozen=True)
class OpenGeometryTurnResult:
    case_id: str
    passed: bool
    code: str
    version_before: int
    version_after: int
    planner_calls: int
    repair_feedback_code: str | None
    latency_ms: float
    errors: tuple[str, ...]


def _parts_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    current = state.get("current") or {}
    design = current.get("design") or {}
    return {part["id"]: part for part in design.get("parts", [])}


def _materials_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    current = state.get("current") or {}
    design = current.get("design") or {}
    return {material["id"]: material for material in design.get("materials", [])}


def _resolve_expected_value(state: dict[str, Any], path: str) -> object:
    current: object = (state.get("current") or {}).get("design") or {}
    segments = path.split(".")
    if segments and segments[0] == "parts":
        current = _parts_by_id(state)
        segments = segments[1:]
    for segment in segments:
        if isinstance(current, list):
            current = current[int(segment)]
        elif isinstance(current, dict):
            current = current[segment]
        else:
            raise KeyError(path)
    return current


def run_synthetic_development_eval(
    turns: list[dict[str, object]],
) -> dict[str, object]:
    """执行受控候选，报告工程契约质量，不调用或估算真实 LLM 成本。"""
    state: dict[str, Any] = {"current_version": 0, "current": None, "history": []}
    results: list[OpenGeometryTurnResult] = []
    for turn in turns:
        before = deepcopy(state)
        candidates = list(turn["candidates"])
        planner_calls = 0
        repair_feedback_code: str | None = None

        def planner(_instruction, _current, _recent, feedback):
            nonlocal planner_calls, repair_feedback_code
            planner_calls += 1
            if feedback is not None:
                repair_feedback_code = feedback.get("code")
            candidate = candidates[min(planner_calls - 1, len(candidates) - 1)]
            return _operation_adapter.validate_python(candidate)

        started_at = perf_counter()
        errors: list[str] = []
        code = "exception"
        try:
            prepared = prepare_command(
                instruction=str(turn["instruction"]),
                current_state=state,
                planner=planner,
            )
            code = str(prepared.result["code"])
            candidate_state = prepared.extension
            expected_delta = int(turn.get("expected_version_delta", 1))
            if code != turn["expected_code"]:
                errors.append(f"code={code}, expected={turn['expected_code']}")
            if candidate_state["current_version"] != before["current_version"] + expected_delta:
                errors.append("版本增量不符合预期")
            if turn.get("state_must_remain_unchanged") and candidate_state != before:
                errors.append("不支持请求改变了上一有效版本")
            before_parts = _parts_by_id(before)
            after_parts = _parts_by_id(candidate_state)
            before_materials = _materials_by_id(before)
            after_materials = _materials_by_id(candidate_state)
            for part_id in turn.get("required_part_ids", []):
                if part_id not in after_parts:
                    errors.append(f"缺少必需部件 {part_id}")
            for part_id in turn.get("preserve_part_ids", []):
                if before_parts.get(part_id) != after_parts.get(part_id):
                    errors.append(f"未修改部件 {part_id} 发生变化")
            for material_id in turn.get("preserve_material_ids", []):
                if before_materials.get(material_id) != after_materials.get(material_id):
                    errors.append(f"未修改材质 {material_id} 发生变化")
            for path, expected in dict(turn.get("expected_values", {})).items():
                try:
                    actual = _resolve_expected_value(candidate_state, path)
                except (KeyError, IndexError, ValueError):
                    errors.append(f"期望路径不存在 {path}")
                else:
                    if actual != expected:
                        errors.append(f"{path}={actual!r}, expected={expected!r}")
            expected_calls = int(turn.get("expected_planner_calls", 1))
            if planner_calls != expected_calls:
                errors.append("规划调用次数不符合预期")
            expected_repair = turn.get("expected_repair_code")
            if expected_repair is not None and repair_feedback_code != expected_repair:
                errors.append("结构化修复反馈不符合预期")
            state = candidate_state
        except (OpenGeometryError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        latency_ms = round((perf_counter() - started_at) * 1000, 3)
        results.append(
            OpenGeometryTurnResult(
                case_id=str(turn["id"]),
                passed=not errors,
                code=code,
                version_before=int(before["current_version"]),
                version_after=int(state["current_version"]),
                planner_calls=planner_calls,
                repair_feedback_code=repair_feedback_code,
                latency_ms=latency_ms,
                errors=tuple(errors),
            )
        )
    passed = sum(result.passed for result in results)
    latencies = sorted(result.latency_ms for result in results)
    p95_index = max(0, min(len(latencies) - 1, ceil(len(latencies) * 0.95) - 1))
    return {
        "schema_version": "open-geometry-eval/1.0",
        "dataset_kind": "synthetic_development",
        "claim": "engineering_contract_only",
        "overall_passed": passed == len(results),
        "metrics": {
            "turn_count": len(results),
            "passed_turn_count": passed,
            "turn_pass_rate": passed / len(results) if results else 0.0,
            "planner_call_count": sum(result.planner_calls for result in results),
            "structured_repair_count": sum(
                result.repair_feedback_code is not None for result in results
            ),
            "unsupported_preservation_count": sum(
                result.code == "unsupported_geometry" and result.passed
                for result in results
            ),
            "latency_p95_ms": latencies[p95_index] if latencies else 0.0,
            "llm_cost_cny": None,
            "llm_cost_status": "not_measured_offline",
        },
        "turns": [asdict(result) for result in results],
    }
