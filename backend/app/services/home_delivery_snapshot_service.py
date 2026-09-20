"""不可变轻量交付与白名单公开投影，私有模型始终走原鉴权接口。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only
from app.db.models import (
    HomeDeliverySnapshot,
    HomeDeliveryConfirmation,
    HomeDeliveryShare,
)
from app.schemas.home_design import HomeDesignDocument
from app.schemas.spatial import SpatialDocument
from app.schemas.home_delivery_snapshot import DeliverySummary, PublicSnapshot
from app.services.aggregate_lock_service import lock_owned_task
from app.services.home_design_delivery import get_delivery
from app.services.home_quote_service import read_quote

MAX_BYTES = 5 * 1024 * 1024


class DeliveryError(ValueError):
    pass


def _utc(value):
    # MySQL/SQLite 的 DateTime 列按项目约定存 UTC，但读取时不保留 tzinfo。
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def checked_size(value):
    if len(canonical(value)) > MAX_BYTES:
        raise DeliveryError("交付快照超过 5MB 上限")
    return value


def _lock(db, task_id, session_id):
    if lock_owned_task(db, task_id=task_id, session_id=session_id) is None:
        raise LookupError("设计任务不存在")


def _replay(db, model, task_id, key, request_digest):
    row = db.scalar(
        select(model)
        .where(model.task_id == task_id, model.client_mutation_id == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row and row.request_digest != request_digest:
        raise DeliveryError("同一请求标识不能用于不同内容")
    return row


def _quota(db, model, task_id, limit):
    if (
        len(
            db.scalars(
                select(model.id).where(model.task_id == task_id).with_for_update()
            ).all()
        )
        >= limit
    ):
        raise DeliveryError("当前任务记录数量已达到上限")


def delivery_response(row):
    value = row.snapshot_json
    try:
        if (
            not isinstance(value, dict)
            or digest(value) != row.content_digest
            or value["schema_version"] != "home-delivery-snapshot/1.0"
        ):
            raise ValueError()
        if (value["task_id"], value["home_version"], value["space_version"]) != (
            row.task_id,
            row.home_version,
            row.space_version,
        ):
            raise ValueError()
        document = HomeDesignDocument.model_validate(value["document"])
        SpatialDocument.model_validate(value["space"])
        if document.space_version != row.space_version:
            raise ValueError()
    except (ValueError, TypeError, KeyError) as exc:
        raise DeliveryError("交付快照损坏") from exc
    return dict(
        id=row.id,
        task_id=row.task_id,
        home_version=row.home_version,
        space_version=row.space_version,
        quote_id=row.quote_id,
        content_digest=row.content_digest,
        created_at=_utc(row.created_at),
        snapshot=value,
    )


def delivery_summary_response(row):
    return DeliverySummary.model_validate(
        {
            key: _utc(getattr(row, key)) if key == "created_at" else getattr(row, key)
            for key in (
                "id",
                "task_id",
                "home_version",
                "space_version",
                "quote_id",
                "content_digest",
                "created_at",
            )
        }
    )


def page_deliveries(db, task_id, before, limit, home_version=None):
    query = (
        select(HomeDeliverySnapshot)
        .options(
            load_only(
                HomeDeliverySnapshot.id,
                HomeDeliverySnapshot.task_id,
                HomeDeliverySnapshot.home_version,
                HomeDeliverySnapshot.space_version,
                HomeDeliverySnapshot.quote_id,
                HomeDeliverySnapshot.content_digest,
                HomeDeliverySnapshot.created_at,
            )
        )
        .where(HomeDeliverySnapshot.task_id == task_id)
    )
    if home_version is not None:
        query = query.where(HomeDeliverySnapshot.home_version == home_version)
    if before is not None:
        query = query.where(HomeDeliverySnapshot.id < before)
    rows = db.scalars(
        query.order_by(HomeDeliverySnapshot.id.desc()).limit(limit + 1)
    ).all()
    return dict(
        items=[delivery_summary_response(row) for row in rows[:limit]],
        next_before_id=rows[limit - 1].id if len(rows) > limit else None,
    )


def read_delivery(db, task_id, identifier):
    row = db.scalar(
        select(HomeDeliverySnapshot).where(
            HomeDeliverySnapshot.task_id == task_id,
            HomeDeliverySnapshot.id == identifier,
        )
    )
    if row is None:
        raise LookupError("交付快照不存在")
    return delivery_response(row)


def create_delivery(db, task_id, session_id, payload):
    _lock(db, task_id, session_id)
    request_digest = digest(payload.model_dump())
    row = _replay(
        db, HomeDeliverySnapshot, task_id, payload.client_mutation_id, request_digest
    )
    if row:
        result = delivery_response(row)
        db.commit()
        return result
    _quota(db, HomeDeliverySnapshot, task_id, 100)
    original = get_delivery(db, task_id, payload.home_version)
    quote = None
    if payload.quote_id is not None:
        response = read_quote(db, task_id, payload.quote_id)
        quote = response["snapshot"]
        if (
            response["home_version"] != payload.home_version
            or quote["space_version"] != original["space_version"]
            or quote["delivery_digest"] != original["content_digest"]
        ):
            raise DeliveryError("估价不属于当前精确交付版本")
    snapshot = {
        key: deepcopy(original[key])
        for key in (
            "task_id",
            "home_version",
            "space_version",
            "document",
            "space",
            "lines",
            "validation",
            "gaps",
            "limitations",
        )
    }
    snapshot.update(
        schema_version="home-delivery-snapshot/1.0",
        original_delivery_digest=original["content_digest"],
        quote=quote,
    )
    snapshot["assets"] = [
        {
            key: asset[key]
            for key in (
                "id",
                "content_digest",
                "kind",
                "source_id",
                "source_version",
                "name",
            )
        }
        for asset in original["assets"]
    ]
    # 行项目不重复保存资产来源及模型，仅保留资产 ID 与摘要。
    for line in snapshot["lines"]:
        asset = line.get("asset")
        if asset:
            line["asset"] = {key: asset[key] for key in ("id", "content_digest")}
    checked_size(snapshot)
    row = HomeDeliverySnapshot(
        task_id=task_id,
        home_version=payload.home_version,
        space_version=original["space_version"],
        quote_id=payload.quote_id,
        client_mutation_id=payload.client_mutation_id,
        request_digest=request_digest,
        snapshot_json=snapshot,
        content_digest=digest(snapshot),
    )
    db.add(row)
    db.flush()
    result = delivery_response(row)
    db.commit()
    return result


def page(db, model, task_id, before, limit, transform, **filters):
    query = select(model).where(model.task_id == task_id)
    for key, value in filters.items():
        if value is not None:
            query = query.where(getattr(model, key) == value)
    if before is not None:
        query = query.where(model.id < before)
    rows = db.scalars(query.order_by(model.id.desc()).limit(limit + 1)).all()
    return dict(
        items=[transform(row) for row in rows[:limit]],
        next_before_id=rows[limit - 1].id if len(rows) > limit else None,
    )


def confirmation_response(row):
    return {
        key: _utc(getattr(row, key)) if key == "created_at" else getattr(row, key)
        for key in (
            "id",
            "delivery_id",
            "snapshot_digest",
            "decision",
            "note",
            "created_at",
        )
    }


def confirm(db, task_id, session_id, delivery_id, payload):
    _lock(db, task_id, session_id)
    request_digest = digest(dict(delivery_id=delivery_id, **payload.model_dump()))
    row = _replay(
        db,
        HomeDeliveryConfirmation,
        task_id,
        payload.client_mutation_id,
        request_digest,
    )
    if row:
        result = confirmation_response(row)
        db.commit()
        return result
    delivery = read_delivery(db, task_id, delivery_id)
    if delivery["content_digest"] != payload.snapshot_digest:
        raise DeliveryError("审阅的快照摘要不匹配")
    _quota(db, HomeDeliveryConfirmation, task_id, 500)
    row = HomeDeliveryConfirmation(
        task_id=task_id,
        delivery_id=delivery_id,
        actor_session_id=session_id,
        request_digest=request_digest,
        **payload.model_dump(),
    )
    db.add(row)
    db.flush()
    result = confirmation_response(row)
    db.commit()
    return result


def public_projection(snapshot):
    document = deepcopy(snapshot["document"])
    for item in document["objects"]:
        item.pop("asset_id", None)
    for surface in document["surfaces"]:
        surface.pop("quote_rule_id", None)
    space = {
        key: deepcopy(snapshot["space"][key])
        for key in (
            "schema_version",
            "unit",
            "scale_status",
            "rooms",
            "walls",
            "openings",
        )
    }
    line_fields = (
        "entity_type",
        "id",
        "room_id",
        "room_name",
        "name",
        "material",
        "unit",
        "quantity",
        "quantity_status",
        "unit_price",
        "total_price",
        "price_status",
    )
    lines = [
        {key: deepcopy(line[key]) for key in line_fields if key in line}
        for line in snapshot["lines"]
    ]
    quote = snapshot.get("quote")
    if quote:
        quote = {
            key: deepcopy(quote[key])
            for key in (
                "currency",
                "known_subtotal",
                "pending_count",
                "total_price",
                "created_at",
                "limitations",
            )
        }
        quote["lines"] = [
            {
                key: deepcopy(line[key])
                for key in (
                    "entity_type",
                    "id",
                    "room_id",
                    "room_name",
                    "name",
                    "unit",
                    "quantity",
                    "unit_price",
                    "total_price",
                    "price_status",
                )
                if key in line
            }
            for line in snapshot["quote"]["lines"]
        ]
    return dict(
        schema_version="public-home-delivery/1.0",
        home_version=snapshot["home_version"],
        space_version=snapshot["space_version"],
        document=document,
        space=space,
        lines=lines,
        validation=deepcopy(snapshot["validation"]),
        gaps=deepcopy(snapshot["gaps"]),
        limitations=deepcopy(snapshot["limitations"])
        + ["链接接收者可查看户型和自行填写的名称；不含原图及私有家具模型。"],
        quote=quote,
    )


def share_response(row, token=None, replayed=False):
    return dict(
        id=row.id,
        delivery_id=row.delivery_id,
        expires_at=_utc(row.expires_at),
        revoked_at=_utc(row.revoked_at),
        token=token,
        share_url=f"/home-share/{token}" if token else None,
        replayed=replayed,
    )


def create_share(db, task_id, session_id, delivery_id, payload):
    _lock(db, task_id, session_id)
    request_digest = digest(dict(delivery_id=delivery_id, **payload.model_dump()))
    row = _replay(
        db, HomeDeliveryShare, task_id, payload.client_mutation_id, request_digest
    )
    if row:
        result = share_response(row, replayed=True)
        db.commit()
        return result
    snapshot = read_delivery(db, task_id, delivery_id)["snapshot"]
    _quota(db, HomeDeliveryShare, task_id, 100)
    public = checked_size(public_projection(snapshot))
    PublicSnapshot.model_validate(public)
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=payload.expires_in_hours
    )
    for _ in range(3):
        token = secrets.token_urlsafe(32)
        row = HomeDeliveryShare(
            task_id=task_id,
            delivery_id=delivery_id,
            client_mutation_id=payload.client_mutation_id,
            request_digest=request_digest,
            consent_json=dict(
                consent_public=True,
                include_private_models=False,
                include_source_image=False,
                disclosure_version="home-share-consent/1.0",
            ),
            token_digest=sha256(token.encode()).hexdigest(),
            snapshot_json=public,
            content_digest=digest(public),
            expires_at=expires_at,
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            continue
        result = share_response(row, token)
        db.commit()
        return result
    db.rollback()
    raise DeliveryError("无法生成唯一分享凭证")


def revoke(db, task_id, session_id, share_id):
    _lock(db, task_id, session_id)
    row = db.scalar(
        select(HomeDeliveryShare)
        .where(HomeDeliveryShare.task_id == task_id, HomeDeliveryShare.id == share_id)
        .with_for_update()
    )
    if row is None:
        raise LookupError("分享不存在")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return dict(id=share_id, status="revoked")


def public_share(db, token):
    if len(token) != 43:
        raise LookupError("分享不存在或已失效")
    row = db.scalar(
        select(HomeDeliveryShare).where(
            HomeDeliveryShare.token_digest == sha256(token.encode()).hexdigest(),
            HomeDeliveryShare.revoked_at.is_(None),
            HomeDeliveryShare.expires_at > datetime.now(timezone.utc),
        )
    )
    if row is None:
        raise LookupError("分享不存在或已失效")
    try:
        if digest(row.snapshot_json) != row.content_digest:
            raise ValueError()
        PublicSnapshot.model_validate(row.snapshot_json)
        # 重投影校验公开字段集合，拒绝损坏快照携带额外私有字段。
        source = {**row.snapshot_json, "assets": []}
        reprojection = public_projection(source)
        reprojection["limitations"] = row.snapshot_json["limitations"]
        if reprojection != row.snapshot_json:
            raise ValueError()
        HomeDesignDocument.model_validate(row.snapshot_json["document"])
        SpatialDocument.model_validate(row.snapshot_json["space"])
    except (ValueError, TypeError, KeyError) as exc:
        raise LookupError("分享不存在或已失效") from exc
    return dict(expires_at=_utc(row.expires_at), snapshot=row.snapshot_json)
