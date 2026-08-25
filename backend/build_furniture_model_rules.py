# -*- coding: utf-8 -*-
"""合并家具参数文件并生成确定性建模规则目录。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.furniture_model_rules import (
    build_deterministic_rule_catalog,
    merge_furniture_catalogs,
)


BACKEND_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated", type=Path, required=True, help="精选 20 款参数文件")
    parser.add_argument("--common", type=Path, required=True, help="常见 20 款参数文件")
    parser.add_argument(
        "--catalog-output",
        type=Path,
        default=BACKEND_DIR / "furniture_3d_specs_40.json",
    )
    parser.add_argument(
        "--rules-output",
        type=Path,
        default=BACKEND_DIR / "furniture_model_rules.json",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as file:
        return json.load(file)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    merged = merge_furniture_catalogs(
        [
            ("精选家具20款", load_json(args.curated)),
            ("常见家具20款", load_json(args.common)),
        ]
    )
    rules = build_deterministic_rule_catalog(merged)
    write_json(args.catalog_output, merged)
    write_json(args.rules_output, rules)
    print(
        f"OK: 合并 {merged['家具数量']} 款；"
        f"ready={rules['已完成规则数量']}，pending={rules['待完善规则数量']}"
    )


if __name__ == "__main__":
    main()
