import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import DesignTask, TaskExecutionEvent
from app.schemas.open_geometry import (
    MIN_GEOMETRY_LENGTH_MM,
    OpenGeometryDesign,
    OpenGeometryOperation,
)
from app.services.open_geometry_service import (
    OpenGeometryError,
    OpenGeometryIdempotencyConflict,
    apply_command,
    compile_open_geometry,
    get_state,
    prepare_command,
    restore_version,
    state_response,
)


OPERATION = TypeAdapter(OpenGeometryOperation)


def chair_design():
    return {
        "schema_version": "furniture-open-geometry/1.0",
        "name": "流线概念椅",
        "description": "连续靠背与弧形双支撑",
        "materials": [
            {"id": "shell", "name": "软包", "base_color": "#D8C7AE", "roughness": 0.72, "metallic": 0.0},
            {"id": "frame", "name": "金属框架", "base_color": "#343836", "roughness": 0.32, "metallic": 0.8},
        ],
        "parts": [
            {"id": "seat", "name": "悬浮座面", "material_id": "shell", "parent_id": None,
             "position_mm": [0.0, 460.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0],
             "geometry": {"type": "box", "size_mm": [1180.0, 100.0, 650.0], "radius_mm": 50.0}},
            {"id": "back", "name": "连续包裹靠背", "material_id": "shell", "parent_id": None,
             "position_mm": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0],
             "geometry": {"type": "sweep", "path_mm": [[-500.0, 520.0, -250.0], [0.0, 860.0, -330.0], [500.0, 520.0, -250.0]], "radius_mm": 105.0, "tubular_segments": 40, "radial_segments": 12, "closed": False}},
            {"id": "left_support", "name": "左弧形支撑", "material_id": "frame", "parent_id": None,
             "position_mm": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0],
             "geometry": {"type": "sweep", "path_mm": [[-430.0, 30.0, -230.0], [-500.0, 230.0, 10.0], [-430.0, 430.0, 230.0]], "radius_mm": 30.0, "tubular_segments": 28, "radial_segments": 10, "closed": False}},
            {"id": "right_support", "name": "右弧形支撑", "material_id": "frame", "parent_id": None,
             "position_mm": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0],
             "geometry": {"type": "sweep", "path_mm": [[430.0, 30.0, -230.0], [500.0, 230.0, 10.0], [430.0, 430.0, 230.0]], "radius_mm": 30.0, "tubular_segments": 28, "radial_segments": 10, "closed": False}},
        ],
    }


@pytest.fixture
def db_and_task():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="waiting_input", active_mode="custom_furniture", agent_state_json={})
        db.add(task)
        db.commit()
        yield db, task


def planner(raw):
    operation = OPERATION.validate_python(raw)
    return lambda _instruction, _current, _history, _feedback: operation


def test_prepare_command_creates_without_database_side_effects():
    prepared = prepare_command(
        instruction="创建弧形椅",
        current_state={"current_version": 0, "current": None, "history": []},
        planner=planner({"operation": "create", "design": chair_design()}),
    )

    assert prepared.result == {
        "status": "completed",
        "code": "completed",
        "message": "已生成开放几何版本 1。",
        "current_version": 1,
        "model_id": prepared.result["model_id"],
        "part_count": 4,
    }
    assert prepared.extension["current_version"] == 1
    assert prepared.extension["history"]


def test_prepare_command_patches_existing_state_without_mutating_input():
    initial = prepare_command(
        instruction="创建弧形椅",
        current_state={"current_version": 0, "current": None, "history": []},
        planner=planner({"operation": "create", "design": chair_design()}),
    )
    current_state = initial.extension
    patch = next(part for part in chair_design()["parts"] if part["id"] == "back")
    patch["geometry"]["radius_mm"] = 112.0

    prepared = prepare_command(
        instruction="加厚靠背",
        current_state=current_state,
        planner=planner({"operation": "patch", "patch": {"upsert_parts": [patch]}}),
    )

    assert prepared.result["current_version"] == 2
    assert prepared.extension["current"]["design"]["parts"][1]["geometry"]["radius_mm"] == 112.0
    assert current_state["current"]["design"]["parts"][1]["geometry"]["radius_mm"] == 105.0


