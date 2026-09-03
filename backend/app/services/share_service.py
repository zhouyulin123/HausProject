"""不可变方案分享快照、哈希 token 与统一失效查询。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    AnonymousSessionTask,
    DesignPlanVersion,
    DesignRevision,
    PlanShare,
)
from app.schemas.shares import PublicPlanSnapshot


_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_LOCAL_PATH_PATTERNS = (
    re.compile(r"file://\S+", re.IGNORECASE),
    re.compile(r"(?<![\w])(?:[A-Za-z]:[\\/]|\\\\)[^\s,;，；。]+"),
    re.compile(
        r"(?<![\w])/(?:home|users|var|tmp|etc|opt|root|mnt|media)"
        r"(?:/[^\s,;，；。]*)?",
        re.IGNORECASE,
    ),
)


def token_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _text(value: Any, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    for pattern in _LOCAL_PATH_PATTERNS:
        normalized = pattern.sub("[已隐藏本地路径]", normalized)
    return normalized[:limit] if normalized else None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return round(number) if number is not None else None


def _string_list(value: Any, *, limit: int = 30) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        normalized = _text(item, limit=300)
        if normalized:
            result.append(normalized)
    return result


def _dict_items(value: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value[:limit] if isinstance(item, dict)]


def _furniture_snapshot(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in _dict_items(plan.get("furnitureSuggestions")):
        name = _text(item.get("name"), limit=200)
        if not name:
            continue
        result.append(
            {
                "sku": _text(item.get("sku"), limit=100),
                "name": name,
                "category": _text(item.get("category"), limit=100),
                "room": _text(item.get("room"), limit=100),
                "style": _text(item.get("style"), limit=100),
                "material": _text(item.get("material"), limit=200),
                "price_range": _text(item.get("priceRange"), limit=100),
                "size": _text(item.get("sizeSuggestion"), limit=200),
                "reason": _text(item.get("reason"), limit=500),
                "alternative": _text(item.get("alternative"), limit=300),
                "quantity": _number(item.get("quantity")),
                "unit_price": _integer(item.get("unitPrice")),
                "subtotal": _integer(item.get("subtotal")),
            }
        )
    return result


def _colors_snapshot(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in _dict_items(plan.get("colorPalette"), limit=20):
        name = _text(item.get("name"), limit=100)
        color = _text(item.get("hex"), limit=20)
        if name and color and _HEX_COLOR.fullmatch(color):
            result.append(
                {
                    "name": name,
                    "hex": color.lower(),
                    "usage": _text(item.get("usage"), limit=200),
                }
            )
    return result


def _materials_snapshot(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in _dict_items(plan.get("materials"), limit=30):
        name = _text(item.get("name"), limit=100)
        if name:
            result.append(
                {
                    "name": name,
                    "description": _text(item.get("description"), limit=300),
                }
            )
    return result


def _lighting_snapshot(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in _dict_items(plan.get("lightingSuggestions"), limit=30):
        name = _text(item.get("name"), limit=100)
        if name:
            result.append(
                {
                    "name": name,
                    "purpose": _text(item.get("purpose"), limit=100),
                    "description": _text(item.get("description"), limit=300),
                }
            )
    return result


def _budget_snapshot(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in _dict_items(plan.get("budgetBreakdown"), limit=30):
        name = _text(item.get("name"), limit=100)
        if name:
            result.append(
                {
                    "name": name,
                    "percent": _number(item.get("percent")),
                    "amount": _integer(item.get("amount")),
                }
            )
    return result


def _quote_snapshot(plan_version: DesignPlanVersion) -> dict[str, Any] | None:
    quote_row = plan_version.quote_snapshot
    if quote_row is None:
        return None
    quote = quote_row.quote_json if isinstance(quote_row.quote_json, dict) else {}
    line_items = []
    for item in _dict_items(quote.get("lineItems")):
        sku = _text(item.get("sku"), limit=100)
        quantity = _number(item.get("quantity"))
        unit_price = _integer(item.get("unitPrice"))
        subtotal = _integer(item.get("subtotal"))
        if sku and quantity is not None and unit_price is not None:
            line_items.append(
                {
                    "sku": sku,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "subtotal": subtotal
                    if subtotal is not None
                    else round(quantity * unit_price),
                }
            )

    custom_lookup = {
        (
            _integer(item.get("subtotal")),
            _integer(item.get("unitPrice")),
        ): item
        for item in _dict_items(
            (plan_version.plan_json or {}).get("customItems")
            if isinstance(plan_version.plan_json, dict)
            else None
        )
    }
    custom_lines = []
    for item in _dict_items(quote.get("customLineItems")):
        quantity = _number(item.get("quantity"))
        unit_price = _integer(item.get("unitPrice"))
        subtotal = _integer(item.get("subtotal"))
        plan_item = custom_lookup.get((subtotal, unit_price), {})
        project = _text(plan_item.get("project"), limit=200)
        if project and quantity is not None and unit_price is not None:
            custom_lines.append(
                {
                    "project": project,
                    "grade": _text(plan_item.get("grade"), limit=100),
                    "unit": _text(plan_item.get("unit"), limit=50),
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "subtotal": subtotal
                    if subtotal is not None
                    else round(quantity * unit_price),
                }
            )
    return {
        "currency": _text(quote_row.currency, limit=10) or "CNY",
        "furniture_total": int(quote_row.furniture_total),
        "custom_total": int(quote_row.custom_total),
        "total": int(quote_row.grand_total),
        "line_items": line_items,
        "custom_line_items": custom_lines,
    }


def build_public_snapshot(plan_version: DesignPlanVersion) -> dict[str, Any]:
    plan = plan_version.plan_json if isinstance(plan_version.plan_json, dict) else {}
    snapshot = PublicPlanSnapshot(
        name=_text(plan.get("name"), limit=200) or plan_version.plan_name,
        style=_text(plan.get("style"), limit=100) or plan_version.style,
        description=_text(plan.get("description"), limit=2000),
        score=_number(plan.get("score")),
        budget=_integer(plan.get("budget")),
        tags=_string_list(plan.get("tags")),
        suitable_for=_string_list(plan.get("suitableFor")),
        layout_suggestions=_string_list(plan.get("layoutSuggestions")),
        ai_tips=_string_list(plan.get("aiTips")),
        furniture=_furniture_snapshot(plan),
        colors=_colors_snapshot(plan),
        materials=_materials_snapshot(plan),
        lighting=_lighting_snapshot(plan),
        budget_breakdown=_budget_snapshot(plan),
        quote=_quote_snapshot(plan_version),
    )
    return snapshot.model_dump(mode="json")


def _snapshot_digest(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{sha256(canonical).hexdigest()}"


def create_share(
    db: Session,
    *,
    plan_version: DesignPlanVersion,
    expires_in_hours: int,
) -> tuple[PlanShare, str]:
    snapshot = build_public_snapshot(plan_version)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
    for _ in range(3):
        token = secrets.token_urlsafe(32)
        share = PlanShare(
            plan_version_id=plan_version.id,
            token_digest=token_digest(token),
            snapshot_json=snapshot,
            snapshot_digest=_snapshot_digest(snapshot),
            expires_at=expires_at,
        )
        db.add(share)
        try:
            db.commit()
            db.refresh(share)
            return share, token
        except IntegrityError:
            db.rollback()
    raise RuntimeError("无法生成唯一分享凭证")


def get_available_share(
    db: Session, *, token: str, now: datetime | None = None
) -> PlanShare | None:
    current = now or datetime.now(timezone.utc)
    share = db.scalar(
        select(PlanShare).where(
            PlanShare.token_digest == token_digest(token),
            PlanShare.revoked_at.is_(None),
            PlanShare.expires_at > current,
        )
    )
    if share is None or not isinstance(share.snapshot_json, dict):
        return None
    if _snapshot_digest(share.snapshot_json) != share.snapshot_digest:
        return None
    try:
        PublicPlanSnapshot.model_validate(share.snapshot_json)
    except ValueError:
        return None
    return share


def revoke_owned_share(
    db: Session,
    *,
    token: str,
    session_id: str,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    share = db.scalar(
        select(PlanShare)
        .join(
            DesignPlanVersion,
            DesignPlanVersion.id == PlanShare.plan_version_id,
        )
        .join(DesignRevision, DesignRevision.id == DesignPlanVersion.revision_id)
        .join(
            AnonymousSessionTask,
            AnonymousSessionTask.task_id == DesignRevision.task_id,
        )
        .where(
            PlanShare.token_digest == token_digest(token),
            PlanShare.revoked_at.is_(None),
            PlanShare.expires_at > current,
            AnonymousSessionTask.session_id == session_id,
        )
        .with_for_update()
    )
    if share is None:
        return False
    share.revoked_at = current
    db.commit()
    return True
