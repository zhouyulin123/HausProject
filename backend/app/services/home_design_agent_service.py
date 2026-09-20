"""整屋建议的白名单执行与隔离模型调用。"""

from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json

from sqlalchemy import select

from app.core.config import settings
from app.db.models import (
    HomeDesignAgentTurn,
    HomeDesignAsset,
    HomeDesign,
    HomeDesignVersion,
    DesignSpaceVersion,
    Product,
)
from app.schemas.home_design import HomeDesignDocument
from app.schemas.home_design_agent import (
    HomeAgentBudgetPreview,
    HomeAgentEvidence,
    HomeDesignAgentPlan,
    HomeDesignAgentRequest,
    HomeDesignAgentResponse,
)
from app.schemas.spatial import SpatialDocument
from app.services import (
    aggregate_lock_service,
    generation_constraints_service,
    llm_service,
    model_call_governance_service,
    task_timeline_service,
)
from app.services.home_design_validation import validate_design
from app.services.home_design_asset_service import (
    AssetError,
    get_asset,
    validate_bindings,
)
from app.services.home_design_delivery import build_delivery
from app.services.home_quote_service import preview_delivery
from app.services.open_geometry_rate_limit import (
    open_geometry_rate_limiter,
    OpenGeometryRateLimitError,
)


ERRORS = {
    "home_agent_running": (409, "建议正在生成，请稍后刷新"),
    "home_agent_idempotency_conflict": (409, "本轮标识已经用于不同请求"),
    "home_agent_version_conflict": (409, "设计版本已改变，请基于最新版本重新提问"),
    "home_agent_design_required": (409, "请先保存整屋设计，再获取 AI 建议"),
    "home_agent_expired": (409, "本轮调用未完成且已过期，请新建一轮请求"),
    "home_agent_rate_limited": (429, "请求较多，请稍后重试"),
    "home_agent_unavailable": (503, "模型服务暂不可用，本轮未生成建议"),
    "home_agent_scope_lost": (404, "设计任务不存在或不属于当前会话"),
    "home_agent_state_invalid": (409, "已保存数据不完整，请恢复有效版本后再试"),
    "home_agent_asset_invalid": (422, "选择的家具快照不存在、损坏或不属于当前任务"),
}


class HomeAgentError(Exception):
    def __init__(self, code, retry_after=None):
        self.code = code
        self.retry_after = retry_after
        self.status_code, self.message = ERRORS[code]
        super().__init__(self.message)