def test_prepare_command_repairs_once_and_reports_unsupported_without_retry():
    feedback = []
    candidates = [
        OpenGeometryError("invalid_model_output", "候选无效"),
        {"operation": "create", "design": chair_design()},
    ]

    def repairing_planner(_instruction, _current, _history, previous_feedback):
        feedback.append(previous_feedback)
        candidate = candidates.pop(0)
        if isinstance(candidate, Exception):
            raise candidate
        return OPERATION.validate_python(candidate)

    repaired = prepare_command(
        instruction="创建弧形椅",
        current_state={"current_version": 0, "current": None, "history": []},
        planner=repairing_planner,
    )
    assert repaired.result["code"] == "completed"
    assert feedback[1]["code"] == "invalid_model_output"

    calls = []
    unsupported = prepare_command(
        instruction="创建自由曲面",
        current_state=repaired.extension,
        planner=lambda *_: calls.append(1) or OPERATION.validate_python(
            {"operation": "unsupported", "reason": "需要 NURBS 曲面"}
        ),
    )
    assert unsupported.result["status"] == "completed"
    assert unsupported.result["code"] == "unsupported_geometry"
    assert unsupported.extension == repaired.extension
    assert calls == [1]


def test_prepare_command_can_disable_repair_for_composite_call_budget():
    calls = []

    def invalid_planner(_instruction, _current, _history, previous_feedback):
        calls.append(previous_feedback)
        raise OpenGeometryError("invalid_model_output", "候选无效")

    with pytest.raises(OpenGeometryError) as error:
        prepare_command(
            instruction="创建弧形椅",
            current_state={"current_version": 0, "current": None, "history": []},
            planner=invalid_planner,
            max_attempts=1,
        )

    assert error.value.code == "invalid_model_output"
    assert calls == [None]

    with pytest.raises(ValueError):
        prepare_command(
            instruction="创建弧形椅",
            current_state={"current_version": 0, "current": None, "history": []},
            planner=invalid_planner,
            max_attempts=3,
        )


@pytest.mark.parametrize(
    "invalid_state",
    [
        {"current_version": 1, "current": None, "history": []},
        {"current_version": 0, "current": None, "history": [{"version": 1}]},
    ],
)
def test_state_response_rejects_inconsistent_empty_version_chain(invalid_state):
    with pytest.raises(OpenGeometryError, match="版本链"):
        state_response(1, invalid_state)


def test_get_state_rejects_corrupted_persisted_version_chain(db_and_task):
    _db, task = db_and_task
    task.agent_state_json = {
        "open_geometry_furniture": {
            "current_version": 1,
            "current": None,
            "history": [],
        }
    }

    with pytest.raises(OpenGeometryError, match="版本链"):
        get_state(task)


def test_state_response_rejects_current_or_history_version_drift():
    created = prepare_command(
        instruction="创建",
        current_state={"current_version": 0, "current": None, "history": []},
        planner=planner({"operation": "create", "design": chair_design()}),
    ).extension
    mismatched_current = {
        **created,
        "current_version": 2,
    }
    duplicate_history = {
        **created,
        "history": [created["history"][0], created["history"][0]],
    }

    with pytest.raises(OpenGeometryError, match="当前版本"):
        state_response(1, mismatched_current)
    with pytest.raises(OpenGeometryError, match="严格递增"):
        state_response(1, duplicate_history)


def test_state_response_rejects_model_spec_that_does_not_recompile():
    created = prepare_command(
        instruction="创建",
        current_state={"current_version": 0, "current": None, "history": []},
        planner=planner({"operation": "create", "design": chair_design()}),
    ).extension
    tampered_version = {
        **created["current"],
        "model_spec": {
            **created["current"]["model_spec"],
            "家具名称": "被篡改的编译产物",
        },
    }
    tampered = {
        **created,
        "current": tampered_version,
        "history": [tampered_version],
    }

    with pytest.raises(OpenGeometryError, match="重新编译"):
        state_response(1, tampered)


