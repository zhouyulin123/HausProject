"""从受信任来源冻结模型，不在重放或历史读取时重读来源。"""

from copy import deepcopy
from hashlib import sha256
import json

from sqlalchemy import select

from app.core.config import settings
from app.db.models import HomeDesignAsset, Product
from app.schemas.home_design import Material, ObjectSize
from app.schemas.home_design_asset import AssetResponse
from app.services.aggregate_lock_service import lock_owned_task
from app.services.furniture_model_rules import validate_deterministic_rule
from app.services.home_asset_validation import validate_product_compilation
from app.services.open_geometry_service import get_state, OpenGeometryError

MAX_MODEL_BYTES = 1_000_000
MAX_PARTS = 256
SUPPORTED_GENERATORS = {
    "lounge_chair_v1",
    "coffee_table_v1",
    "sofa_v2",
    "table_v2",
    "chair_v2",
    "bed_v2",
    "lamp_v2",
    "rug_v2",
    "curtain_v2",
    "cabinet_v2",
    "desk_v2",
    "shelf_v2",
    "ergonomic_chair_v2",
    "open_geometry_v1",
}


class AssetError(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.status = code, status
        super().__init__(message)


def _digest(value):
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _model(spec, *, validated_open=False):
    if not isinstance(spec, dict):
        raise ValueError("没有确定性模型")
    if (
        len(json.dumps(spec, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        > MAX_MODEL_BYTES
    ):
        raise ValueError("模型数据超过大小上限")
    rule = spec.get("确定性建模规则")
    if not isinstance(rule, dict) or rule.get("规则状态") != "ready":
        raise ValueError("模型规则尚未就绪")
    if rule.get("生成器") not in SUPPORTED_GENERATORS:
        raise ValueError("模型渲染器不受支持")
    for key in ("部件", "材质槽"):
        if (
            not isinstance(rule.get(key), list)
            or not rule[key]
            or any(not isinstance(item, dict) for item in rule[key])
        ):
            raise ValueError("模型部件或材质格式无效")
    coordinates = rule.get("坐标系统")
    if not isinstance(coordinates, dict) or any(
        coordinates.get(key) != value
        for key, value in {
            "单位": "mm",
            "上轴": "Y",
            "前向": "+Z",
            "原点": "floor_center",
        }.items()
    ):
        raise ValueError("模型坐标系不受支持")
    # 开放几何已由 get_state 对每个历史版本重新编译验证，其规则没有产品质量规则字段。
    if not validated_open:
        validate_deterministic_rule(rule)
        validate_product_compilation(spec, rule)
    if len(rule["部件"]) > MAX_PARTS:
        raise ValueError("模型部件超过上限")
    if rule["安装规则"]["基准"] != "floor":
        raise ValueError("当前只支持落地家具")
    dimensions = rule["包围尺寸_mm"]
    size = ObjectSize(
        width=dimensions["宽"] / 1000,
        height=dimensions["高"] / 1000,
        depth=dimensions["深"] / 1000,
    )
    slot = rule["材质槽"][0]
    color = slot.get("base_color")
    if isinstance(color, list):
        # 与确定性渲染器一致，首色仅作为清单代表色；完整调色板仍保留在模型中。
        color = color[0] if color else None
    material = Material(
        name=slot.get("材质") or slot.get("槽位ID"), color=color
    )
    return size.model_dump(), material.model_dump()


def _product_snapshot(product):
    if not product.is_active:
        raise ValueError("商品已停用")
    if product.data_origin == "development_fixture" and not (
        settings.app_env == "development" and settings.development_catalog_enabled
    ):
        raise ValueError("开发案例目录未启用")
    size, material = _model(product.model_spec_json)
    return dict(
        kind="product",
        source_id=product.id,
        source_version=product.record_version,
        name=product.name,
        size=size,
        material=material,
        model_spec=deepcopy(product.model_spec_json),
        source_summary={
            "sku": product.sku,
            "data_origin": product.data_origin,
            "data_version": product.data_version,
            "verification_status": product.verification_status,
        },
    )


def _open_snapshot(task):
    state = get_state(task)
    if state.current is None:
        raise ValueError("当前任务尚无开放几何作品")
    size, material = _model(state.current.model_spec, validated_open=True)
    return dict(
        kind="open_geometry",
        source_id=task.id,
        source_version=state.current_version,
        name=state.current.design.name,
        size=size,
        material=material,
        model_spec=deepcopy(state.current.model_spec),
        source_summary={"data_origin": "user_design", "verification_status": "concept"},
    )


def _option(kind, source_id, version, name, loader):
    result = dict(
        kind=kind,
        source_id=source_id,
        source_version=version,
        name=name,
        size=None,
        material=None,
        available=False,
        reason=None,
        source_summary={},
    )
    try:
        snapshot = loader()
        result.update(
            {
                k: snapshot[k]
                for k in (
                    "name",
                    "source_version",
                    "size",
                    "material",
                    "source_summary",
                )
            }
        )
        result["available"] = True
    except (ValueError, TypeError, KeyError, OpenGeometryError):
        result["reason"] = "该来源没有可用的落地确定性模型，或当前环境不允许使用"
    return result


def list_options(db, task, kind, after_id, limit):
    if kind == "open_geometry":
        items = (
            []
            if after_id is not None and task.id <= after_id
            else [
                _option(
                    kind, task.id, None, "当前家具作品", lambda: _open_snapshot(task)
                )
            ]
        )
        return dict(items=items, next_after_id=None)
    statement = select(Product).where(Product.is_active.is_(True))
    if after_id is not None:
        statement = statement.where(Product.id > after_id)
    rows = db.scalars(statement.order_by(Product.id).limit(limit + 1)).all()
    return dict(
        items=[
            _option(
                kind, p.id, p.record_version, p.name, lambda p=p: _product_snapshot(p)
            )
            for p in rows[:limit]
        ],
        next_after_id=rows[limit - 1].id if len(rows) > limit else None,
    )


def _response(row):
    try:
        if _digest(row.snapshot_json) != row.content_digest:
            raise ValueError("摘要不一致")
        return AssetResponse(
            id=row.id,
            task_id=row.task_id,
            content_digest=row.content_digest,
            **row.snapshot_json,
        )
    except (ValueError, TypeError) as exc:
        raise AssetError(
            "home_asset_corrupt", "家具快照损坏，请联系维护人员", 409
        ) from exc


def get_asset(db, task_id, asset_id):
    row = db.scalar(
        select(HomeDesignAsset).where(
            HomeDesignAsset.task_id == task_id, HomeDesignAsset.id == asset_id
        )
    )
    if row is None:
        raise AssetError("home_asset_not_found", "家具快照不存在或不属于当前任务", 404)
    return _response(row)


def create_asset(db, *, task_id, session_id, payload):
    task = lock_owned_task(db, session_id=session_id, task_id=task_id)
    if task is None:
        raise AssetError("home_asset_not_found", "设计任务不存在或不属于当前会话", 404)
    digest = _digest(payload.model_dump())
    replay = db.scalar(
        select(HomeDesignAsset)
        .where(
            HomeDesignAsset.task_id == task_id,
            HomeDesignAsset.client_mutation_id == payload.client_mutation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if replay:
        if replay.request_digest != digest:
            raise AssetError(
                "home_asset_idempotency_conflict", "请求标识已用于不同家具", 409
            )
        result = _response(replay)
        db.commit()
        return result
    # 使用当前读，不受鉴权查询先前建立的 MySQL 一致性快照影响。
    if (
        len(
            db.scalars(
                select(HomeDesignAsset.id)
                .where(HomeDesignAsset.task_id == task_id)
                .with_for_update()
            ).all()
        )
        >= 200
    ):
        raise AssetError("home_asset_limit", "本设计已达到 200 个家具快照上限", 409)
    try:
        if payload.kind == "product":
            product = db.scalar(
                select(Product)
                .where(Product.id == payload.source_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if product is None:
                raise ValueError("来源不存在")
            snapshot = _product_snapshot(product)
        else:
            if payload.source_id != task_id:
                raise ValueError("开放几何必须属于当前任务")
            snapshot = _open_snapshot(task)
    except (ValueError, TypeError, KeyError, OpenGeometryError) as exc:
        raise AssetError(
            "home_asset_unavailable", "来源不存在或没有可用的落地确定性模型"
        ) from exc
    if snapshot["source_version"] != payload.source_version:
        raise AssetError(
            "home_asset_source_changed", "来源版本已变化，请刷新家具列表", 409
        )
    row = HomeDesignAsset(
        task_id=task_id,
        client_mutation_id=payload.client_mutation_id,
        request_digest=digest,
        snapshot_json=snapshot,
        content_digest=_digest(snapshot),
    )
    db.add(row)
    db.flush()
    result = _response(row)
    db.commit()
    return result


def validate_bindings(db, task_id, document):
    assets = {}
    for item in document.objects:
        if item.asset_id is None:
            continue
        if item.asset_id not in assets:
            try:
                assets[item.asset_id] = get_asset(db, task_id, item.asset_id)
            except AssetError as exc:
                raise ValueError("家具快照不存在、损坏或不属于当前任务") from exc
        asset = assets[item.asset_id]
        if item.size != asset.size or item.material != asset.material:
            raise ValueError("绑定家具的尺寸与材质必须保持冻结值")
        if item.position.y != 0:
            raise ValueError("落地家具底面必须保持在地面")
        if item.installation is not None and item.installation.kind != "floor":
            raise ValueError("冻结落地家具不能改变安装方式")
    return assets
