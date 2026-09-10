import json
import hashlib
import logging
from copy import deepcopy
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.design_workflow import DesignWorkflow
from app.api.dependencies import (
    SessionIdHeader,
    get_current_user,
    require_active_session,
    require_owned_design_task,
)
from app.core.config import settings
from app.core.request_context import normalize_request_id
from app.db.database import get_db
from app.db.models import (
    DesignPlanVersion,
    DesignTask,
    RequirementParseResult,
    UploadedImage,
    User,
)
from app.schemas.tasks import (
    ConfirmRequirementRequest,
    DesignRevisionDetailResponse,
    DesignRevisionListResponse,
    DesignRevisionSummary,
    GenerationEventResponse,
    GenerationQueuedResponse,
    GenerationStatusResponse,
    GenerateResponse,
    PlanMutationRequest,
    PlanMutationResponse,
    RefinePlanRequest,
    RefinePlanResponse,
    RequirementResponse,
    TaskCreate,
    TaskResponse,
    TaskResultResponse,
    TaskStatusResponse,
)
from app.schemas.task_timeline import TaskTimelineEventResponse, TaskTimelineResponse
from app.schemas.design_agent import AgentTurnRequest
from app.services import (
    anonymous_session_service,
    aggregate_lock_service,
    catalog_service,
    design_agent_service,
    design_version_service,
    generation_provenance,
    generation_request_service,
    generation_run_service,
    llm_service,
    plan_mutation_service,
    profile_service,
    task_service,
    task_timeline_service,
)
from app.services.llm_service import LLMUnavailable

logger = logging.getLogger(__name__)
router = APIRouter()
MAX_BUDGET_REPLANS = 2


@router.get("/{task_id}/timeline", response_model=TaskTimelineResponse)
def get_task_timeline(
    task_id: int,
    x_session_id: SessionIdHeader,
    after_id: Annotated[int | None, Query(ge=1)] = None,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    if after_id is not None and before_id is not None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "timeline_cursor_conflict",
                "message": "before_id 与 after_id 不能同时使用",
            },
        )
    events, next_cursor = task_timeline_service.list_events(
        db,
        task_id=task_id,
        after_id=after_id,
        before_id=before_id,
        limit=limit,
    )
    cost = task_timeline_service.cost_summary(db, task_id=task_id)
    return TaskTimelineResponse(
        task_id=task_id,
        events=[
            TaskTimelineEventResponse(
                event_id=event.id,
                request_id=event.request_id,
                source_type=event.source_type,
                source_id=event.source_id,
                attempt=event.attempt,
                event_code=event.event_code,
                summary=task_timeline_service.safe_summary(event.event_code),
                billing_status=event.billing_status,
                cost_cny=event.cost_cny,
                occurred_at=event.occurred_at,
            )
            for event in events
        ],
        next_cursor=next_cursor,
        next_before_id=next_cursor if after_id is None else None,
        next_after_id=next_cursor if after_id is not None else None,
        known_cost_cny=cost.known_cost_cny,
        has_unknown_cost=cost.has_unknown_cost,
        unknown_cost_event_count=cost.unknown_cost_event_count,
    )


@router.post(
    "/{task_id}/plan-mutations",
    response_model=PlanMutationResponse,
)
def mutate_plan(
    task_id: int,
    payload: PlanMutationRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    try:
        require_active_session(db, x_session_id)
        task = aggregate_lock_service.lock_owned_task(
            db,
            session_id=x_session_id,
            task_id=task_id,
        )
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="设计任务不存在或不属于当前会话",
            )
        revision, plan, scene, version, feedback = plan_mutation_service.mutate_plan(
            db,
            task=task,
            payload=payload,
        )
        db.commit()
        db.refresh(revision)
        db.refresh(scene)
        db.refresh(version)
        db.refresh(feedback)
    except plan_mutation_service.PlanMutationConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except aggregate_lock_service.AggregateLockBusy as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "aggregate_busy", "message": str(exc)},
        ) from exc
    except plan_mutation_service.PlacementNotFound as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except plan_mutation_service.PlanMutationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    target_plan = db.get(DesignPlanVersion, scene.plan_version_id)
    if target_plan is None:
        raise RuntimeError("工作台变更缺少方案版本")
    plan = deepcopy(plan)
    plan["planVersionId"] = target_plan.id
    plan["planKey"] = target_plan.plan_key
    return {
        "revision_version": revision.version,
        "plan": plan,
        "scene": {
            "id": scene.id,
            "plan_version_id": scene.plan_version_id,
            "current_version": scene.current_version,
            "scene": version.scene_json,
            "validation": version.validation_json,
            "source": version.source,
            "created_at": scene.created_at,
            "updated_at": scene.updated_at,
        },
        "feedback": feedback,
    }