@pytest.mark.parametrize(
    ("initial_state", "rejected_operation", "repair_operation", "error_code"),
    [
        (
            {"current_version": 0, "current": None, "history": []},
            {"operation": "patch", "patch": {"name": "错误首轮 patch"}},
            {"operation": "create", "design": chair_design()},
            "missing_design",
        ),
        (
            "created",
            {"operation": "create", "design": chair_design()},
            {"operation": "patch", "patch": {"name": "修复为局部修改"}},
            "replace_not_allowed",
        ),
        (
            "created",
            {
                "operation": "patch",
                "patch": {"remove_part_ids": ["missing_part"]},
            },
            {"operation": "patch", "patch": {"name": "保留已有部件"}},
            "unknown_part",
        ),
        (
            "created",
            {
                "operation": "patch",
                "patch": {"remove_material_ids": ["missing_material"]},
            },
            {"operation": "patch", "patch": {"name": "保留已有材质"}},
            "unknown_material",
        ),
    ],
)
def test_candidate_contract_errors_receive_one_structured_repair(
    initial_state,
    rejected_operation,
    repair_operation,
    error_code,
):
    if initial_state == "created":
        initial_state = prepare_command(
            instruction="创建",
            current_state={"current_version": 0, "current": None, "history": []},
            planner=planner({"operation": "create", "design": chair_design()}),
        ).extension
    candidates = [rejected_operation, repair_operation]
    feedback_seen = []

    def repairing_planner(_instruction, _current, _history, feedback):
        feedback_seen.append(feedback)
        return OPERATION.validate_python(candidates.pop(0))

    repaired = prepare_command(
        instruction="请修正候选操作",
        current_state=initial_state,
        planner=repairing_planner,
    )

    assert repaired.result["code"] == "completed"
    assert feedback_seen[0] is None
    assert feedback_seen[1]["code"] == error_code
    assert candidates == []


def test_rejected_candidate_gets_one_structured_repair_attempt(db_and_task):
    db, task = db_and_task
    below_floor = chair_design()
    below_floor["parts"][2]["geometry"]["path_mm"][0][1] = 10.0
    candidates = [
        OPERATION.validate_python({"operation": "create", "design": below_floor}),
        OPERATION.validate_python({"operation": "create", "design": chair_design()}),
    ]
    feedback_seen = []

    def correcting_planner(_instruction, _current, _history, feedback):
        feedback_seen.append(feedback)
        return candidates.pop(0)

    result = apply_command(
        db,
        task_id=task.id,
        client_mutation_id="repair-floor",
        base_version=0,
        instruction="创建一把落地的弧形双支撑椅",
        planner=correcting_planner,
    )

    assert result.current_version == 1
    assert feedback_seen[0] is None
    assert feedback_seen[1]["code"] == "below_floor"
    assert feedback_seen[1]["rejected_candidate"]["operation"] == "create"
    assert not candidates


def test_invalid_structured_output_gets_one_repair_attempt(db_and_task):
    db, task = db_and_task
    calls = []

    def correcting_planner(_instruction, _current, _history, feedback):
        calls.append(feedback)
        if feedback is None:
            raise OpenGeometryError(
                "invalid_model_output",
                "模型返回的开放几何 JSON 未通过严格校验",
                details=[{"type": "missing", "loc": ["design"]}],
            )
        return OPERATION.validate_python({"operation": "create", "design": chair_design()})

    result = apply_command(
        db,
        task_id=task.id,
        client_mutation_id="repair-schema",
        base_version=0,
        instruction="创建弧形椅",
        planner=correcting_planner,
    )

    assert result.current_version == 1
    assert calls[1]["code"] == "invalid_model_output"
    assert calls[1]["rejected_candidate"] is None


def test_compiles_template_external_curve_design_to_non_empty_deterministic_model():
    design = OpenGeometryDesign.model_validate(chair_design())
    model = compile_open_geometry(design)

    rule = model["确定性建模规则"]
    assert rule["生成器"] == "open_geometry_v1"
    assert len(rule["部件"]) == 4
    assert {part["几何"] for part in rule["部件"]} == {"box", "sweep"}
    assert all(value > 0 for value in rule["包围尺寸_mm"].values())


