import json
from pathlib import Path

import pytest

from app.services.furniture_model_rules import (
    FurnitureRuleError,
    build_deterministic_rule_catalog,
    compile_lounge_chair_rule,
    compile_round_rect_coffee_table_rule,
    merge_furniture_catalogs,
    validate_deterministic_rule,
)


SPEC_FILE = Path(__file__).resolve().parents[2] / "furniture_3d_specs.json"
SPEC_40_FILE = Path(__file__).resolve().parents[2] / "furniture_3d_specs_40.json"


def _lounge_chair_spec() -> dict:
    catalog = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    return next(
        item
        for item in catalog["家具列表"]
        if item["家具名称"] == "中古风绒布单人椅"
    )


def _coffee_table_spec() -> dict:
    catalog = json.loads(SPEC_40_FILE.read_text(encoding="utf-8"))
    return next(
        item
        for item in catalog["家具列表"]
        if item["家具名称"] == "白橡木圆角长茶几"
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
    assert rule["规则版本"] == "1.2.0"
    assert rule["外观规则"]["软包"]["滚边"] == {
        "启用": True,
        "直径_mm": 7,
    }
    assert rule["外观规则"]["软包"]["绒面"] == {
        "方向性": True,
        "法线强度": 0.2,
        "纹理周期_mm": 3,
    }
    assert rule["外观规则"]["软包"]["坐垫形变"] == {
        "前缘压缩": 0.04,
        "中心隆起_mm": 10,
    }
    assert rule["外观规则"]["软包"]["靠背曲面"] == {
        "横向弧度半径_mm": 900,
    }
    assert rule["外观规则"]["软包"]["缝线"] == {
        "启用": True,
        "线径_mm": 1.4,
        "内缩_mm": 10,
    }
    assert rule["外观规则"]["木材"] == {
        "树种": "深色白蜡木",
        "纹理周期_mm": 42,
        "法线强度": 0.16,
        "透明面漆": {"强度": 0.14, "粗糙度": 0.62},
        "榫卯节点": {
            "启用": True,
            "榫肩线宽_mm": 1.2,
            "距构件端部_mm": 18,
        },
    }
    parts = {part["部件ID"]: part for part in rule["部件"]}
    assert parts["seat_cushion"]["位置_mm"][2] == 0
    assert parts["back_cushion"]["位置_mm"][2] == -220
    assert parts["left_arm"]["位置_mm"][1] == 572
    assert parts["front_left_leg"]["尺寸_mm"][1] == 549
    assert parts["front_left_leg"]["位置_mm"][2] == 246.5
    assert parts["rear_left_leg"]["旋转_deg"] == [8, 0, 0]
    assert parts["left_back_post"]["位置_mm"][1] == pytest.approx(561.691, abs=0.001)
    assert parts["left_back_post"]["位置_mm"][2] == pytest.approx(-199.181, abs=0.001)
    assert set(parts) == {
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


def test_rule_validation_rejects_incomplete_upholstery_appearance() -> None:
    rule = compile_lounge_chair_rule(_lounge_chair_spec())
    del rule["外观规则"]["软包"]["靠背曲面"]

    with pytest.raises(FurnitureRuleError, match="靠背曲面"):
        validate_deterministic_rule(rule)


def test_rule_validation_rejects_incomplete_wood_appearance() -> None:
    rule = compile_lounge_chair_rule(_lounge_chair_spec())
    del rule["外观规则"]["木材"]["榫卯节点"]

    with pytest.raises(FurnitureRuleError, match="榫卯节点"):
        validate_deterministic_rule(rule)


def test_rule_validation_rejects_unknown_material_binding() -> None:
    rule = compile_lounge_chair_rule(_lounge_chair_spec())
    rule["部件"][0]["材质槽"] = "missing_material"

    with pytest.raises(FurnitureRuleError, match="missing_material"):
        validate_deterministic_rule(rule)


def test_round_rect_coffee_table_rule_has_manufacturable_structure() -> None:
    rule = compile_round_rect_coffee_table_rule(_coffee_table_spec())

    validate_deterministic_rule(rule)

    assert rule["模型ID"] == "HAUS-COFFEE-003"
    assert rule["生成器"] == "coffee_table_v1"
    assert rule["包围尺寸_mm"] == {"宽": 1200, "高": 360, "深": 600}
    assert rule["几何规则"]["台面"] == {
        "尺寸_mm": [1200, 32, 600],
        "平面圆角半径_mm": 120,
        "边缘圆角_mm": 10,
    }
    assert rule["几何规则"]["桌腿"]["外撇角_deg"] == 2
    parts = {part["部件ID"]: part for part in rule["部件"]}
    assert set(parts) == {
        "tabletop",
        "front_left_leg",
        "front_right_leg",
        "rear_left_leg",
        "rear_right_leg",
        "left_hidden_stretcher",
        "right_hidden_stretcher",
    }
    assert parts["tabletop"]["位置_mm"] == [0, 344, 0]
    assert parts["front_left_leg"]["旋转_deg"] == [2, 0, -2]
    assert parts["left_hidden_stretcher"]["几何"] == "wood_rail"
    assert rule["外观规则"]["木材"]["纹理周期_mm"] == 54


def test_rule_catalog_compiles_all_40_products_without_pending_models() -> None:
    catalog = json.loads(SPEC_40_FILE.read_text(encoding="utf-8"))

    rules = build_deterministic_rule_catalog(catalog)

    assert rules["家具数量"] == 40
    assert rules["已完成规则数量"] == 40
    assert rules["待完善规则数量"] == 0
    assert len({item["模型ID"] for item in rules["模型目录"]}) == 40
    assert all(item["规则状态"] == "ready" for item in rules["模型目录"])
    for entry in rules["模型目录"]:
        rule = entry["确定性规则"]
        validate_deterministic_rule(rule)
        assert rule["模型ID"] == entry["模型ID"]
        assert rule["设计冻结"]
        assert rule["安装规则"]["基准"] in {"floor", "ceiling", "wall"}
        assert all(slot["表面类型"] for slot in rule["材质槽"])


def test_catalog_rules_cover_every_furniture_family_with_detailed_parts() -> None:
    catalog = json.loads(SPEC_40_FILE.read_text(encoding="utf-8"))
    entries = build_deterministic_rule_catalog(catalog)["模型目录"]
    by_name = {entry["家具名称"]: entry["确定性规则"] for entry in entries}

    expected = {
        "云感模块三人沙发": ("sofa_v2", 12),
        "岩板套几（大小两件）": ("table_v2", 6),
        "白橡木藤编餐椅": ("chair_v2", 9),
        "现代悬浮灯带储物床": ("bed_v2", 8),
        "奶油白蘑菇落地灯": ("lamp_v2", 3),
        "低饱和几何短绒地毯": ("rug_v2", 2),
        "亚麻遮光窗帘": ("curtain_v2", 3),
        "藤编床头柜": ("cabinet_v2", 8),
        "白蜡木电动升降书桌": ("desk_v2", 8),
        "白橡木开放书架": ("shelf_v2", 11),
        "人体工学椅": ("ergonomic_chair_v2", 12),
    }
    for name, (generator, minimum_parts) in expected.items():
        assert by_name[name]["生成器"] == generator
        assert len(by_name[name]["部件"]) >= minimum_parts


def test_catalog_rules_use_only_supported_explicit_geometry() -> None:
    catalog = json.loads(SPEC_40_FILE.read_text(encoding="utf-8"))
    entries = build_deterministic_rule_catalog(catalog)["模型目录"]
    supported = {
        "rounded_box",
        "rounded_cushion",
        "curved_cushion",
        "rounded_tabletop",
        "cloud_tabletop",
        "elliptical_tabletop",
        "wood_rail",
        "tapered_wood_leg",
        "top_pivot_tapered_wood_leg",
        "tapered_wood_post",
        "cylinder",
        "frustum",
        "tube",
        "rug_panel",
        "curtain_panel",
        "mesh_panel",
        "sphere",
        "torus",
    }

    for entry in entries:
        rule = entry["确定性规则"]
        assert {part["几何"] for part in rule["部件"]} <= supported

    pendant = next(
        entry["确定性规则"]
        for entry in entries
        if entry["家具名称"] == "黄铜玻璃餐吊灯"
    )
    assert sum(part["几何"] == "sphere" for part in pendant["部件"]) == 6
    assert sum(part["几何"] == "torus" for part in pendant["部件"]) == 1


def _catalog_rules_by_name() -> dict[str, dict]:
    catalog = json.loads(SPEC_40_FILE.read_text(encoding="utf-8"))
    entries = build_deterministic_rule_catalog(catalog)["模型目录"]
    return {entry["家具名称"]: entry["确定性规则"] for entry in entries}


def test_sectional_sofas_use_an_l_shaped_support_structure() -> None:
    by_name = _catalog_rules_by_name()

    for name in ("奶油白猫抓布转角沙发", "浅灰羽绒感转角沙发"):
        rule = by_name[name]
        parts = {part["部件ID"]: part for part in rule["部件"]}
        total_depth = rule["包围尺寸_mm"]["深"]

        assert "main_seat_frame" in parts
        assert "chaise_frame" in parts
        assert parts["main_seat_frame"]["尺寸_mm"][2] < total_depth * 0.7
        assert parts["chaise_frame"]["尺寸_mm"][2] > total_depth * 0.8
        assert "chaise_outer_arm" in parts
        assert "right_arm" not in parts


def test_sofa_seat_cushions_connect_to_the_back_instead_of_floating_forward() -> None:
    by_name = _catalog_rules_by_name()

    for rule in (item for item in by_name.values() if item["生成器"] == "sofa_v2"):
        total_depth = rule["包围尺寸_mm"]["深"]
        back = next(part for part in rule["部件"] if part["部件ID"] == "back_cushion_1")
        seat = next(part for part in rule["部件"] if part["部件ID"] == "seat_cushion_1")
        back_front = back["位置_mm"][2] + back["尺寸_mm"][2] / 2
        seat_rear = seat["位置_mm"][2] - seat["尺寸_mm"][2] / 2

        assert abs(back_front - seat_rear) < total_depth * 0.06


def test_nested_table_legs_are_evenly_distributed_around_each_top() -> None:
    rule = _catalog_rules_by_name()["岩板套几（大小两件）"]
    parts = {part["部件ID"]: part for part in rule["部件"]}

    for prefix in ("large", "small"):
        center_x = parts[f"{prefix}_top"]["位置_mm"][0]
        offsets = [
            (
                parts[f"{prefix}_leg_{index}"]["位置_mm"][0] - center_x,
                parts[f"{prefix}_leg_{index}"]["位置_mm"][2],
            )
            for index in range(1, 4)
        ]
        radii = [(x * x + z * z) ** 0.5 for x, z in offsets]

        assert max(radii) - min(radii) < 0.01
        assert abs(sum(x for x, _ in offsets)) < 0.01
        assert abs(sum(z for _, z in offsets)) < 0.01


def test_chair_materials_follow_part_semantics_instead_of_slot_order() -> None:
    by_name = _catalog_rules_by_name()

    for name in ("藤编靠背餐椅", "白橡木藤编餐椅"):
        rule = by_name[name]
        parts = {part["部件ID"]: part for part in rule["部件"]}
        surfaces = {slot["槽位ID"]: slot["表面类型"] for slot in rule["材质槽"]}
        assert parts["back"]["几何"] == "mesh_panel"
        assert surfaces[parts["back"]["材质槽"]] == "rattan"
        assert surfaces[parts["seat"]["材质槽"]] == "fabric"
        assert surfaces[parts["leg_fl"]["材质槽"]] == "wood"

    upholstered = by_name["奶油白软包餐椅"]
    parts = {part["部件ID"]: part for part in upholstered["部件"]}
    surfaces = {
        slot["槽位ID"]: slot["表面类型"]
        for slot in upholstered["材质槽"]
    }
    assert surfaces[parts["seat"]["材质槽"]] == "fabric"
    assert surfaces[parts["back"]["材质槽"]] == "fabric"
    assert surfaces[parts["leg_fl"]["材质槽"]] == "metal"


def test_ergonomic_chair_spokes_point_radially_from_the_hub() -> None:
    rule = _catalog_rules_by_name()["人体工学椅"]
    parts = {part["部件ID"]: part for part in rule["部件"]}

    for index, angle in enumerate((0, 72, 144, 216, 288), start=1):
        assert parts[f"star_spoke_{index}"]["旋转_deg"] == [90, angle, 0]

    for side in ("left", "right"):
        support = parts[f"{side}_arm_support"]
        pad = parts[f"{side}_arm_pad"]
        assert support["尺寸_mm"][1] > support["尺寸_mm"][2]
        assert pad["尺寸_mm"][2] > pad["尺寸_mm"][1] * 5
        assert pad["位置_mm"][1] > support["位置_mm"][1]