def _locked_turn(db, task_id, client_turn_id):
    return db.scalar(
        select(HomeDesignAgentTurn)
        .where(
            HomeDesignAgentTurn.task_id == task_id,
            HomeDesignAgentTurn.client_turn_id == client_turn_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _current_document(db, task_id, payload):
    current = db.scalar(
        select(HomeDesign)
        .where(HomeDesign.task_id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None:
        raise HomeAgentError("home_agent_design_required")
    if current.current_version != payload.base_version:
        raise HomeAgentError("home_agent_version_conflict")
    version = db.scalar(
        select(HomeDesignVersion)
        .where(
            HomeDesignVersion.task_id == task_id,
            HomeDesignVersion.version == payload.base_version,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if version is None:
        raise HomeAgentError("home_agent_state_invalid")
    document = _validated(HomeDesignDocument, version.document_json)
    if document.space_version != payload.space_version:
        raise HomeAgentError("home_agent_version_conflict")
    return document


def _validated(schema, value):
    try:
        return schema.model_validate(value)
    except (ValueError, TypeError) as exc:
        raise HomeAgentError("home_agent_state_invalid") from exc


def _load_assets(db, task_id, asset_ids):
    assets = {}
    try:
        identifiers = sorted(set(asset_ids))
        if identifiers:
            locked = db.scalars(
                select(HomeDesignAsset.id)
                .where(
                    HomeDesignAsset.task_id == task_id,
                    HomeDesignAsset.id.in_(identifiers),
                )
                .order_by(HomeDesignAsset.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
            if locked != identifiers:
                raise AssetError("home_asset_not_found", "家具快照不存在", 404)
        for asset_id in identifiers:
            assets[asset_id] = get_asset(db, task_id, asset_id)
    except AssetError as exc:
        raise HomeAgentError("home_agent_asset_invalid") from exc
    return assets


def _asset_fact(asset):
    return {
        "asset_id": asset.id,
        "kind": asset.kind,
        "name": asset.name,
        "size": asset.size.model_dump(mode="json"),
        "material": asset.material.model_dump(mode="json"),
        "source_id": asset.source_id,
        "source_version": asset.source_version,
        "content_digest": asset.content_digest,
    }


def _asset_fingerprint(db, assets):
    product_ids = sorted(
        {asset.source_id for asset in assets.values() if asset.kind == "product"}
    )
    products = {
        product.id: product
        for product in db.scalars(
            select(Product)
            .where(Product.id.in_(product_ids))
            .order_by(Product.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    }
    facts = []
    for asset in sorted(assets.values(), key=lambda value: value.id):
        product = products.get(asset.source_id) if asset.kind == "product" else None
        facts.append(
            {
                **_asset_fact(asset),
                "pricing": None
                if product is None
                else {
                    key: getattr(product, key)
                    for key in (
                        "record_version",
                        "is_active",
                        "price",
                        "price_max",
                        "verification_status",
                        "availability_status",
                        "stock_quantity",
                        "region_codes",
                        "price_valid_from",
                        "price_valid_to",
                        "data_origin",
                    )
                },
            }
        )
    return sha256(
        json.dumps(
            facts,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _evidence(assets):
    return {
        "schema_version": "home-agent-evidence/1.0",
        "asset_refs": [
            {
                "asset_id": asset.id,
                "content_digest": asset.content_digest,
                "source_id": asset.source_id,
                "source_version": asset.source_version,
            }
            for asset in sorted(assets.values(), key=lambda value: value.id)
        ],
        "rule_version": "catalog-eligibility/home-agent-budget/1.0",
    }


def _candidate_facts(db, *, task_id, version, document, space, region, budget_max):
    try:
        assets = validate_bindings(db, task_id, document)
    except ValueError as exc:
        raise ValueError("候选家具绑定无效") from exc
    delivery = build_delivery(
        task_id=task_id,
        version=version,
        document=document,
        space=space,
        assets={
            identifier: asset.model_dump(mode="json")
            for identifier, asset in assets.items()
        },
    )
    return _evidence(assets), preview_delivery(
        db, delivery, region=region, budget_max=budget_max
    )


def _empty_budget(payload):
    return HomeAgentBudgetPreview(
        region=payload.region,
        budget_max=payload.budget_max,
        limitations=["尚无通过确定性校验的候选，未计算价格。"],
    )


def _expired(row):
    created = (
        row.created_at.replace(tzinfo=timezone.utc)
        if row.created_at.tzinfo is None
        else row.created_at
    )
    return datetime.now(timezone.utc) - created >= timedelta(minutes=10)


def _checked_response(row):
    request = _validated(HomeDesignAgentRequest, row.request_json)
    if request.client_turn_id != row.client_turn_id:
        raise HomeAgentError("home_agent_state_invalid")
    response = _validated(HomeDesignAgentResponse, row.response_json)
    if (
        response.turn_id != row.id
        or response.base_version != request.base_version
        or response.space_version != request.space_version
    ):
        raise HomeAgentError("home_agent_state_invalid")
    return response


def _replay(db, row, digest):
    if row.request_digest != digest:
        raise HomeAgentError("home_agent_idempotency_conflict")
    if row.status == "running":
        if _expired(row):
            row.status, row.error_code = "failed", "home_agent_expired"
            row.completed_at = datetime.now(timezone.utc)
            db.commit()
            raise HomeAgentError(row.error_code)
        raise HomeAgentError("home_agent_running")
    if row.status == "failed":
        raise HomeAgentError(
            row.error_code if row.error_code in ERRORS else "home_agent_state_invalid",
            row.retry_after_seconds,
        )
    if row.status != "completed":
        raise HomeAgentError("home_agent_state_invalid")
    response = _checked_response(row)
    db.commit()
    return response


def create_turn(db, *, task_id, session_id, payload):
    task = aggregate_lock_service.lock_owned_task(
        db, session_id=session_id, task_id=task_id
    )
    if task is None:
        raise HomeAgentError("home_agent_scope_lost")
    request = payload.model_dump(mode="json")
    digest = sha256(
        json.dumps(
            request, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    existing = _locked_turn(db, task_id, payload.client_turn_id)
    if existing:
        return _replay(db, existing, digest)
    document = _current_document(db, task_id, payload)
    source = db.scalar(
        select(DesignSpaceVersion)
        .where(
            DesignSpaceVersion.task_id == task_id,
            DesignSpaceVersion.version == payload.space_version,
        )
        .with_for_update()
    )
    if source is None:
        raise HomeAgentError("home_agent_version_conflict")
    space = _validated(SpatialDocument, source.document_json)
    try:
        current_assets = validate_bindings(db, task_id, document)
    except ValueError as exc:
        raise HomeAgentError("home_agent_state_invalid") from exc
    allowed_assets = _load_assets(db, task_id, payload.allowed_asset_ids)
    scoped_assets = _load_assets(
        db, task_id, set(current_assets) | set(allowed_assets)
    )
    asset_fingerprint = _asset_fingerprint(db, scoped_assets)
    recent = db.scalars(
        select(HomeDesignAgentTurn)
        .where(
            HomeDesignAgentTurn.task_id == task_id,
            HomeDesignAgentTurn.status == "completed",
        )
        .order_by(HomeDesignAgentTurn.id.desc())
        .limit(6)
        .with_for_update()
    ).all()
    for previous in recent:
        _checked_response(previous)
    history = [
        {
            "message": r.request_json["message"],
            "response": {
                "outcome": r.response_json["outcome"],
                "message": r.response_json["message"],
                "base_version": r.response_json["base_version"],
                "space_version": r.response_json["space_version"],
            },
        }
        for r in reversed(recent)
    ]
    row = HomeDesignAgentTurn(
        task_id=task_id,
        client_turn_id=payload.client_turn_id,
        request_digest=digest,
        request_json=request,
        status="running",
    )
    db.add(row)
    db.flush()
    turn_id = row.id
    # 调用预留提交后，不再持有任务锁；成本治理使用独立事务。
    db.commit()
    error_code = None
    retry_after = None
    response = None
    with llm_service.capture_model_call() as capture:
        try:
            wait = open_geometry_rate_limiter.retry_after(
                db, session_id=session_id, task_id=task_id
            )
            db.rollback()
            if wait is not None:
                raise HomeAgentError("home_agent_rate_limited", wait)
            with model_call_governance_service.govern_task_model_calls(
                db,
                task_id=task_id,
                operation_key=f"home-design-agent:{payload.client_turn_id}",
            ):
                raw = llm_service.plan_home_design(
                    instruction=payload.message,
                    context={
                        "document": document.model_dump(mode="json"),
                        "space": space.model_dump(mode="json"),
                        "history": history,
                        "confirmed_requirements": (
                            generation_constraints_service.normalize_requirement_facts(
                                task.confirmed_requirement_json or {}
                            )
                        ),
                        "current_asset_facts": [
                            _asset_fact(asset)
                            for asset in sorted(
                                current_assets.values(), key=lambda value: value.id
                            )
                        ],
                        "available_assets": [
                            _asset_fact(asset)
                            for asset in sorted(
                                allowed_assets.values(), key=lambda value: value.id
                            )
                        ],
                        "budget": {
                            "region": payload.region,
                            "budget_max": payload.budget_max,
                            "currency": "CNY",
                            "note": "价格仅由服务端在候选校验后计算",
                        },
                    },
                )
            plan = HomeDesignAgentPlan.model_validate(raw)
            response = HomeDesignAgentResponse(
                turn_id=turn_id,
                outcome="invalid" if plan.outcome == "proposal" else plan.outcome,
                message=plan.message,
                base_version=payload.base_version,
                space_version=payload.space_version,
                budget_preview=_empty_budget(payload),
            )
            if plan.outcome == "proposal":
                candidate = apply_plan(
                    document, plan, allowed_assets=allowed_assets
                )
                validation = validate_design(candidate, space)
                response.validation = validation
                if validation.valid:
                    evidence, budget_preview = _candidate_facts(
                        db,
                        task_id=task_id,
                        version=payload.base_version,
                        document=candidate,
                        space=space,
                        region=payload.region,
                        budget_max=payload.budget_max,
                    )
                    response.candidate_document = candidate
                    response.outcome = "proposal"
                    response.message = "已生成待确认的设计候选，尚未保存"
                    response.evidence = HomeAgentEvidence.model_validate(evidence)
                    response.budget_preview = HomeAgentBudgetPreview.model_validate(
                        budget_preview
                    )
                else:
                    response.outcome, response.message = (
                        "invalid",
                        "建议未通过几何校验，请调整要求后重试",
                    )
        except HomeAgentError as exc:
            error_code = exc.code
            retry_after = exc.retry_after
        except ValueError:
            response = HomeDesignAgentResponse(
                turn_id=turn_id,
                outcome="invalid",
                message="模型建议未通过结构或引用校验，现有设计保持不变",
                base_version=payload.base_version,
                space_version=payload.space_version,
                budget_preview=_empty_budget(payload),
            )
        except (llm_service.LLMUnavailable, OpenGeometryRateLimitError):
            error_code = "home_agent_unavailable"
        except Exception:
            # 未知服务错误也必须关闭预留，不能留下可被误认为成功的结果。
            error_code = "home_agent_unavailable"
    db.rollback()
    owned = aggregate_lock_service.lock_owned_task(
        db, session_id=session_id, task_id=task_id
    )
    row = _locked_turn(db, task_id, payload.client_turn_id)
    if row is None:
        raise HomeAgentError("home_agent_scope_lost")
    if row.status != "running":
        return _replay(db, row, digest)
    if owned is None:
        error_code = "home_agent_scope_lost"
    elif _expired(row):
        error_code = "home_agent_expired"
    elif error_code is None:
        try:
            _current_document(db, task_id, payload)
            refreshed_assets = _load_assets(db, task_id, scoped_assets)
            if _asset_fingerprint(db, refreshed_assets) != asset_fingerprint:
                raise HomeAgentError("home_agent_version_conflict")
        except HomeAgentError as exc:
            error_code = exc.code
    row.status = "failed" if error_code else "completed"
    row.error_code = error_code
    row.retry_after_seconds = retry_after
    row.response_json = (
        None
        if error_code
        else HomeDesignAgentResponse.model_validate(response.model_dump()).model_dump(
            mode="json"
        )
    )
    row.completed_at = datetime.now(timezone.utc)
    billing, cost = task_timeline_service.billing_for_model_call(
        attempted=capture.attempted,
        usage=capture.usage,
        input_price_per_mtok=settings.llm_input_price_per_mtok,
        output_price_per_mtok=settings.llm_output_price_per_mtok,
    )
    task_timeline_service.append_event(
        db,
        task_id=task_id,
        source_type="agent",
        source_id=turn_id,
        attempt=1 if capture.attempted else None,
        event_code="agent.home_design.failed"
        if error_code or response.outcome == "invalid"
        else "agent.home_design.completed",
        billing_status=billing,
        cost_cny=cost,
        event_key=f"home-design-agent:{turn_id}:finished",
    )
    db.commit()
    if error_code:
        raise HomeAgentError(error_code, retry_after)
    return response


def history(db, *, task_id, before_id, limit):
    statement = select(HomeDesignAgentTurn).where(
        HomeDesignAgentTurn.task_id == task_id
    )
    if before_id is not None:
        statement = statement.where(HomeDesignAgentTurn.id < before_id)
    rows = db.scalars(
        statement.order_by(HomeDesignAgentTurn.id.desc()).limit(limit + 1)
    ).all()
    for row in rows[:limit]:
        _validated(HomeDesignAgentRequest, row.request_json)
        if row.status not in {"running", "completed", "failed"}:
            raise HomeAgentError("home_agent_state_invalid")
        if row.status == "completed":
            _checked_response(row)
    return {
        "task_id": task_id,
        "turns": [
            {
                "turn_id": r.id,
                "client_turn_id": r.client_turn_id,
                "message": r.request_json["message"],
                "base_version": r.request_json["base_version"],
                "space_version": r.request_json["space_version"],
                "status": "failed"
                if r.status == "running" and _expired(r)
                else r.status,
                "response": r.response_json if r.status == "completed" else None,
                "error_code": "home_agent_expired"
                if r.status == "running" and _expired(r)
                else r.error_code,
                "created_at": r.created_at,
            }
            for r in rows[:limit]
        ],
        "next_before_id": rows[limit - 1].id if len(rows) > limit else None,
    }


def apply_plan(
    document: HomeDesignDocument,
    plan: HomeDesignAgentPlan,
    *,
    allowed_assets=None,
) -> HomeDesignDocument:
    allowed_assets = allowed_assets or {}
    result = document.model_dump(mode="json")
    touched = set()
    for operation in plan.operations:
        kind = "objects" if operation.type.endswith("object") else "surfaces"
        value = getattr(operation, "object" if kind == "objects" else "surface", None)
        target = value.id if value is not None else operation.id
        identity = (kind, target)
        if identity in touched:
            raise ValueError("同一轮不能重复修改同一个目标")
        touched.add(identity)
        index = next(
            (i for i, item in enumerate(result[kind]) if item["id"] == target), None
        )
        if operation.type.startswith("add"):
            if operation.type == "add_asset_object":
                asset = allowed_assets.get(operation.asset_id)
                if asset is None:
                    raise ValueError("家具快照不在本轮允许范围")
                if operation.position.y != 0:
                    raise ValueError("冻结落地家具不能悬空")
                result[kind].append(
                    {
                        "id": operation.id,
                        "asset_id": asset.id,
                        "room_id": operation.room_id,
                        "name": asset.name,
                        "category": "furniture",
                        "position": operation.position.model_dump(mode="json"),
                        "size": asset.size.model_dump(mode="json"),
                        "rotation": operation.rotation,
                        "material": asset.material.model_dump(mode="json"),
                        "installation": {"kind": "floor"},
                    }
                )
                continue
            if (
                kind == "objects"
                and value.clearance is not None
                and value.clearance.confirmed
            ):
                raise ValueError("AI 不能确认使用预留条件")
            if kind == "objects" and value.asset_id is not None:
                raise ValueError("AI 不能创建家具快照引用")
            if index is not None:
                raise ValueError("新增目标标识已经存在")
            result[kind].append(value.model_dump(mode="json"))
        else:
            if index is None:
                raise ValueError("修改目标不存在")
            if operation.type.startswith("remove"):
                result[kind].pop(index)
            elif kind == "objects":
                if result[kind][index].get(
                    "asset_id"
                ) is not None and operation.changes.model_fields_set & {
                    "size",
                    "material",
                }:
                    raise ValueError("冻结家具不能通过 AI 修改尺寸或材质")
                if (
                    result[kind][index].get("asset_id") is not None
                    and operation.changes.position is not None
                    and operation.changes.position.y != 0
                ):
                    raise ValueError("落地家具不能悬空")
                result[kind][index].update(
                    operation.changes.model_dump(mode="json", exclude_unset=True)
                )
            else:
                result[kind][index]["material"] = operation.material.model_dump(
                    mode="json"
                )
    return HomeDesignDocument.model_validate(result)