def test_three_local_patches_preserve_stable_ids_and_unmodified_properties(db_and_task):
    db, task = db_and_task
    created = apply_command(db, task_id=task.id, client_mutation_id="create-1", base_version=0,
                            instruction="创建连续曲面感座椅和弧形双支撑",
                            planner=planner({"operation": "create", "design": chair_design()}))
    back = next(part for part in chair_design()["parts"] if part["id"] == "back")
    back["geometry"]["path_mm"][1][2] = -430.0
    wrapped = apply_command(db, task_id=task.id, client_mutation_id="patch-1", base_version=1,
                            instruction="靠背再包裹一些",
                            planner=planner({"operation": "patch", "patch": {"upsert_parts": [back]}}))
    left = next(part for part in chair_design()["parts"] if part["id"] == "left_support")
    right = next(part for part in chair_design()["parts"] if part["id"] == "right_support")
    left["geometry"]["radius_mm"] = 24.0
    right["geometry"]["radius_mm"] = 24.0
    left["geometry"]["path_mm"][0][1] = 24.0
    right["geometry"]["path_mm"][0][1] = 24.0
    thinner = apply_command(db, task_id=task.id, client_mutation_id="patch-2", base_version=2,
                            instruction="双支撑更细，颜色保持不变",
                            planner=planner({"operation": "patch", "patch": {"upsert_parts": [left, right]}}))
    widened = apply_command(db, task_id=task.id, client_mutation_id="patch-3", base_version=3,
                            instruction="整体加宽10%",
                            planner=planner({"operation": "patch", "patch": {"scale": [1.1, 1.0, 1.0]}}))

    assert [created.current_version, wrapped.current_version, thinner.current_version, widened.current_version] == [1, 2, 3, 4]
    design = widened.current.design
    assert {part.id for part in design.parts} == {"seat", "back", "left_support", "right_support"}
    assert next(part for part in design.parts if part.id == "back").geometry.path_mm[1][2] == -430.0
    assert next(part for part in design.parts if part.id == "left_support").geometry.radius_mm == 24.0
    assert design.scale == [1.1, 1.0, 1.0]
    assert design.materials[0].base_color == "#D8C7AE"
    original_width = created.current.model_spec["确定性建模规则"]["包围尺寸_mm"]["宽"]
    widened_width = widened.current.model_spec["确定性建模规则"]["包围尺寸_mm"]["宽"]
    assert widened_width == pytest.approx(original_width * 1.1)


def test_invalid_patch_does_not_replace_last_valid_version(db_and_task):
    db, task = db_and_task
    apply_command(db, task_id=task.id, client_mutation_id="create", base_version=0,
                  instruction="创建", planner=planner({"operation": "create", "design": chair_design()}))
    invalid = next(part for part in chair_design()["parts"] if part["id"] == "seat")
    invalid["material_id"] = "missing"

    with pytest.raises(OpenGeometryError, match="不满足开放几何约束"):
        apply_command(db, task_id=task.id, client_mutation_id="bad", base_version=1,
                      instruction="使用不存在的材质", planner=planner({"operation": "patch", "patch": {"upsert_parts": [invalid]}}))

    db.refresh(task)
    state = get_state(task)
    assert state.current_version == 1
    assert state.current.design.name == "流线概念椅"


def test_idempotency_and_restore_create_new_version(db_and_task):
    db, task = db_and_task
    first = apply_command(db, task_id=task.id, client_mutation_id="same", base_version=0,
                          instruction="创建", planner=planner({"operation": "create", "design": chair_design()}))
    repeated = apply_command(db, task_id=task.id, client_mutation_id="same", base_version=0,
                             instruction="创建", planner=lambda *_: pytest.fail("幂等重试不应再次规划"))
    assert repeated == first
    with pytest.raises(OpenGeometryIdempotencyConflict):
        apply_command(db, task_id=task.id, client_mutation_id="same", base_version=0,
                      instruction="不同请求", planner=planner({"operation": "create", "design": chair_design()}))

    back = next(part for part in chair_design()["parts"] if part["id"] == "back")
    back["geometry"]["radius_mm"] = 130.0
    apply_command(db, task_id=task.id, client_mutation_id="change", base_version=1,
                  instruction="加厚靠背", planner=planner({"operation": "patch", "patch": {"upsert_parts": [back]}}))
    restored = restore_version(db, task_id=task.id, client_mutation_id="undo", base_version=2, target_version=1)
    assert restored.current_version == 3
    assert restored.current.source == "restore"
    assert next(part for part in restored.current.design.parts if part.id == "back").geometry.radius_mm == 105.0


