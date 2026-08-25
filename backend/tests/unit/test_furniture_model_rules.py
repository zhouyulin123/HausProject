import json
from pathlib import Path

import pytest

from app.services.furniture_model_rules import (
    FurnitureRuleError,
    build_deterministic_rule_catalog,
    compile_lounge_chair_rule,
    merge_furniture_catalogs,
    validate_deterministic_rule,
)


SPEC_FILE = Path(__file__).resolve().parents[2] / "furniture_3d_specs.json"


def _lounge_chair_spec() -> dict:
    catalog = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    return next(
        item
        for item in catalog["家具列表"]
        if item["家具名称"] == "中古风绒布单人椅"
    )


def test_merge_furniture_catalogs_normalizes_two_batches() -> None:
    first = {"家具列表": [{"家具名称": "沙发 A", "空间": "客厅"}]}
    second = {"家具列表": [{"家具名称": "餐椅 B", "适用空间": "餐厅"}]}

    merged = merge_furniture_catalogs(
        [("精选家具", first), ("常见家具", second)]
    )

    assert merged["家具数量"] == 2
    assert [item["数据批次"] for item in merged["家具列表"]] == [
        "精选家具",
        "常见家具",
    ]
    assert [item["空间"] for item in merged["家具列表"]] == ["客厅", "餐厅"]


def test_merge_furniture_catalogs_rejects_duplicate_names() -> None:
    catalog = {"家具列表": [{"家具名称": "重复家具", "空间": "客厅"}]}

    with pytest.raises(FurnitureRuleError, match="重复家具"):
        merge_furniture_catalogs([("批次一", catalog), ("批次二", catalog)])


def test_lounge_chair_rule_is_complete_and_has_no_runtime_defaults() -> None:
    rule = compile_lounge_chair_rule(_lounge_chair_spec())

    validate_deterministic_rule(rule)

    assert rule["模型ID"] == "HAUS-CHAIR-001"
    assert rule["生成器"] == "lounge_chair_v1"
    assert rule["坐标系统"] == {
        "单位": "mm",
        "上轴": "Y",
        "前向": "+Z",
        "原点": "floor_center",
    }
    assert rule["包围尺寸_mm"] == {"宽": 720, "高": 790, "深": 780}
    assert rule["几何规则"]["座位数"] == 1
    assert rule["几何规则"]["座垫"]["尺寸_mm"] == [570, 90, 525]
    assert rule["几何规则"]["木扶手"]["截面_mm"] == [32, 46]
    assert rule["几何规则"]["靠背"]["后倾角_deg"] == 12
    assert {part["部件ID"] for part in rule["部件"]} == {
        "seat_cushion",
        "back_cushion",
        "left_arm",
        "right_arm",
        "front_seat_rail",
        "rear_seat_rail",
        "left_seat_rail",
        "right_seat_rail",
        "left_back_post",
        "right_back_post",
        "front_left_leg",
        "front_right_leg",
        "rear_left_leg",
        "rear_right_leg",
    }
    assert {slot["槽位ID"] for slot in rule["材质槽"]} == {
        "upholstery",
        "wood_frame",
    }
    assert rule["规则状态"] == "ready"


def test_rule_validation_rejects_unknown_material_binding() -> None:
    rule = compile_lounge_chair_rule(_lounge_chair_spec())
    rule["部件"][0]["材质槽"] = "missing_material"

    with pytest.raises(FurnitureRuleError, match="missing_material"):
        validate_deterministic_rule(rule)


def test_rule_catalog_tracks_ready_and_pending_models() -> None:
    chair = _lounge_chair_spec()
    catalog = {
        "家具数量": 3,
        "家具列表": [
            chair,
            {"家具名称": "测试沙发", "家具类型": "沙发"},
            {"家具名称": "测试餐桌", "家具类型": "餐桌"},
        ],
    }

    rules = build_deterministic_rule_catalog(catalog)

    assert rules["家具数量"] == 3
    assert rules["已完成规则数量"] == 1
    assert rules["待完善规则数量"] == 2
    assert len({item["模型ID"] for item in rules["模型目录"]}) == 3
    sample = next(
        item for item in rules["模型目录"] if item["家具名称"] == "中古风绒布单人椅"
    )
    assert sample["规则状态"] == "ready"
    assert sample["确定性规则"]["模型ID"] == sample["模型ID"]
    assert all(
        item["规则状态"] == "pending"
        for item in rules["模型目录"]
        if item["家具名称"] != "中古风绒布单人椅"
    )