def _get_task(db: Session, task_id: int) -> DesignTask:
    task = db.get(DesignTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _plan_version_payload(plan_version) -> dict:
    """在不修改不可变快照的前提下，把数据库版本编号暴露给 3D 场景 API。"""
    return {
        **(plan_version.plan_json or {}),
        "planVersionId": plan_version.id,
        "generationSource": plan_version.revision.generator,
    }


@router.get("/mine")
def my_designs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """登录用户的历史方案列表，每个任务附带最新版本方案快照。"""
    return {"designs": design_version_service.list_user_designs(db, user_id=user.id)}


@router.post("", response_model=TaskResponse)
def create_task(
    task_data: TaskCreate,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    if task_data.session_id and task_data.session_id != x_session_id:
        raise HTTPException(status_code=400, detail="请求中的会话编号不一致")
    if not anonymous_session_service.session_owns_images(
        db,
        x_session_id,
        task_data.image_ids,
    ):
        raise HTTPException(status_code=403, detail="上传图片不属于当前会话")

    task = DesignTask(
        raw_user_input=task_data.user_input,
        active_mode=task_data.active_mode,
    )
    if task_data.requirement:
        # 前端表单已收集结构化需求，直接进入已确认状态
        task.confirmed_requirement_json = task_data.requirement
        task.status = "confirmed"
        task.progress = 50
        task.space_type = " / ".join(task_data.requirement.get("rooms", [])[:3]) or None
        task.style = " / ".join(task_data.requirement.get("styles", [])[:3]) or None
    else:
        task.status = "analyzing"
        task.progress = 20
    db.add(task)
    db.commit()
    db.refresh(task)
    anonymous_session_service.attach_task(db, x_session_id, task.id)

    # 关联已上传的图片
    if task_data.image_ids:
        images = list(db.scalars(
            select(UploadedImage).where(UploadedImage.id.in_(task_data.image_ids))
        ))
        for image in images:
            image.task_id = task.id
            task_timeline_service.project_visual_analysis(
                db,
                task_id=task.id,
                image=image,
            )
        db.commit()

    return TaskResponse(task_id=task.id, status=task.status)


@router.get("/{task_id}/requirement", response_model=RequirementResponse)
def get_requirement(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    raw_input = task.raw_user_input or ""

    existing = db.scalar(
        select(RequirementParseResult)
        .where(
            RequirementParseResult.task_id == task.id,
            RequirementParseResult.raw_input == raw_input,
        )
        .order_by(RequirementParseResult.id.desc())
    )
    if existing is not None:
        return RequirementResponse(
            parsed_requirement=deepcopy(existing.parsed_json or {}),
            missing_fields=list(existing.missing_fields or []),
            follow_up_questions=list(existing.follow_up_questions or []),
            parser=existing.parser,
        )

    parser = "llm"
    parser_model = None
    with llm_service.capture_model_call() as model_call:
        try:
            parsed = llm_service.parse_requirement(raw_input)
            parser_model = settings.llm_model
            missing_fields = parsed.pop("missing_fields", [])
            follow_up_questions = parsed.pop("follow_up_questions", [])
        except LLMUnavailable:
            parser = "rule"
            parsed = task_service.parse_requirement(raw_input)
            missing_fields = []
            if parsed["budget"]["max_budget"] == "未指定":
                missing_fields.append("budget")
            if parsed.get("area") is None:
                missing_fields.append("area")
            follow_up_questions = []
            if "area" in missing_fields:
                follow_up_questions.append("您的房间面积大概是多少？")
            if "budget" in missing_fields:
                follow_up_questions.append("您的预算范围大概是多少？")

    billing_status, cost_cny = task_timeline_service.billing_for_model_call(
        attempted=model_call.attempted,
        usage=model_call.usage,
        input_price_per_mtok=settings.llm_input_price_per_mtok,
        output_price_per_mtok=settings.llm_output_price_per_mtok,
    )
    parse_result = RequirementParseResult(
        task_id=task.id,
        raw_input=raw_input,
        parsed_json=parsed,
        missing_fields=missing_fields,
        follow_up_questions=follow_up_questions,
        parser=parser,
        parser_model=parser_model,
        model_call_attempted=model_call.attempted,
        billing_status=billing_status,
        cost_cny=cost_cny,
    )
    db.add(parse_result)
    db.flush()
    task_timeline_service.append_event(
        db,
        task_id=task.id,
        source_type="requirement",
        source_id=parse_result.id,
        attempt=1 if model_call.attempted else None,
        event_code=(
            "requirement.completed" if parser == "llm" else "requirement.fallback"
        ),
        billing_status=billing_status,
        cost_cny=cost_cny,
        event_key=f"requirement:{parse_result.id}:completed",
    )
    task.status = "waiting_confirm"
    task.progress = 40
    db.commit()

    return RequirementResponse(
        parsed_requirement=parsed,
        missing_fields=missing_fields,
        follow_up_questions=follow_up_questions,
        parser=parser,
    )


@router.post("/{task_id}/confirm-requirement")
def confirm_requirement(
    task_id: int,
    req: ConfirmRequirementRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    task.confirmed_requirement_json = req.confirmed_requirement
    task.status = "confirmed"
    task.progress = 50
    db.commit()

    # 登录用户：从确认的需求中提取长期画像（不阻断主流程）
    if task.user_id:
        requirement_text = json.dumps(
            req.confirmed_requirement,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        requirement_digest = hashlib.sha256(requirement_text.encode("utf-8")).hexdigest()
        event_key = f"profile:{task.id}:{requirement_digest}"

        # 同一任务的画像更新串行执行，避免并发确认重复调用模型和重复计费。
        locked_task = db.scalar(
            select(DesignTask).where(DesignTask.id == task.id).with_for_update()
        )
        if locked_task is not None and task_timeline_service.get_event_by_key(
            db, event_key=event_key
        ) is None:
            profile = None
            extraction_failed = False
            with llm_service.capture_model_call() as model_call:
                try:
                    profile = profile_service.extract_and_merge(
                        db,
                        user_id=locked_task.user_id,
                        text=requirement_text,
                        commit=False,
                    )
                except Exception:
                    db.rollback()
                    extraction_failed = True
                    logger.exception("画像提取失败: task_id=%s", task.id)

            billing_status, cost_cny = task_timeline_service.billing_for_model_call(
                attempted=model_call.attempted,
                usage=model_call.usage,
                input_price_per_mtok=settings.llm_input_price_per_mtok,
                output_price_per_mtok=settings.llm_output_price_per_mtok,
            )
            if extraction_failed:
                event_code = "profile.failed"
            elif profile is not None:
                event_code = "profile.completed"
            else:
                event_code = "profile.skipped"
            task_timeline_service.append_event(
                db,
                task_id=task.id,
                source_type="profile",
                source_id=task.id,
                attempt=model_call.attempt_count or None,
                event_code=event_code,
                billing_status=billing_status,
                cost_cny=cost_cny,
                event_key=event_key,
            )
            db.commit()

    return {"status": "ok"}


def _execute_generation(
    db: Session,
    *,
    task: DesignTask,
    on_step=None,
    on_meta=None,
    before_persist=None,
    on_success=None,
    allow_template_fallback: bool = False,
) -> GenerateResponse:
    task_id = task.id
    task.status = "generating"
    task.progress = 60
    task.error_message = None
    db.commit()

    try:
        requirement = deepcopy(
            task.confirmed_requirement_json
            or task_service.parse_requirement(task.raw_user_input or "")
        )
        confirmed_facts = design_agent_service.confirmed_generation_facts(task)
        budget_max = confirmed_facts.get("budget_max")

        # 登录用户：注入长期画像，让方案贴合其偏好
        if task.user_id:
            profile = profile_service.get_or_create_profile(
                db,
                user_id=task.user_id,
            )
            profile_context = profile_service.build_profile_context(profile)
            if profile_context:
                requirement = {**(requirement or {}), "profile_context": profile_context}

        # 若有上传图片的 VL 分析结果，作为空间上下文一并喂给方案生成
        image_context = []
        for img in db.scalars(
            select(UploadedImage)
            .where(UploadedImage.task_id == task.id)
            .order_by(UploadedImage.id)
        ):
            analysis = img.analysis_json or {}
            if analysis.get("findings"):
                image_context.extend(analysis["findings"])
        # 商品库上下文：家具与定制报价只能从自家库里选
        catalog_context = catalog_service.build_catalog_context(db)

        def build_template_plans(requirement_payload):
            if not allow_template_fallback:
                raise llm_service.LLMUnavailable(
                    "Agent 生成必须由真实模型完成，不允许模板降级"
                )
            return task_service.build_template_plans(requirement_payload)

        workflow = DesignWorkflow(
            generate_plans=llm_service.generate_plans,
            build_template_plans=build_template_plans,
            enrich_plans=lambda plans: catalog_service.verify_and_enrich_plans(
                db,
                plans,
            ),
            on_step=on_step,
        )
        workflow_trace: list[dict] = []
        retry_count = 0
        attempt_requirement = deepcopy(requirement)

        def emit_generation_meta(
            generated_plans: list[dict],
            *,
            accepted: bool,
        ) -> None:
            if on_meta is None:
                return
            meta = llm_service.last_generation_meta()
            if meta is None:
                return
            provenance = generation_provenance.build_generation_provenance(
                prompt_snapshot=str(meta.get("prompt_snapshot") or ""),
                input_snapshot=meta.get("input_snapshot") or {},
                catalog_context=catalog_context,
            )
            on_meta(
                {
                    "meta": {**meta, **provenance},
                    "output_snapshot": {
                        "retry_count": retry_count,
                        "model_output_accepted": accepted,
                        "plan_count": len(generated_plans),
                        "plans": [
                            {
                                "name": plan.get("name"),
                                "style": plan.get("style"),
                                "budget": plan.get("budget"),
                                "score": plan.get("score"),
                                "furniture_count": len(
                                    plan.get("furnitureSuggestions") or []
                                ),
                            }
                            for plan in generated_plans
                        ],
                    },
                }
            )

        while True:
            try:
                workflow_result = workflow.run(
                    requirement=attempt_requirement,
                    image_context=image_context,
                    catalog_context=catalog_context,
                )
            except Exception:
                emit_generation_meta([], accepted=False)
                raise
            plans = workflow_result["plans"]
            generator = workflow_result["generator"]
            workflow_trace.extend(workflow_result["node_trace"])

            # 模型输出即使触发模板降级，供应商已返回的 usage 仍必须记账。
            emit_generation_meta(plans, accepted=generator == "llm")

            plan_totals = [
                int(plan["shopQuote"]["total"])
                for plan in plans
            ]
            over_budget = (
                isinstance(budget_max, (int, float))
                and not isinstance(budget_max, bool)
                and any(total > budget_max for total in plan_totals)
            )
            if not over_budget:
                break

            if retry_count >= MAX_BUDGET_REPLANS:
                error = generation_run_service.GenerationBudgetReplanExhausted(
                    budget_max=budget_max,
                    plan_totals=plan_totals,
                    retry_count=retry_count,
                    max_retries=MAX_BUDGET_REPLANS,
                )
                if on_step is not None:
                    on_step(
                        {
                            "node": "budget_guard",
                            "status": "failed",
                            "source": "deterministic",
                            **error.details,
                        }
                    )
                raise error

            retry_count += 1
            replan_context = {
                "reason_code": "budget_exceeded",
                "retry_count": retry_count,
                "max_retries": MAX_BUDGET_REPLANS,
                "budget_max": budget_max,
                "previous_plan_totals": plan_totals,
            }
            replan_step = {
                "node": "budget_replan",
                "status": "completed",
                "source": "deterministic",
                **replan_context,
            }
            if on_step is not None:
                # Worker 的 step 回调同时执行租约、取消和 deadline 门禁。
                on_step(replan_step)
            workflow_trace.append(replan_step)
            attempt_requirement = deepcopy(requirement)
            attempt_requirement["budget_replan"] = replan_context
        if generator == "template":
            generation_step = next(
                (
                    step
                    for step in workflow_trace
                    if step.get("node") == "generate_plans"
                ),
                {},
            )
            logger.warning(
                "LLM 方案生成降级到模板: %s",
                generation_step.get("fallback_reason", "未知原因"),
            )

        if before_persist is not None:
            before_persist()

        revision = design_version_service.persist_generation(
            db,
            task=task,
            plans=plans,
            generator=generator,
            image_context=image_context,
            workflow_trace=workflow_trace,
        )
        task.status = "completed"
        task.progress = 100
        if on_success is not None:
            on_success(generator, revision.id)
        else:
            db.commit()

        return GenerateResponse(
            task_id=task.id,
            status="completed",
            generator=generator,
        )
    except Exception as exc:
        db.rollback()
        if isinstance(
            exc,
            (
                generation_run_service.GenerationRunOwnershipError,
                generation_run_service.GenerationBudgetReplanExhausted,
                generation_run_service.GenerationMetadataDriftError,
            ),
        ):
            raise
        failed_task = db.get(DesignTask, task_id)
        if failed_task:
            failed_task.status = "failed"
            failed_task.progress = 0
            failed_task.error_message = str(exc)[:2000]
            db.commit()
        logger.exception("方案生成任务失败: task_id=%s", task_id)
        raise HTTPException(status_code=500, detail="方案生成失败，请稍后重试") from exc


def _generation_request_digest(db: Session, task: DesignTask) -> str:
    return generation_request_service.build_request_digest(db, task)


@router.post(
    "/{task_id}/generate",
    response_model=GenerateResponse,
    deprecated=True,
)
def generate_design(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    """同步入口已移除；`generate-async` 仅保留给已确认事实的兼容调用。"""
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    raise HTTPException(
        status_code=410,
        detail={
            "code": "synchronous_generation_removed",
            "message": "同步生成入口已停用，请通过 Agent 工作台发起设计",
        },
    )


def execute_generation_run(run_id: int) -> None:
    """开发环境显式回退入口；默认生产路径不从请求进程执行。"""
    from app.workers.generation_worker import execute_specific_run

    execute_specific_run(run_id)


@router.post(
    "/{task_id}/generate-async",
    response_model=GenerationQueuedResponse,
    status_code=202,
)
def queue_design_generation(
    task_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    x_session_id: SessionIdHeader,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=100,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    missing_facts = design_agent_service.missing_confirmed_generation_facts(task)
    if missing_facts:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "generation_facts_incomplete",
                "message": "生成方案前必须确认预算和房间尺寸",
                "missing_fields": missing_facts,
            },
        )
    try:
        run = generation_run_service.create_run(
            db,
            task=task,
            idempotency_key=idempotency_key,
            max_attempts=settings.generation_worker_max_attempts,
            request_id=getattr(request.state, "request_id", None)
            or normalize_request_id(request.headers.get("X-Request-ID")),
            request_digest=_generation_request_digest(db, task),
        )
    except generation_run_service.GenerationIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "message": str(exc)},
        ) from exc
    if run.status == "queued":
        task.status = "queued"
        task.progress = 50
        task.error_message = None
        db.commit()
        if settings.generation_inline_fallback:
            background_tasks.add_task(execute_generation_run, run.id)
    return GenerationQueuedResponse(run_id=run.id, status=run.status)


@router.post(
    "/{task_id}/generation/cancel",
    response_model=GenerationQueuedResponse,
)
def cancel_design_generation(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    run = generation_run_service.get_latest_run(db, task_id=task_id)
    if run is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    status = generation_run_service.request_cancel(db, run=run)
    return GenerationQueuedResponse(run_id=run.id, status=status)


@router.get(
    "/{task_id}/generation",
    response_model=GenerationStatusResponse,
)
def get_generation_status(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    run = generation_run_service.get_latest_run(db, task_id=task_id)
    if run is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    return GenerationStatusResponse(
        run_id=run.id,
        request_id=run.request_id,
        attempt=run.attempt,
        attempt_count=run.attempt_count,
        max_attempts=run.max_attempts,
        status=run.status,
        progress=run.progress,
        current_node=run.current_node,
        generator=run.generator,
        error_message=run.error_message,
        cancel_requested_at=run.cancel_requested_at,
        next_retry_at=run.next_retry_at,
        execution_deadline_at=run.execution_deadline_at,
        dead_lettered_at=run.dead_lettered_at,
        cost_cny=run.cost_cny,
        cost_reserved_cny=run.cost_reserved_cny or 0.0,
        cost_limit_cny=run.cost_limit_cny,
        result_revision_id=run.result_revision_id,
        output_digest=run.output_digest,
        events=[
            GenerationEventResponse(
                node=event.node,
                status=event.status,
                progress=event.progress,
                source=event.source,
                duration_ms=event.duration_ms,
                details=event.detail_json or {},
            )
            for event in run.events
        ],
    )


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    return TaskStatusResponse(
        task_id=task.id, status=task.status, progress=task.progress or 0
    )


@router.get("/{task_id}/result", response_model=TaskResultResponse)
def get_task_result(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    revision = design_version_service.get_latest_revision(db, task_id=task_id)
    if revision is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "design_revision_required",
                "message": "可信方案版本尚未生成",
            },
        )

    images = [
        {"image_id": img.id, "image_url": img.file_url, "image_type": img.image_type}
        for img in db.scalars(
            select(UploadedImage).where(UploadedImage.task_id == task_id)
        )
    ]
    return TaskResultResponse(
        plans=[
            {**_plan_version_payload(plan), "task_id": task_id}
            for plan in revision.plans
        ],
        generator=revision.generator,
        revision_version=revision.version,
        images=images,
        pdf_url=None,
    )


@router.post(
    "/{task_id}/plans/{plan_id}/refine",
    response_model=RefinePlanResponse,
    deprecated=True,
)
def refine_plan(
    task_id: int,
    plan_id: str,
    req: RefinePlanRequest,
    x_session_id: SessionIdHeader,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=100,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
    db: Session = Depends(get_db),
):
    """兼容入口：实际写入统一 Agent turn，不再直接调用模型服务。"""
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    digest = hashlib.sha256(
        f"{task_id}:{idempotency_key}".encode("utf-8")
    ).hexdigest()[:32]
    result = design_agent_service.run_turn(
        db,
        task=task,
        payload=AgentTurnRequest(
            client_turn_id=f"legacy-refine-{digest}",
            message=req.instruction,
            active_mode="catalog_design",
            plan_id=plan_id,
        ),
    )
    if result.get("status") != "completed" or not isinstance(
        result.get("result"), dict
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "agent_plan_refine_incomplete",
                "message": result.get("reply") or "方案精修未完成",
            },
        )
    return result["result"]


@router.get(
    "/{task_id}/versions",
    response_model=DesignRevisionListResponse,
)
def get_design_versions(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    revisions = design_version_service.list_revisions(db, task_id=task_id)
    summaries = []
    for revision in revisions:
        totals = [
            plan.quote_snapshot.grand_total
            for plan in revision.plans
            if plan.quote_snapshot is not None
        ]
        summaries.append(
            DesignRevisionSummary(
                version=revision.version,
                generator=revision.generator,
                status=revision.status,
                plan_count=len(revision.plans),
                quote_min=min(totals, default=0),
                quote_max=max(totals, default=0),
                created_at=revision.created_at,
            )
        )
    return DesignRevisionListResponse(revisions=summaries)


@router.get(
    "/{task_id}/versions/{version}",
    response_model=DesignRevisionDetailResponse,
)
def get_design_version(
    task_id: int,
    version: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    revision = design_version_service.get_revision(
        db,
        task_id=task_id,
        version=version,
    )
    if not revision:
        raise HTTPException(status_code=404, detail="方案版本不存在")
    return DesignRevisionDetailResponse(
        version=revision.version,
        generator=revision.generator,
        status=revision.status,
        requirement=revision.requirement_snapshot or {},
        image_context=revision.image_context_snapshot or [],
        workflow_trace=revision.workflow_trace_snapshot or [],
        plans=[_plan_version_payload(plan) for plan in revision.plans],
        created_at=revision.created_at,
    )


@router.post(
    "/{task_id}/export-pdf",
    deprecated=True,
    description=(
        "旧版无方案版本导出入口已停用。请改用基于服务端方案快照的 "
        "/api/design/proposal-pdf。"
    ),
)
def export_pdf(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    raise HTTPException(
        status_code=410,
        detail={
            "code": "legacy_pdf_export_retired",
            "message": "旧版导出未绑定方案快照，已停止使用",
            "replacement": "/api/design/proposal-pdf",
        },
    )