def test_schema_rejects_unknown_reference_bounds_and_complexity():
    invalid_reference = chair_design()
    invalid_reference["parts"][0]["parent_id"] = "missing"
    with pytest.raises(ValidationError, match="不存在的父部件"):
        OpenGeometryDesign.model_validate(invalid_reference)

    out_of_bounds = chair_design()
    out_of_bounds["parts"][1]["geometry"]["path_mm"][0][0] = 9000.0
    with pytest.raises(ValidationError, match="超出允许坐标范围"):
        OpenGeometryDesign.model_validate(out_of_bounds)

    too_complex = chair_design()
    too_complex["parts"] = [
        {**too_complex["parts"][0], "id": f"part_{index}"}
        for index in range(33)
    ]
    with pytest.raises(ValidationError, match="部件数量"):
        OpenGeometryDesign.model_validate(too_complex)


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("material", "roughness"),
        ("material", "metallic"),
        ("part", "position_mm"),
        ("part", "rotation_deg"),
        ("design", "scale"),
    ],
)
def test_schema_rejects_non_finite_material_and_transform_values(
    target,
    field,
    invalid_value,
):
    design = chair_design()
    owner = {
        "material": design["materials"][0],
        "part": design["parts"][0],
        "design": design,
    }[target]
    if target == "design" and field == "scale":
        owner[field] = [1.0, 1.0, 1.0]
    current = owner[field]
    owner[field] = [invalid_value, *current[1:]] if isinstance(current, list) else invalid_value

    with pytest.raises(ValidationError, match="finite number"):
        OpenGeometryDesign.model_validate(design)


@pytest.mark.parametrize(
    ("geometry", "field", "nested"),
    [
        ({"type": "box", "size_mm": [500.0, 80.0, 400.0], "radius_mm": 20.0}, "size_mm", True),
        ({"type": "box", "size_mm": [500.0, 80.0, 400.0], "radius_mm": 20.0}, "radius_mm", False),
        ({"type": "cylinder", "radius_mm": 30.0, "top_radius_mm": 25.0, "height_mm": 400.0}, "radius_mm", False),
        ({"type": "cylinder", "radius_mm": 30.0, "top_radius_mm": 25.0, "height_mm": 400.0}, "top_radius_mm", False),
        ({"type": "cylinder", "radius_mm": 30.0, "top_radius_mm": 25.0, "height_mm": 400.0}, "height_mm", False),
        ({"type": "sphere", "radius_mm": 100.0, "scale": [1.0, 1.0, 1.0]}, "radius_mm", False),
        ({"type": "sphere", "radius_mm": 100.0, "scale": [1.0, 1.0, 1.0]}, "scale", True),
        ({"type": "sweep", "path_mm": [[0.0, 30.0, 0.0], [0.0, 100.0, 0.0], [0.0, 200.0, 0.0]], "radius_mm": 20.0}, "path_mm", True),
        ({"type": "sweep", "path_mm": [[0.0, 30.0, 0.0], [0.0, 100.0, 0.0], [0.0, 200.0, 0.0]], "radius_mm": 20.0}, "radius_mm", False),
        ({"type": "lathe", "profile_mm": [[0.0, 0.0], [100.0, 0.0], [100.0, 300.0]]}, "profile_mm", True),
    ],
)
def test_schema_rejects_non_finite_geometry_values(geometry, field, nested):
    design = chair_design()
    design["parts"] = [design["parts"][0]]
    design["parts"][0]["geometry"] = geometry
    if nested:
        if field in {"path_mm", "profile_mm"}:
            geometry[field][0][0] = float("nan")
        else:
            geometry[field][0] = float("nan")
    else:
        geometry[field] = float("inf")

    with pytest.raises(ValidationError, match="finite number"):
        OpenGeometryDesign.model_validate(design)


