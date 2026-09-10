"""读取 Skill 与运行时共用的开放几何契约。"""

from functools import lru_cache
import json
from pathlib import Path
from typing import Any


CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "shared"
    / "furniture_open_geometry_contract.json"
)
SKILL_PATH = Path(__file__).resolve().parents[3] / "skills" / "furniture-open-geometry" / "SKILL.md"


@lru_cache(maxsize=1)
def open_geometry_contract() -> dict[str, Any]:
    with CONTRACT_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def contract_limit(name: str) -> int | float:
    value = open_geometry_contract()["limits"][name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"开放几何限制 {name} 必须是数值")
    return value


@lru_cache(maxsize=1)
def open_geometry_skill_prompt() -> str:
    """运行时直接消费版本化 Skill 指令，避免产品 Prompt 与 Skill 漂移。"""
    return SKILL_PATH.read_text(encoding="utf-8")
