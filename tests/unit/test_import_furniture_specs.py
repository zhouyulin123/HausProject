from import_furniture_specs import load_specs, product_payload_from_spec


def test_load_specs_injects_ready_deterministic_rule_into_sample() -> None:
    specs = load_specs()
    assert len(specs) == 40
    chair = next(
        item for item in specs if item["家具名称"] == "中古风绒布单人椅"
    )

    rule = chair["确定性建模规则"]
    assert rule["规则状态"] == "ready"
    assert rule["模型ID"] == "HAUS-CHAIR-001"
    assert rule["生成器"] == "lounge_chair_v1"
    assert len(rule["部件"]) == 14


def test_product_payload_from_common_spec_is_complete() -> None:
    spec = next(item for item in load_specs() if item["家具名称"] == "白橡木圆角长茶几")

    payload = product_payload_from_spec(spec, "HAUS-COFFEE-003")

    assert payload == {
        "sku": "HAUS-COFFEE-003",
        "name": "白橡木圆角长茶几",
        "category": "茶几",
        "room": "客厅",
        "style": "原木风",
        "material": "北美白橡木木蜡油",
        "price": 1600,
        "price_max": 2300,
        "size": "1200 × 600 × 360mm",
        "selling_point": "真实尺寸参数建模，北美白橡木木蜡油材质",
        "alternative": "可选同类型其他参数款",
        "model_width_mm": 1200,
        "model_height_mm": 360,
        "model_depth_mm": 600,
        "model_source": "家具3D真实参数",
    }