@pytest.mark.parametrize(
    ("path_mm", "closed", "message"),
    [
        ([[0.0, 30.0, 0.0]] * 3, False, "总长度必须至少"),
        ([[0.0, 30.0, 0.0], [0.05, 30.0, 0.0], [100.0, 30.0, 0.0]], False, "连续控制点间距"),
        ([[0.0, 30.0, 0.0], [100.0, 30.0, 0.0], [0.05, 30.0, 0.0]], True, "闭合端点间距"),
    ],
)
def test_sweep_rejects_collapsed_and_near_zero_segments(path_mm, closed, message):
    design = chair_design()
    design["parts"][1]["geometry"].update(path_mm=path_mm, closed=closed)

    with pytest.raises(ValidationError, match=message):
        OpenGeometryDesign.model_validate(design)


@pytest.mark.parametrize(
    ("path_mm", "closed"),
    [
        ([[0.0, 30.0, 0.0], [100.0, 30.0, 0.0], [200.0, 30.0, 0.0]], False),
        ([[0.0, 30.0, 0.0], [100.0, 30.0, 0.0], [50.0, 130.0, 0.0]], True),
    ],
)
def test_sweep_accepts_straight_and_non_degenerate_closed_paths(path_mm, closed):
    design = chair_design()
    design["parts"][1]["geometry"].update(path_mm=path_mm, closed=closed)

    assert OpenGeometryDesign.model_validate(design).parts[1].geometry.path_mm == path_mm


@pytest.mark.parametrize(
    "profile_mm",
    [
        [[0.0, 0.0], [0.0, 100.0], [0.0, 200.0]],
        [[100.0, 50.0], [100.0, 50.0], [100.0, 50.0]],
        [[0.0, 0.0], [0.01, 100.0], [0.01, 200.0]],
    ],
)
def test_lathe_rejects_profiles_that_cannot_create_visible_surface(profile_mm):
    design = chair_design()
    design["parts"][0]["geometry"] = {"type": "lathe", "profile_mm": profile_mm}

    with pytest.raises(ValidationError, match="lathe 轮廓无法生成可见表面"):
        OpenGeometryDesign.model_validate(design)


@pytest.mark.parametrize(
    "profile_mm",
    [
        [[0.0, 0.0], [100.0, 0.0], [100.0, 300.0], [0.0, 300.0]],
        [[20.0, 0.0], [120.0, 80.0], [90.0, 240.0], [0.0, 300.0]],
    ],
)
def test_lathe_accepts_cylinder_and_curved_profiles(profile_mm):
    design = chair_design()
    design["parts"][0]["geometry"] = {"type": "lathe", "profile_mm": profile_mm}

    assert OpenGeometryDesign.model_validate(design).parts[0].geometry.profile_mm == profile_mm


def test_skill_runtime_and_shared_contract_geometry_types_stay_aligned():
    from pathlib import Path
    import json

    root = Path(__file__).resolve().parents[2]
    contract = json.loads((root / "shared/furniture_open_geometry_contract.json").read_text(encoding="utf-8"))
    skill = (root / "skills/furniture-open-geometry/SKILL.md").read_text(encoding="utf-8")
    operation_schema = OPERATION.json_schema()

    for geometry_type in contract["geometry_types"]:
        assert f'"{geometry_type}"' in json.dumps(operation_schema)
        assert f"`{geometry_type}`" in skill
    for operation_type in contract["operation_types"]:
        assert f'"{operation_type}"' in json.dumps(operation_schema)
        assert f"`{operation_type}`" in skill
    assert contract["limits"]["min_geometry_length_mm"] == MIN_GEOMETRY_LENGTH_MM
    assert f"{MIN_GEOMETRY_LENGTH_MM}mm" in skill


def test_skill_defines_deterministic_floor_constraints_for_every_geometry():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    skill = (root / "skills/furniture-open-geometry/SKILL.md").read_text(encoding="utf-8")

    expected_rules = {
        "box": "world_position_y - size_mm[1] / 2 >= 0",
        "cylinder": "world_position_y - height_mm / 2 >= 0",
        "sphere": "world_position_y - radius_mm * scale[1] >= 0",
        "sweep": "world_position_y + min(path_mm[*][1]) - radius_mm >= 0",
        "lathe": "world_position_y + min(profile_mm[*][1]) >= 0",
    }
    for geometry_type, formula in expected_rules.items():
        assert f"`{geometry_type}`" in skill
        assert f"`{formula}`" in skill


