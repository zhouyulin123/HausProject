"""商品商业事实变更、审核决定与追加式审计。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Product, ProductAuditEvent
from app.schemas.product_commercial import CommercialReviewRequest
from app.services.catalog_service import _product_eligibility_inputs
from app.services.product_eligibility import evaluate_product_eligibility


COMMERCIAL_EDIT_FIELDS = frozenset(
    {
        "sku",
        "name",
        "category",
        "room",
        "style",
        "material",
        "price",
        "price_max",
        "size",
        "selling_point",
        "alternative",
        "image_url",
        "data_origin",
        "source_name",
        "source_url",
        "source_product_id",
        "source_retrieved_at",
        "price_observed_at",
        "price_note",
        "source_metadata",
        "model_width_mm",
        "model_height_mm",
        "model_depth_mm",
        "model_license",
        "model_source",
        "availability_status",
        "stock_quantity",
        "region_codes",
        "lead_time_days_min",
        "lead_time_days_max",
        "price_valid_from",
        "price_valid_to",
        "data_version",
        "alternative_skus",
        "is_active",
    }
)
AUDITED_FIELDS = COMMERCIAL_EDIT_FIELDS | frozenset(
    {"verification_status", "verified_at", "verified_by", "record_version"}
)
_SUMMARY_ONLY_FIELDS = frozenset(
    {
        "selling_point",
        "alternative",
        "price_note",
        "model_license",
        "model_source",
    }
)
_URL_FIELDS = frozenset({"source_url", "image_url"})
_REQUEST_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
_LOCAL_PATH_PATTERN = re.compile(
    r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|var|tmp)/)",
    re.IGNORECASE,
)


class ProductCommercialNotFound(ValueError):
    pass


class ProductCommercialConflict(ValueError):
    def __init__(
        self,
        message: str,
        *,
        expected_record_version: int | None = None,
        current_record_version: int | None = None,
    ):
        super().__init__(message)
        self.expected_record_version = expected_record_version
        self.current_record_version = current_record_version


class ProductCommercialIdempotencyConflict(ProductCommercialConflict):
    pass


class ProductCommercialEvidenceIncomplete(ValueError):
    def __init__(self, reason_codes: tuple[str, ...]):
        super().__init__("商品商业核验事实不完整")
        self.reason_codes = reason_codes


def request_id_or_new(value: str | None, *, prefix: str = "product") -> str:
    normalized = (value or "").strip()
    if normalized:
        if len(normalized) > 100 or not _REQUEST_TOKEN_PATTERN.fullmatch(normalized):
            raise ProductCommercialConflict("X-Request-ID 格式无效")
        return normalized
    return f"{prefix}:{uuid4().hex}"


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if (
        len(normalized) < 8
        or len(normalized) > 100
        or not _REQUEST_TOKEN_PATTERN.fullmatch(normalized)
    ):
        raise ProductCommercialConflict("Idempotency-Key 格式无效")
    return normalized


def snapshot_product_fields(
    product: Product,
    fields: Iterable[str] = AUDITED_FIELDS,
) -> dict[str, Any]:
    return {field: getattr(product, field) for field in fields}


def _values_equal(before: Any, after: Any) -> bool:
    if isinstance(before, datetime) and isinstance(after, datetime):
        def normalized(value: datetime) -> datetime:
            if value.tzinfo is None:
                return value
            return value.astimezone(timezone.utc).replace(tzinfo=None)

        return normalized(before) == normalized(after)
    return before == after


def _text_summary(value: Any) -> dict[str, Any]:
    text = str(value).strip() if value is not None else ""
    return {
        "present": bool(text),
        "char_count": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
    }


def _safe_url(value: Any) -> Any:
    if value is None or not str(value).strip():
        return None
    parsed = urlsplit(str(value).strip())
    if not parsed.scheme or not parsed.hostname:
        return _text_summary(value)
    try:
        parsed_port = parsed.port
    except ValueError:
        return _text_summary(value)
    port = f":{parsed_port}" if parsed_port is not None else ""
    return urlunsplit((parsed.scheme, f"{parsed.hostname}{port}", parsed.path, "", ""))


def _audit_value(field: str, value: Any) -> Any:
    if field == "source_metadata":
        canonical = json.dumps(
            value if isinstance(value, dict) else {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return {
            "present": isinstance(value, dict) and bool(value),
            "entry_count": len(value) if isinstance(value, dict) else 0,
            "sha256": (
                hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                if isinstance(value, dict) and value
                else None
            ),
        }
    if field in _SUMMARY_ONLY_FIELDS:
        return _text_summary(value)
    if field in _URL_FIELDS:
        return _safe_url(value)
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat()
    if isinstance(value, (str, int, bool)) or value is None:
        if isinstance(value, str) and _LOCAL_PATH_PATTERN.match(value.strip()):
            return _text_summary(value)
        return value
    if isinstance(value, (list, tuple)):
        return [_audit_value(field, item) for item in value]
    return _text_summary(value)


def append_product_audit_event(
    db: Session,
    *,
    product: Product,
    event_type: str,
    actor: str,
    request_id: str,
    before: dict[str, Any],
    decision: str | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
    payload_hash: str | None = None,
) -> ProductAuditEvent:
    if (
        not actor
        or len(actor) > 100
        or not _REQUEST_TOKEN_PATTERN.fullmatch(actor)
    ):
        raise ProductCommercialConflict("审计 actor 格式无效")
    if (
        not request_id
        or len(request_id) > 100
        or not _REQUEST_TOKEN_PATTERN.fullmatch(request_id)
    ):
        raise ProductCommercialConflict("审计 request_id 格式无效")
    changes: dict[str, dict[str, Any]] = {}
    for field in sorted(AUDITED_FIELDS.intersection(before)):
        old_value = before[field]
        new_value = getattr(product, field)
        if not _values_equal(old_value, new_value):
            changes[field] = {
                "before": _audit_value(field, old_value),
                "after": _audit_value(field, new_value),
            }
    if note is not None:
        changes["review_note"] = {
            "before": None,
            "after": _text_summary(note),
        }
    event = ProductAuditEvent(
        product_id=product.id,
        event_type=event_type,
        actor=actor,
        request_id=request_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        changed_fields=list(changes),
        changes=changes,
        decision=decision,
        resulting_status=product.verification_status,
        resulting_record_version=product.record_version or 1,
    )
    db.add(event)
    db.flush()
    return event


def _review_payload_hash(payload: CommercialReviewRequest) -> str:
    encoded = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _operation_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _idempotent_event(
    db: Session,
    *,
    product_id: int,
    idempotency_key: str,
    payload_hash: str,
) -> ProductAuditEvent | None:
    event = db.scalar(
        select(ProductAuditEvent)
        .where(
            ProductAuditEvent.product_id == product_id,
            ProductAuditEvent.idempotency_key == idempotency_key,
        )
        .with_for_update()
    )
    if event is not None and event.payload_hash != payload_hash:
        raise ProductCommercialIdempotencyConflict(
            "Idempotency-Key 已用于不同的商品写请求"
        )
    return event


def review_product(
    db: Session,
    *,
    product_id: int,
    payload: CommercialReviewRequest,
    actor: str,
    request_id: str,
    idempotency_key: str,
) -> ProductAuditEvent:
    normalized_key = _idempotency_key(idempotency_key)
    digest = _review_payload_hash(payload)
    existing_event = _idempotent_event(
        db,
        product_id=product_id,
        idempotency_key=normalized_key,
        payload_hash=digest,
    )
    if existing_event is not None:
        return existing_event

    product = db.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise ProductCommercialNotFound("商品不存在")
    existing_event = _idempotent_event(
        db,
        product_id=product_id,
        idempotency_key=normalized_key,
        payload_hash=digest,
    )
    if existing_event is not None:
        return existing_event
    if payload.expected_record_version != product.record_version:
        raise ProductCommercialConflict(
            f"商品版本冲突：期望 {payload.expected_record_version}，"
            f"当前 {product.record_version}",
            expected_record_version=payload.expected_record_version,
            current_record_version=product.record_version,
        )

    before = snapshot_product_fields(product)
    now = datetime.now(timezone.utc)
    if payload.decision == "approve":
        prospective_origin = (
            "merchant_verified"
            if product.data_origin == "merchant_draft"
            else product.data_origin
        )
        region = next(
            (code for code in (product.region_codes or []) if code != "*"),
            None,
        )
        facts, policy = _product_eligibility_inputs(
            product,
            at=now,
            region=region,
            allow_draft=False,
            max_unit_price=None,
            max_dimensions_mm=None,
            required_quantity=None,
        )
        candidate = replace(
            facts,
            data_origin=prospective_origin,
            verification_status="verified",
            verified_at=now,
            verified_by=actor,
        )
        eligibility = evaluate_product_eligibility(candidate, policy)
        if not eligibility.eligible:
            raise ProductCommercialEvidenceIncomplete(eligibility.reason_codes)
        product.data_origin = prospective_origin
        product.verification_status = "verified"
        product.verified_at = now
        product.verified_by = actor
    else:
        product.verification_status = "rejected"
        product.verified_at = None
        product.verified_by = None
    product.record_version = (product.record_version or 1) + 1
    event = append_product_audit_event(
        db,
        product=product,
        event_type=f"commercial_review_{payload.decision}",
        actor=actor,
        request_id=request_id,
        before=before,
        decision=payload.decision,
        note=payload.note,
        idempotency_key=normalized_key,
        payload_hash=digest,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replay = _idempotent_event(
            db,
            product_id=product_id,
            idempotency_key=normalized_key,
            payload_hash=digest,
        )
        if replay is not None:
            return replay
        raise ProductCommercialConflict("商业审核并发冲突，请刷新后重试") from exc
    db.refresh(event)
    return event


def deactivate_product(
    db: Session,
    *,
    product_id: int,
    expected_record_version: int,
    actor: str,
    request_id: str,
    idempotency_key: str,
) -> ProductAuditEvent:
    normalized_key = _idempotency_key(idempotency_key)
    digest = _operation_payload_hash(
        {
            "operation": "deactivate",
            "expected_record_version": expected_record_version,
        }
    )
    existing_event = _idempotent_event(
        db,
        product_id=product_id,
        idempotency_key=normalized_key,
        payload_hash=digest,
    )
    if existing_event is not None:
        return existing_event

    product = db.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise ProductCommercialNotFound("商品不存在")
    existing_event = _idempotent_event(
        db,
        product_id=product_id,
        idempotency_key=normalized_key,
        payload_hash=digest,
    )
    if existing_event is not None:
        return existing_event
    if expected_record_version != product.record_version:
        raise ProductCommercialConflict(
            f"商品版本冲突：期望 {expected_record_version}，当前 {product.record_version}",
            expected_record_version=expected_record_version,
            current_record_version=product.record_version,
        )

    before = snapshot_product_fields(product)
    product.is_active = False
    product.verification_status = "draft"
    product.verified_at = None
    product.verified_by = None
    product.record_version = (product.record_version or 1) + 1
    event = append_product_audit_event(
        db,
        product=product,
        event_type="commercial_deactivate",
        actor=actor,
        request_id=request_id,
        before=before,
        idempotency_key=normalized_key,
        payload_hash=digest,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replay = _idempotent_event(
            db,
            product_id=product_id,
            idempotency_key=normalized_key,
            payload_hash=digest,
        )
        if replay is not None:
            return replay
        raise ProductCommercialConflict("商品停用并发冲突，请刷新后重试") from exc
    db.refresh(event)
    return event


def list_product_audit_events(
    db: Session,
    *,
    product_id: int,
    limit: int = 100,
) -> list[ProductAuditEvent]:
    if db.get(Product, product_id) is None:
        raise ProductCommercialNotFound("商品不存在")
    return list(
        db.scalars(
            select(ProductAuditEvent)
            .where(ProductAuditEvent.product_id == product_id)
            .order_by(ProductAuditEvent.id.desc())
            .limit(limit)
        ).all()
    )
