from import_furniture_specs import load_specs


def test_load_specs_injects_ready_deterministic_rule_into_sample() -> None:
    specs = load_specs()
    chair = next(
        item for item in specs if item["家具名称"] == "中古风绒布单人椅"
    )

    rule = chair["确定性建模规则"]
    assert rule["规则状态"] == "ready"
    assert rule["模型ID"] == "HAUS-CHAIR-001"
    assert rule["生成器"] == "lounge_chair_v1"
    assert len(rule["部件"]) == 14