def test_follow_up_planner_receives_current_design_and_recent_turn_context(db_and_task):
    db, task = db_and_task
    apply_command(db, task_id=task.id, client_mutation_id="context-create", base_version=0,
                  instruction="创建一把曲面椅", planner=planner({"operation": "create", "design": chair_design()}))
    captured = {}

    def contextual_planner(instruction, current, history, feedback):
        captured.update(
            instruction=instruction,
            current=current,
            history=history,
            feedback=feedback,
        )
        back = next(part for part in current.parts if part.id == "back")
        payload = back.model_dump(mode="json")
        payload["geometry"]["radius_mm"] = 112.0
        return OPERATION.validate_python({"operation": "patch", "patch": {"upsert_parts": [payload]}})

    result = apply_command(db, task_id=task.id, client_mutation_id="context-patch", base_version=1,
                           instruction="把刚才那个靠背再包裹一点，保持颜色不变", planner=contextual_planner)

    assert captured["current"].materials[0].base_color == "#D8C7AE"
    assert captured["history"][-1]["instruction"] == "创建一把曲面椅"
    assert "back" in captured["history"][-1]["part_ids"]
    assert captured["feedback"] is None
    assert result.current.design.materials[0].base_color == "#D8C7AE"


def test_planner_receives_only_the_six_most_recent_versions():
    state = prepare_command(
        instruction="版本 1",
        current_state={"current_version": 0, "current": None, "history": []},
        planner=planner({"operation": "create", "design": chair_design()}),
    ).extension
    for version in range(2, 8):
        state = prepare_command(
            instruction=f"版本 {version}",
            current_state=state,
            planner=planner(
                {"operation": "patch", "patch": {"name": f"概念椅 v{version}"}}
            ),
        ).extension

    captured = {}

    def capture_context(_instruction, _current, history, _feedback):
        captured["history"] = history
        return OPERATION.validate_python(
            {"operation": "unsupported", "reason": "仅检查上下文窗口"}
        )

    prepare_command(
        instruction="检查最近历史",
        current_state=state,
        planner=capture_context,
    )

    assert [item["version"] for item in captured["history"]] == [2, 3, 4, 5, 6, 7]
    assert [item["instruction"] for item in captured["history"]] == [
        "版本 2",
        "版本 3",
        "版本 4",
        "版本 5",
        "版本 6",
        "版本 7",
    ]


def test_model_attempt_is_recorded_in_task_timeline(db_and_task):
    db, task = db_and_task

    def metered_planner(_instruction, _current, _history, _feedback):
        from app.services import llm_service
        llm_service._mark_model_call_attempted()
        return OPERATION.validate_python({"operation": "create", "design": chair_design()})

    apply_command(db, task_id=task.id, client_mutation_id="ledger-create", base_version=0,
                  instruction="创建", planner=metered_planner)
    event = db.query(TaskExecutionEvent).filter_by(task_id=task.id).one()
    assert event.event_code == "agent.open_geometry.completed"
    assert event.attempt == 1
    assert event.billing_status == "unknown"


def test_same_client_id_can_record_multiple_failed_model_attempts_without_500(db_and_task):
    db, task = db_and_task

    def failing_planner(*_args):
        from app.services import llm_service
        llm_service._mark_model_call_attempted()
        raise OpenGeometryError("invalid_model_output", "无效输出")

    for _ in range(2):
        with pytest.raises(OpenGeometryError, match="无效输出"):
            apply_command(db, task_id=task.id, client_mutation_id="retry-failure", base_version=0,
                          instruction="创建", planner=failing_planner)

    events = db.query(TaskExecutionEvent).filter_by(task_id=task.id).order_by(TaskExecutionEvent.id).all()
    assert [event.attempt for event in events] == [1, 2]
    assert len({event.event_key for event in events}) == 2
