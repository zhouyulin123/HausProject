"""冻结时复核编译来源，不重新解释部件或假称精确几何碰撞。"""

from functools import lru_cache
import json
from pathlib import Path

from app.services.furniture_model_rules import (
    build_deterministic_rule_catalog,
    compile_furniture_family_rule,
    compile_lounge_chair_rule,
    compile_round_rect_coffee_table_rule,
)


@lru_cache(maxsize=1)
def _catalog_rules():
    # 兼容只有规则的既有商品，但仅准入可由随代码发布的原始目录重建的规则。
    path = Path(__file__).resolve().parents[2] / "furniture_3d_specs_40.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
        return {
            item["模型ID"]: item["确定性规则"]
            for item in build_deterministic_rule_catalog(catalog)["模型目录"]
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("家具编译来源目录不可用") from exc


def validate_product_compilation(spec, rule):
    """要求逐字段等于现有编译器产物，包围盒仍继承其概念级约定。"""
    try:
        if set(spec) == {"确定性建模规则"}:
            expected = _catalog_rules().get(rule["模型ID"])
            if expected is None:
                raise ValueError("规则没有可重建来源")
        elif rule["生成器"] == "lounge_chair_v1":
            expected = compile_lounge_chair_rule(spec)
        elif rule["生成器"] == "coffee_table_v1":
            expected = compile_round_rect_coffee_table_rule(spec)
        else:
            expected = compile_furniture_family_rule(spec, rule["模型ID"])
        # JSON 比较同时拒绝 bool 被 Python 的 True == 1 当成正常坐标。
        options = dict(sort_keys=True, ensure_ascii=False, allow_nan=False)
        if json.dumps(rule, **options) != json.dumps(expected, **options):
            raise ValueError("家具规则与原始参数编译结果不一致")
    except (TypeError, KeyError, OverflowError) as exc:
        raise ValueError("家具原始参数无法可靠重编译") from exc
