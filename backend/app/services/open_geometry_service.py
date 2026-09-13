"""开放几何家具：模型规划、严格合并、确定性编译与任务级版本持久化。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.db.models import CustomFurnitureDraftMutation, DesignTask, TaskExecutionEvent
from app.schemas.open_geometry import (
    BoxGeometry,
    CylinderGeometry,
    OpenGeometryCommandResponse,
    OpenGeometryDesign,
    OpenGeometryOperation,
    OpenGeometryPart,
    OpenGeometryStateResponse,
    OpenGeometryVersion,
    SphereGeometry,
    SweepGeometry,
)
from app.core.config import settings
from app.services import (
    aggregate_lock_service,
    llm_service,
    model_call_governance_service,
    task_timeline_service,
)
from app.services.open_geometry_contract import open_geometry_contract, open_geometry_skill_prompt


STATE_KEY = "open_geometry_furniture"
_operation_adapter = TypeAdapter(OpenGeometryOperation)
REPAIRABLE_CANDIDATE_ERRORS = {
    "below_floor",
    "extent_out_of_range",
    "invalid_patch",
    "invalid_model_output",
    "missing_design",
    "replace_not_allowed",
    "unknown_material",
    "unknown_part",
}


class OpenGeometryError(Exception):
    def __init__(self, code: str, message: str, *, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or []


class OpenGeometryVersionConflict(OpenGeometryError):
    def __init__(self, current_version: int):
        super().__init__("version_conflict", "开放几何版本已变化，请刷新后重试")
        self.current_version = current_version


class OpenGeometryIdempotencyConflict(OpenGeometryError):
    def __init__(self):
        super().__init__("idempotency_conflict", "幂等键已用于不同请求")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request_digest(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _state_for_task(task: DesignTask) -> dict[str, Any]:
    raw = deepcopy((task.agent_state_json or {}).get(STATE_KEY) or {})
    raw.setdefault("current_version", 0)
    raw.setdefault("history", [])
    return raw


def _response(task_id: int, state: dict[str, Any], *, reply: str | None = None):
    state = _normalized_state(state)
    payload = {
        "task_id": task_id,
        "current_version": state["current_version"],
        "current": state.get("current"),
        "history": state.get("history", []),
    }
    if reply is None:
        return OpenGeometryStateResponse.model_validate(payload)
    return OpenGeometryCommandResponse.model_validate({**payload, "reply": reply})


def get_state(task: DesignTask) -> OpenGeometryStateResponse:
    return _response(task.id, _state_for_task(task))


def state_response(task_id: int, state: dict[str, Any] | None) -> OpenGeometryStateResponse | None:
    if not isinstance(state, dict):
        return None
    return _response(task_id, _normalized_state(state))


def _resolve_world_transform(
    parts: list[OpenGeometryPart],
) -> dict[str, tuple[list[float], list[float]]]:
    by_id = {part.id: part for part in parts}
    resolved: dict[str, tuple[list[float], list[float]]] = {}

    def resolve(part: OpenGeometryPart) -> tuple[list[float], list[float]]:
        if part.id in resolved:
            return resolved[part.id]
        if part.parent_id is None:
            result = (list(part.position_mm), list(part.rotation_deg))
        else:
            parent_position, parent_rotation = resolve(by_id[part.parent_id])
            local_x, local_y, local_z = part.position_mm
            result = (
                [parent_position[0] + local_x, parent_position[1] + local_y,
                 parent_position[2] + local_z],
                [parent_rotation[index] + part.rotation_deg[index] for index in range(3)],
            )
        resolved[part.id] = result
        return result

    for item in parts:
        resolve(item)
    return resolved


def _part_extent(part: OpenGeometryPart) -> tuple[list[float], list[float]]:
    geometry = part.geometry
    if isinstance(geometry, BoxGeometry):
        half = [value / 2 for value in geometry.size_mm]
        return ([-half[0], -half[1], -half[2]], half)
    if isinstance(geometry, CylinderGeometry):
        radius = max(geometry.radius_mm, geometry.top_radius_mm or geometry.radius_mm)
        return ([-radius, -geometry.height_mm / 2, -radius],
                [radius, geometry.height_mm / 2, radius])
    if isinstance(geometry, SphereGeometry):
        radius = geometry.radius_mm
        extents = [radius * value for value in geometry.scale]
        return ([-value for value in extents], extents)
    if isinstance(geometry, SweepGeometry):
        mins = [min(point[index] for point in geometry.path_mm) - geometry.radius_mm
                for index in range(3)]
        maxs = [max(point[index] for point in geometry.path_mm) + geometry.radius_mm
                for index in range(3)]
        return mins, maxs
    radius = max(point[0] for point in geometry.profile_mm)
    min_y = min(point[1] for point in geometry.profile_mm)
    max_y = max(point[1] for point in geometry.profile_mm)
    return [-radius, min_y, -radius], [radius, max_y, radius]


def compile_open_geometry(design: OpenGeometryDesign) -> dict[str, Any]:
    """把 DSL 编译成前端只读的确定性规则，不执行任何模型源码。"""
    transforms = _resolve_world_transform(design.parts)
    compiled_parts: list[dict[str, Any]] = []
    global_min = [float("inf")] * 3
    global_max = [float("-inf")] * 3
    for part in design.parts:
        position, rotation = transforms[part.id]
        local_min, local_max = _part_extent(part)
        for index in range(3):
            global_min[index] = min(global_min[index], (position[index] + local_min[index]) * design.scale[index])
            global_max[index] = max(global_max[index], (position[index] + local_max[index]) * design.scale[index])
        geometry = part.geometry.model_dump(mode="json")
        compiled_parts.append(
            {
                "部件ID": part.id,
                "部件名称": part.name,
                "几何": geometry.pop("type"),
                "几何参数": geometry,
                "尺寸_mm": [round(local_max[index] - local_min[index], 4) for index in range(3)],
                "位置_mm": [round(value, 4) for value in position],
                "旋转_deg": [round(value, 4) for value in rotation],
                "材质槽": part.material_id,
                "父部件ID": part.parent_id,
            }
        )
    extents = [global_max[index] - global_min[index] for index in range(3)]
    max_extent = open_geometry_contract()["limits"]["max_extent_mm"]
    if any(value <= 0 or value > max_extent for value in extents):
        raise OpenGeometryError("extent_out_of_range", "编译后的家具包围尺寸超出允许范围")
    if global_min[1] < -1:
        raise OpenGeometryError("below_floor", "编译后的家具部件低于地面")
    materials = [
        {
            "槽位ID": material.id,
            "部位": material.name,
            "材质": material.name,
            "表面类型": "metal" if material.metallic >= 0.5 else "custom",
            "base_color": material.base_color,
            "roughness": material.roughness,
            "metallic": material.metallic,
        }
        for material in design.materials
    ]
    rule = {
        "规则版本": design.schema_version,
        "规则状态": "ready",
        "模型ID": f"OPEN-{_request_digest(design.model_dump(mode='json'))[:16].upper()}",
        "家具名称": design.name,
        "家具类型": "开放几何家具",
        "生成器": "open_geometry_v1",
        "坐标系统": {"单位": "mm", "上轴": "Y", "前向": "+Z", "原点": "floor_center"},
        "安装规则": {"基准": "floor", "偏移_mm": 0},
        "包围尺寸_mm": {"宽": round(extents[0], 4), "高": round(extents[1], 4), "深": round(extents[2], 4)},
        "预览规则": {
            "中心_mm": [round((global_min[index] + global_max[index]) / 2, 4) for index in range(3)],
            "半径_mm": round(sum(value * value for value in extents) ** 0.5 / 2, 4),
        },
        "几何规则": {"显式部件数": len(compiled_parts), "结构族": "open_geometry_v1"},
        "全局缩放": design.scale,
        "外观规则": {"表面": {item["槽位ID"]: item["表面类型"] for item in materials}},
        "材质槽": materials,
        "部件": compiled_parts,
        "设计冻结": {"输入来源": "OpenGeometryDesign", "单位": "mm", "说明": "受控 DSL 确定性编译；不包含可执行源码。"},
    }
    return {
        "家具类型": "开放几何家具",
        "家具名称": design.name,
        "尺寸参数": rule["包围尺寸_mm"],
        "材质参数": materials,
        "开放几何DSL": design.model_dump(mode="json"),
        "确定性建模规则": rule,
        "安装参数": {"锚点": "floor"},
    }


def merge_patch(current: OpenGeometryDesign, operation: OpenGeometryOperation) -> OpenGeometryDesign:
    if operation.operation == "create":
        return operation.design
    if operation.operation == "unsupported":
        raise OpenGeometryError("unsupported_geometry", operation.reason)
    patch = operation.patch
    document = current.model_dump(mode="json")
    if patch.name is not None:
        document["name"] = patch.name
    if patch.description is not None:
        document["description"] = patch.description
    if patch.scale is not None:
        document["scale"] = patch.scale
    materials = {item["id"]: item for item in document["materials"]}
    for material_id in patch.remove_material_ids:
        if material_id not in materials:
            raise OpenGeometryError("unknown_material", f"无法删除不存在的材质 {material_id}")
        del materials[material_id]
    for material in patch.upsert_materials:
        materials[material.id] = material.model_dump(mode="json")
    parts = {item["id"]: item for item in document["parts"]}
    for part_id in patch.remove_part_ids:
        if part_id not in parts:
            raise OpenGeometryError("unknown_part", f"无法删除不存在的部件 {part_id}")
        del parts[part_id]
    for part in patch.upsert_parts:
        parts[part.id] = part.model_dump(mode="json")
    document["materials"] = list(materials.values())
    document["parts"] = list(parts.values())
    try:
        return OpenGeometryDesign.model_validate(document)
    except ValidationError as exc:
        raise OpenGeometryError("invalid_patch", "局部修改合并后不满足开放几何约束", details=exc.errors(include_url=False, include_context=False)) from exc


def _plan_operation(
    instruction: str,
    current: OpenGeometryDesign | None,
    recent_versions: list[dict[str, Any]],
    validation_feedback: dict[str, Any] | None = None,
) -> OpenGeometryOperation:
    contract = open_geometry_contract()
    current_json = current.model_dump(mode="json") if current else None
    system = (
        open_geometry_skill_prompt()
        + "\n\n你是家具开放几何参数设计器。只输出 JSON，不输出源码或解释。"
        "几何白名单和 JSON Schema 必须严格遵守。没有当前设计时 operation=create；已有设计时优先 operation=patch。"
        "patch 的 upsert_parts 必须给出完整部件并复用稳定 id；未修改内容不要重复提交。"
        "如果提供 previous_candidate_validation_error，必须修复被拒绝候选中的结构错误，再输出新的完整候选操作。"
        "无法用白名单表达时输出 {\"operation\":\"unsupported\",\"reason\":\"...\"}。"
    )
    user = _canonical({
        "contract": contract,
        "operation_json_schema": _operation_adapter.json_schema(),
        "current_design": current_json,
        "recent_version_context": recent_versions[-6:],
        "previous_candidate_validation_error": validation_feedback,
        "instruction": instruction,
    })
    try:
        raw = llm_service._chat_json(system, user, max_tokens=8000, temperature=0.25)
    except llm_service.LLMUnavailable as exc:
        raise OpenGeometryError("llm_unavailable", "家具几何设计模型暂不可用") from exc
    try:
        operation = _operation_adapter.validate_python(raw)
    except ValidationError as exc:
        raise OpenGeometryError("invalid_model_output", "模型返回的开放几何 JSON 未通过严格校验", details=exc.errors(include_url=False, include_context=False)) from exc
    return operation


Planner = Callable[
    [str, OpenGeometryDesign | None, list[dict[str, Any]], dict[str, Any] | None],
    OpenGeometryOperation,
]


@dataclass(frozen=True)
class OpenGeometryPreparation:
    """纯开放几何规划结果；不触碰数据库、账本或事务。"""

    result: dict[str, Any]
    extension: dict[str, Any]


def _normalized_state(current_state: dict[str, Any] | None) -> dict[str, Any]:
    state = deepcopy(current_state or {})
    current_version = state.get("current_version", 0)
    if (
        not isinstance(current_version, int)
        or isinstance(current_version, bool)
        or current_version < 0
    ):
        raise OpenGeometryError("invalid_state", "开放几何状态版本无效")
    history = state.get("history", [])
    if not isinstance(history, list):
        raise OpenGeometryError("invalid_state", "开放几何历史状态无效")
    current_payload = state.get("current")
    if current_payload is None:
        if current_version != 0 or history:
            raise OpenGeometryError(
                "invalid_state",
                "开放几何版本链无效：空设计必须对应零版本和空历史",
            )
        return {"current_version": 0, "current": None, "history": []}
    if current_version == 0 or not history:
        raise OpenGeometryError(
            "invalid_state",
            "开放几何版本链无效：非空设计必须包含当前版本和历史",
        )
    try:
        current = OpenGeometryVersion.model_validate(current_payload)
        versions = [OpenGeometryVersion.model_validate(item) for item in history]
    except (TypeError, ValidationError) as exc:
        details = (
            exc.errors(include_url=False, include_context=False)
            if isinstance(exc, ValidationError)
            else []
        )
        raise OpenGeometryError(
            "invalid_state",
            "开放几何版本链包含无效版本",
            details=details,
        ) from exc
    if current.version != current_version:
        raise OpenGeometryError(
            "invalid_state",
            "开放几何当前版本与版本号不一致",
        )
    if any(
        right.version != left.version + 1
        for left, right in zip(versions, versions[1:])
    ):
        raise OpenGeometryError(
            "invalid_state",
            "开放几何历史版本必须严格递增且连续",
        )
    if versions[-1].model_dump(mode="json") != current.model_dump(mode="json"):
        raise OpenGeometryError(
            "invalid_state",
            "开放几何历史末项必须与当前版本一致",
        )
    if len(versions) > open_geometry_contract()["limits"]["max_history_versions"]:
        raise OpenGeometryError(
            "invalid_state",
            "开放几何历史版本数量超过上限",
        )
    for version in versions:
        try:
            recompiled = compile_open_geometry(version.design)
        except OpenGeometryError as exc:
            raise OpenGeometryError(
                "invalid_state",
                "开放几何历史版本无法通过当前编译规则",
                details=exc.details,
            ) from exc
        if recompiled != version.model_spec:
            raise OpenGeometryError(
                "invalid_state",
                "开放几何历史模型与 DSL 重新编译结果不一致",
            )
    return {
        "current_version": current_version,
        "current": current.model_dump(mode="json"),
        "history": [item.model_dump(mode="json") for item in versions],
    }


def prepare_command(
    *,
    instruction: str,
    current_state: dict[str, Any] | None,
    planner: Planner | None = None,
    max_attempts: int = 2,
) -> OpenGeometryPreparation:
    """规划、一次修复并编译开放几何，不产生任何持久化副作用。"""
    if max_attempts not in {1, 2}:
        raise ValueError("开放几何规划调用次数只能是 1 或 2")
    selected_planner = planner or _plan_operation
    state = _normalized_state(current_state)
    current_payload = state.get("current")
    current = (
        OpenGeometryDesign.model_validate(current_payload["design"])
        if isinstance(current_payload, dict) and current_payload.get("design")
        else None
    )
    recent_versions = [
        {
            "version": item["version"],
            "instruction": item.get("instruction", ""),
            "part_ids": [part["id"] for part in item["design"]["parts"]],
        }
        for item in state["history"][-6:]
        if isinstance(item, dict)
        and isinstance(item.get("design"), dict)
        and isinstance(item.get("design", {}).get("parts"), list)
    ]
    validation_feedback: dict[str, Any] | None = None
    operation: OpenGeometryOperation | None = None
    for candidate_attempt in range(max_attempts):
        try:
            operation = selected_planner(
                instruction,
                current,
                recent_versions,
                validation_feedback,
            )
            if operation.operation == "unsupported":
                model_id = None
                part_count = len(current.parts) if current is not None else 0
                if isinstance(current_payload, dict):
                    model_id = (
                        (current_payload.get("model_spec") or {})
                        .get("确定性建模规则", {})
                        .get("模型ID")
                    )
                return OpenGeometryPreparation(
                    result={
                        "status": "completed",
                        "code": "unsupported_geometry",
                        "message": f"当前几何需求暂不支持：{operation.reason}",
                        "current_version": state["current_version"],
                        "model_id": model_id,
                        "part_count": part_count,
                    },
                    extension=state,
                )
            if current is None and operation.operation != "create":
                raise OpenGeometryError("missing_design", "首次建模必须创建完整开放几何设计")
            if current is not None and operation.operation == "create":
                raise OpenGeometryError("replace_not_allowed", "已有设计不能由模型整件替换，请生成局部 patch")
            design = operation.design if operation.operation == "create" else merge_patch(current, operation)
            model_spec = compile_open_geometry(design)
            break
        except OpenGeometryError as exc:
            can_repair = (
                candidate_attempt + 1 < max_attempts
                and exc.code in REPAIRABLE_CANDIDATE_ERRORS
            )
            if not can_repair:
                raise
            validation_feedback = {
                "code": exc.code,
                "message": str(exc),
                "errors": exc.details,
                "rejected_candidate": (
                    _operation_adapter.dump_python(operation, mode="json")
                    if operation is not None
                    else None
                ),
            }
    else:
        raise OpenGeometryError("invalid_model_output", "开放几何候选未能完成编译")

    version = OpenGeometryVersion(
        version=state["current_version"] + 1,
        source="llm",
        instruction=instruction,
        design=design,
        model_spec=model_spec,
    )
    extension = {
        **state,
        "current_version": version.version,
        "current": version.model_dump(mode="json"),
        "history": [*state["history"], version.model_dump(mode="json")][
            -open_geometry_contract()["limits"]["max_history_versions"]:
        ],
    }
    return OpenGeometryPreparation(
        result={
            "status": "completed",
            "code": "completed",
            "message": f"已生成开放几何版本 {version.version}。",
            "current_version": version.version,
            "model_id": model_spec["确定性建模规则"]["模型ID"],
            "part_count": len(design.parts),
        },
        extension=extension,
    )


def _find_mutation(db: Session, task_id: int, client_mutation_id: str):
    return (
        db.query(CustomFurnitureDraftMutation)
        .filter(
            CustomFurnitureDraftMutation.task_id == task_id,
            CustomFurnitureDraftMutation.client_mutation_id == client_mutation_id,
        )
        .one_or_none()
    )


def _command_request(base_version: int, instruction: str) -> dict[str, Any]:
    return {"resource": STATE_KEY, "action": "command", "base_version": base_version,
            "instruction": instruction, "digest": _request_digest(instruction)}


def replay_command(
    db: Session,
    *,
    task_id: int,
    client_mutation_id: str,
    base_version: int,
    instruction: str,
) -> OpenGeometryCommandResponse | None:
    previous = _find_mutation(db, task_id, client_mutation_id)
    if previous is None:
        return None
    if previous.request_json != _command_request(base_version, instruction):
        raise OpenGeometryIdempotencyConflict()
    return OpenGeometryCommandResponse.model_validate(previous.response_json)


def _record_model_timeline(
    db: Session,
    *,
    task_id: int,
    client_mutation_id: str,
    status: str,
    capture: llm_service.ModelCallCapture,
) -> None:
    billing_status, cost_cny = task_timeline_service.billing_for_model_call(
        attempted=capture.attempted,
        usage=capture.usage,
        input_price_per_mtok=settings.llm_input_price_per_mtok,
        output_price_per_mtok=settings.llm_output_price_per_mtok,
    )
    mutation_key = _request_digest(client_mutation_id)[:32]
    key_prefix = f"agent:open_geometry:{task_id}:{mutation_key}"
    prior_failures = (
        db.query(TaskExecutionEvent)
        .filter(TaskExecutionEvent.event_key.like(f"{key_prefix}:failed:a%"))
        .count()
    )
    request_attempt = prior_failures + 1
    event_key = (
        f"{key_prefix}:failed:a{request_attempt}"
        if status == "failed"
        else f"{key_prefix}:completed"
    )
    task_timeline_service.append_event(
        db,
        task_id=task_id,
        source_type="agent",
        source_id=task_id,
        attempt=request_attempt if capture.attempted else None,
        event_code=f"agent.open_geometry.{status}",
        billing_status=billing_status,
        cost_cny=cost_cny,
        event_key=event_key,
    )


def apply_command(
    db: Session,
    *,
    task_id: int,
    client_mutation_id: str,
    base_version: int,
    instruction: str,
    planner: Planner | None = None,
) -> OpenGeometryCommandResponse:
    request = _command_request(base_version, instruction)
    previous = _find_mutation(db, task_id, client_mutation_id)
    if previous is not None:
        if previous.request_json != request:
            raise OpenGeometryIdempotencyConflict()
        return OpenGeometryCommandResponse.model_validate(previous.response_json)
    task = aggregate_lock_service.lock_task(db, task_id)
    if task is None:
        raise OpenGeometryError("task_not_found", "设计任务不存在")
    # MySQL 行锁保证相同任务的同一幂等键只触发一次模型调用。
    previous = _find_mutation(db, task_id, client_mutation_id)
    if previous is not None:
        if previous.request_json != request:
            raise OpenGeometryIdempotencyConflict()
        return OpenGeometryCommandResponse.model_validate(previous.response_json)
    state = _state_for_task(task)
    if state["current_version"] != base_version:
        raise OpenGeometryVersionConflict(state["current_version"])
    with (
        model_call_governance_service.govern_task_model_calls(
            db,
            task_id=task_id,
            operation_key=f"open-geometry:{client_mutation_id}",
        ),
        llm_service.capture_model_call() as model_capture,
    ):
        try:
            prepared = prepare_command(
                instruction=instruction,
                current_state=state,
                planner=planner,
            )
            if prepared.result.get("code") == "unsupported_geometry":
                raise OpenGeometryError(
                    "unsupported_geometry",
                    prepared.result.get("message", "当前几何需求暂不支持"),
                )
        except OpenGeometryError:
            _record_model_timeline(
                db, task_id=task_id, client_mutation_id=client_mutation_id,
                status="failed", capture=model_capture,
            )
            db.commit()
            raise

    state = prepared.extension
    version = OpenGeometryVersion.model_validate(state["current"])
    root_state = deepcopy(task.agent_state_json or {})
    root_state[STATE_KEY] = state
    task.agent_state_json = root_state
    task.agent_state_version = int(task.agent_state_version or 0) + 1
    response = _response(task_id, state, reply=f"已生成开放几何版本 {version.version}，3D 预览已更新。")
    db.add(CustomFurnitureDraftMutation(
        task_id=task_id,
        client_mutation_id=client_mutation_id,
        request_json=request,
        response_json=response.model_dump(mode="json"),
    ))
    _record_model_timeline(
        db, task_id=task_id, client_mutation_id=client_mutation_id,
        status="completed", capture=model_capture,
    )
    db.commit()
    return response


def restore_version(
    db: Session,
    *,
    task_id: int,
    client_mutation_id: str,
    base_version: int,
    target_version: int,
) -> OpenGeometryCommandResponse:
    request = {"resource": STATE_KEY, "action": "restore", "base_version": base_version,
               "target_version": target_version}
    previous = _find_mutation(db, task_id, client_mutation_id)
    if previous is not None:
        if previous.request_json != request:
            raise OpenGeometryIdempotencyConflict()
        return OpenGeometryCommandResponse.model_validate(previous.response_json)
    task = aggregate_lock_service.lock_task(db, task_id)
    if task is None:
        raise OpenGeometryError("task_not_found", "设计任务不存在")
    previous = _find_mutation(db, task_id, client_mutation_id)
    if previous is not None:
        if previous.request_json != request:
            raise OpenGeometryIdempotencyConflict()
        return OpenGeometryCommandResponse.model_validate(previous.response_json)
    state = _state_for_task(task)
    if state["current_version"] != base_version:
        raise OpenGeometryVersionConflict(state["current_version"])
    target = next((item for item in state["history"] if item["version"] == target_version), None)
    if target is None:
        raise OpenGeometryError("version_not_found", "目标开放几何版本不存在")
    restored = OpenGeometryVersion(
        version=base_version + 1,
        source="restore",
        instruction=f"恢复版本 {target_version}",
        design=OpenGeometryDesign.model_validate(target["design"]),
        model_spec=target["model_spec"],
    )
    state["current_version"] = restored.version
    state["current"] = restored.model_dump(mode="json")
    state["history"] = [*state["history"], restored.model_dump(mode="json")][
        -open_geometry_contract()["limits"]["max_history_versions"]:
    ]
    root_state = deepcopy(task.agent_state_json or {})
    root_state[STATE_KEY] = state
    task.agent_state_json = root_state
    task.agent_state_version = int(task.agent_state_version or 0) + 1
    response = _response(task_id, state, reply=f"已从版本 {target_version} 恢复为新版本 {restored.version}。")
    db.add(CustomFurnitureDraftMutation(
        task_id=task_id, client_mutation_id=client_mutation_id,
        request_json=request, response_json=response.model_dump(mode="json"),
    ))
    db.commit()
    return response
