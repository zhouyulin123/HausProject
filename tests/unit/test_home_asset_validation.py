"""冻结准入必须与原始参数的确定性编译结果一致。"""

from copy import deepcopy
import json

import pytest

from app.services.home_design_asset_service import _model
from app.services.furniture_model_rules import (
    build_deterministic_rule_catalog,
    compile_lounge_chair_rule,
)
from tests.unit.test_furniture_model_rules import SPEC_40_FILE, _lounge_chair_spec


def sample():
    spec = _lounge_chair_spec()
    spec["确定性建模规则"] = compile_lounge_chair_rule(spec)
    return spec


@pytest.mark.parametrize("case", ["position", "rotation", "geometry", "scale", "bounds"])
def test_reject_modified_compiled_geometry(case):
    spec = sample()
    rule = spec["确定性建模规则"]
    if case == "position":
        rule["部件"][0]["位置_mm"] = ["oops", 0, 0]
    elif case == "rotation":
        rule["部件"][0]["旋转_deg"] = [True, 0, 0]
    elif case == "geometry":
        rule["部件"][0]["几何"] = "unsupported_mesh"
    elif case == "scale":
        rule["全局缩放"] = [10, 10, 10]
    else:
        rule["包围尺寸_mm"] = {"宽": 1, "高": 1, "深": 1}
    with pytest.raises(ValueError):
        _model(spec)


def test_original_lounge_fixture_stays_available():
    assert _model(sample())[0]["width"] == 0.72


@pytest.mark.parametrize("case", ["missing_source", "changed_source", "unknown_id", "missing_id"])
def test_reject_unrecoverable_or_changed_source(case):
    spec = sample()
    if case == "missing_source":
        del spec["尺寸参数"]
    elif case == "changed_source":
        spec["尺寸参数"]["总宽"] += 100
    elif case == "unknown_id":
        spec = {"确定性建模规则": spec["确定性建模规则"]}
        spec["确定性建模规则"]["模型ID"] = "unknown"
    else:
        spec = {"确定性建模规则": spec["确定性建模规则"]}
        del spec["确定性建模规则"]["模型ID"]
    with pytest.raises(ValueError):
        _model(spec)


def test_catalog_roundtrip_preserves_floor_only_scope():
    catalog = json.loads(SPEC_40_FILE.read_text(encoding="utf-8"))
    entries = build_deterministic_rule_catalog(catalog)["模型目录"]
    assert len(entries) == 40
    for spec, entry in zip(catalog["家具列表"], entries):
        rule = entry["确定性规则"]
        for source in (deepcopy(spec), {}):
            source["确定性建模规则"] = deepcopy(rule)
            if rule["安装规则"]["基准"] == "floor":
                size, material = _model(source)
                assert size["width"] > 0
                color = rule["材质槽"][0]["base_color"]
                assert material["color"] == (color[0] if isinstance(color, list) else color)
            else:
                with pytest.raises(ValueError, match="落地"):
                    _model(source)
