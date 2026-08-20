"""用户长期装修画像服务：LLM 提取 + 增量合并，跨会话记忆用户偏好。

画像分两层：
- 关键维度（budget_min/max、preferred_styles）用列，便于确定性查询；
- 扩展维度放 profile_json，避免频繁迁移。

合并策略：新信息覆盖/追加，旧信息不冲突则保留（增量而非整体覆盖）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import UserProfile
from app.services import llm_service
from app.services.llm_service import LLMUnavailable

logger = logging.getLogger(__name__)

# profile_json 中需要按列表合并（而非覆盖）的字段
_LIST_KEYS = {"lifestyle", "renovation_goals", "constraints", "soft_preferences"}
_MAX_LIST_ITEMS = 8


def get_or_create_profile(db: Session, *, user_id: int) -> UserProfile:
    profile = db.scalars(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).first()
    if profile is None:
        profile = UserProfile(
            user_id=user_id,
            preferred_styles=[],
            profile_json={},
        )
        db.add(profile)
        db.flush()
    return profile


def _merge_list(existing: list, new: list) -> list:
    merged: list = []
    for item in list(new or []):
        if item not in merged:
            merged.append(item)
    for item in list(existing or []):
        if item not in merged and len(merged) < _MAX_LIST_ITEMS:
            merged.append(item)
    return merged


def merge_profile(profile: UserProfile, extracted: dict[str, Any]) -> None:
    """把 LLM 提取的画像增量合并进现有画像（就地修改，不提交事务）。"""
    if extracted.get("budget_min") is not None:
        try:
            profile.budget_min = int(extracted["budget_min"])
        except (TypeError, ValueError):
            pass
    if extracted.get("budget_max") is not None:
        try:
            profile.budget_max = int(extracted["budget_max"])
        except (TypeError, ValueError):
            pass

    if extracted.get("preferred_styles"):
        profile.preferred_styles = _merge_list(
            profile.preferred_styles or [],
            extracted["preferred_styles"],
        )

    facts = extracted.get("facts")
    if isinstance(facts, dict):
        existing_facts = profile.profile_json or {}
        for key, value in facts.items():
            if value in (None, [], "", {}):
                continue
            if key in _LIST_KEYS and isinstance(value, list):
                existing_facts[key] = _merge_list(
                    existing_facts.get(key) or [],
                    value,
                )
            else:
                existing_facts[key] = value
        profile.profile_json = existing_facts


def extract_and_merge(
    db: Session,
    *,
    user_id: int,
    text: str,
) -> UserProfile | None:
    """从文本提取画像并合并；LLM 不可用时返回 None（不阻断主流程）。"""
    if not text or not text.strip():
        return None
    try:
        extracted = llm_service.extract_profile(text)
    except LLMUnavailable:
        logger.warning("画像提取跳过（LLM 不可用）: user_id=%s", user_id)
        return None
    profile = get_or_create_profile(db, user_id=user_id)
    merge_profile(profile, extracted)
    db.commit()
    return profile


def build_profile_context(profile: UserProfile | None) -> str:
    """把画像转成给 LLM 的文本上下文；无画像时返回空字符串。"""
    if profile is None:
        return ""
    parts: list[str] = []
    if profile.budget_min or profile.budget_max:
        low = f"{profile.budget_min:,}" if profile.budget_min else "不限"
        high = f"{profile.budget_max:,}" if profile.budget_max else "不限"
        parts.append(f"预算 {low} - {high} 元")
    if profile.preferred_styles:
        parts.append("偏好风格 " + "、".join(profile.preferred_styles))
    facts = profile.profile_json or {}
    label_map = {
        "family_structure": "家庭结构",
        "lifestyle": "生活方式",
        "space_layout": "户型",
        "renovation_goals": "装修目标",
        "constraints": "硬性限制",
        "soft_preferences": "软性偏好",
    }
    for key, label in label_map.items():
        value = facts.get(key)
        if value:
            parts.append(f"{label} {json.dumps(value, ensure_ascii=False)}")
    if not parts:
        return ""
    return "业主画像：" + "；".join(parts)
