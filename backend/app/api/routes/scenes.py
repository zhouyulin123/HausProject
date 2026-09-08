"""客户 Web 3D 编辑器的场景版本 API。"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import (
    SessionIdHeader,
    get_current_user,
    require_active_session,
)
from app.agents.scene_agent import SceneAgentSafetyError, SceneAgentWorkflow
from app.core.config import settings
from app.db.database import get_db
from app.db.models import (
    BlenderRenderJob,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    DesignTask,
    User,
)
from app.schemas.blender_render import (
    BlenderRenderJobResponse,
    BlenderRenderRequest,
)
from app.schemas.scenes import (
    CustomFurnitureSceneItemRequest,
    SceneCreateRequest,
    SceneDocument,
    SceneResponse,
    SceneUpdateRequest,
    SceneValidationReport,
    SceneVersionListResponse,
    SceneVersionResponse,
)
from app.schemas.scene_agent import (
    SceneAgentCommandRequest,
    SceneAgentCommandResponse,
)
from app.schemas.feedback import DesignFeedbackEventRequest
from app.services import (
    blender_job_service,
    aggregate_lock_service,
    design_version_service,
    design_agent_service,
    feedback_service,
    layout_generator,
    layout_service,
    llm_service,
    scene_service,
    scene_tools,
)
from app.services.llm_service import LLMUnavailable
from app.services.scene_agent_rate_limit import SceneAgentRateLimiter

router = APIRouter()
logger = logging.getLogger(__name__)
scene_agent_rate_limiter = SceneAgentRateLimiter(
    max_requests=settings.scene_agent_requests_per_minute,
    window_seconds=60,
)
blender_render_rate_limiter = SceneAgentRateLimiter(
    max_requests=settings.blender_render_requests_per_hour,
    window_seconds=3600,
)


def _not_found(resource: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=f"{resource}不存在或不属于当前会话",
    )


def _validation_error(
    error: scene_service.SceneValidationError,
) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "message": str(error),
            "validation": error.report.model_dump(mode="json"),
        },
    )


def _catalog_error(
    error: scene_tools.SceneCatalogEligibilityError,
) -> HTTPException:
    return HTTPException(status_code=422, detail=error.details)


def _version_response(version: DesignSceneVersion) -> SceneVersionResponse:
    return SceneVersionResponse(
        version=version.version,
        scene=SceneDocument.model_validate(version.scene_json),
        validation=SceneValidationReport.model_validate(version.validation_json),
        source=version.source,
        created_at=version.created_at,
    )


def _scene_response(
    scene: DesignScene,
    version: DesignSceneVersion,
) -> SceneResponse:
    return SceneResponse(
        id=scene.id,
        plan_version_id=scene.plan_version_id,
        current_version=scene.current_version,
        scene=SceneDocument.model_validate(version.scene_json),
        validation=SceneValidationReport.model_validate(version.validation_json),
        source=version.source,
        created_at=scene.created_at,
        updated_at=scene.updated_at,
    )


def _render_job_response(job: BlenderRenderJob) -> BlenderRenderJobResponse:
    return BlenderRenderJobResponse(
        id=job.id,
        scene_id=job.scene_id,
        scene_version=job.scene_version,
        profile=job.profile,
        status=job.status,
        progress=job.progress,
        attempt=job.attempt,
        max_attempts=job.max_attempts,
        output_url=job.output_url,
        error_code=job.error_code,
        error_message=job.error_message,
        heartbeat_at=job.heartbeat_at,
        execution_deadline_at=job.execution_deadline_at,
        next_retry_at=job.next_retry_at,
        cancel_requested_at=job.cancel_requested_at,
        dead_lettered_at=job.dead_lettered_at,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get("/plan-versions/{plan_version_id}")
def get_plan_version_detail(
    plan_version_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按方案版本 ID 拉取方案快照，供登录用户跨设备打开详情页兜底。"""
    plan_version = design_version_service.get_plan_version_for_user(
        db,
        plan_version_id=plan_version_id,
        user_id=user.id,
    )
    if plan_version is None:
        raise _not_found("方案版本")
    return {"plan": design_version_service.plan_version_payload(plan_version)}


@router.post(
    "/plan-versions/{plan_version_id}/scene",
    response_model=SceneResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_plan_scene(
    plan_version_id: int,
    payload: SceneCreateRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    plan_version = scene_service.get_owned_plan_version(
        db,
        session_id=x_session_id,
        plan_version_id=plan_version_id,
    )
    if plan_version is None:
        raise _not_found("方案版本")

    try:
        scene, version = scene_service.create_scene(
            db,
            plan_version=plan_version,
            document=payload.scene,
            source=payload.source,
        )
        db.commit()
        db.refresh(scene)
        db.refresh(version)
    except scene_tools.SceneCatalogEligibilityError as error:
        db.rollback()
        raise _catalog_error(error) from error
    except scene_service.SceneConflictError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except scene_service.SceneValidationError as error:
        db.rollback()
        raise _validation_error(error) from error
    return _scene_response(scene, version)


@router.post(
    "/plan-versions/{plan_version_id}/auto-layout",
    response_model=SceneResponse,
    status_code=status.HTTP_201_CREATED,
)
def auto_layout_plan_scene(
    plan_version_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    """用确定性布局引擎为方案自动生成可编辑的 3D 初稿（幂等）。

    场景已存在时直接返回当前版本，不重复生成。
    """
    require_active_session(db, x_session_id)
    plan_version = scene_service.get_owned_plan_version(
        db,
        session_id=x_session_id,
        plan_version_id=plan_version_id,
    )
    if plan_version is None:
        raise _not_found("方案版本")

    # 幂等：场景已存在直接返回当前版本
    existing = scene_service.get_scene_by_plan_version(db, plan_version.id)
    if existing is not None:
        version = scene_service.get_current_version(db, existing)
        return _scene_response(existing, version)

    plan = plan_version.plan_json or {}
    furniture = layout_service.build_layout_furniture(
        db, plan.get("furnitureSuggestions")
    )
    if not furniture:
        raise HTTPException(
            status_code=422,
            detail="方案没有可用于布局的商品",
        )

    revision = db.get(DesignRevision, plan_version.revision_id)
    task = db.get(DesignTask, revision.task_id) if revision else None
    room_name = task.space_type if task and task.space_type else "客厅"
    geometry = layout_service.room_geometry_from_plan_version(db, plan_version)
    room, openings = geometry or layout_service.default_room_geometry(room_name)

    started = time.monotonic()
    results = layout_generator.generate_layouts(room, openings, furniture)
    duration_ms = int((time.monotonic() - started) * 1000)
    if not results:
        raise HTTPException(status_code=422, detail="无法为这套方案生成布局")

    best_scene, best_score = results[0]
    if not best_score.valid:
        logger.warning(
            "方案 %s 的最优自动布局未达标（%d 分）",
            plan_version.id,
            best_score.total,
        )

    try:
        scene, version = scene_service.create_scene(
            db,
            plan_version=plan_version,
            document=best_scene,
            source="auto_layout",
        )
        # 记录布局生成元数据（评分/问题分布/耗时），供质量监控与失败反推
        layout_service.record_layout_run(
            db,
            plan_version_id=plan_version.id,
            scene_version_id=version.id,
            room=room,
            furniture=furniture,
            results=results,
            duration_ms=duration_ms,
        )
        db.commit()
        db.refresh(scene)
        db.refresh(version)
    except scene_tools.SceneCatalogEligibilityError as error:
        db.rollback()
        raise _catalog_error(error) from error
    except scene_service.SceneConflictError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except scene_service.SceneValidationError as error:
        db.rollback()
        raise _validation_error(error) from error
    return _scene_response(scene, version)


@router.get(
    "/plan-versions/{plan_version_id}/scene",
    response_model=SceneResponse,
)
def get_plan_scene(
    plan_version_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    plan_version = scene_service.get_owned_plan_version(
        db,
        session_id=x_session_id,
        plan_version_id=plan_version_id,
    )
    if plan_version is None:
        raise _not_found("方案版本")
    scene = scene_service.get_scene_by_plan_version(db, plan_version.id)
    if scene is None:
        raise _not_found("3D 场景")
    version = scene_service.get_current_version(db, scene)
    return _scene_response(scene, version)


@router.get("/scenes/{scene_id}", response_model=SceneResponse)
def get_scene(
    scene_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=scene_id,
    )
    if scene is None:
        raise _not_found("3D 场景")
    version = scene_service.get_current_version(db, scene)
    return _scene_response(scene, version)


@router.post(
    "/scenes/{scene_id}/custom-furniture-items",
    response_model=SceneResponse,
)
def add_custom_furniture_item(
    scene_id: int,
    payload: CustomFurnitureSceneItemRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    try:
        locked = aggregate_lock_service.lock_owned_scene(
            db,
            session_id=x_session_id,
            scene_id=scene_id,
        )
        if locked is None:
            raise _not_found("3D 场景")
        _, scene = locked
        version, created = scene_service.add_custom_furniture_draft_to_scene(
            db,
            scene=scene,
            payload=payload,
        )
        if created:
            task_id = scene_service.get_scene_task_id(db, scene.id)
            if task_id is None:
                raise RuntimeError("场景缺少所属任务")
            design_agent_service.record_scene_reference(
                db,
                task_id=task_id,
                scene_id=scene.id,
                version=version.version,
            )
        db.commit()
        db.refresh(scene)
        db.refresh(version)
        return _scene_response(scene, version)
    except scene_service.CustomSceneBindingError as error:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": error.code, "message": str(error)},
        ) from error
    except scene_service.SceneConflictError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except scene_service.SceneValidationError as error:
        db.rollback()
        raise _validation_error(error) from error
    except aggregate_lock_service.AggregateLockBusy as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "aggregate_busy", "message": str(error)},
        ) from error


@router.put("/scenes/{scene_id}", response_model=SceneResponse)
def update_scene(
    scene_id: int,
    payload: SceneUpdateRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    try:
        locked = aggregate_lock_service.lock_owned_scene(
            db,
            session_id=x_session_id,
            scene_id=scene_id,
        )
        if locked is None:
            raise _not_found("3D 场景")
        _, scene = locked
        if payload.client_mutation_id:
            version, created = scene_service.update_scene_idempotent(
                db,
                scene=scene,
                base_version=payload.base_version,
                document=payload.scene,
                source=payload.source,
                client_mutation_id=payload.client_mutation_id,
                mutation_metadata={
                    "moved_instance_ids": payload.moved_instance_ids,
                    "feedback_room_id": payload.feedback_room_id,
                },
            )
        else:
            version = scene_service.update_scene(
                db,
                scene=scene,
                base_version=payload.base_version,
                document=payload.scene,
                source=payload.source,
            )
            created = True
        if created and payload.client_mutation_id:
            task_id = scene_service.get_scene_task_id(db, scene.id)
            if task_id is None:
                raise RuntimeError("场景缺少所属任务")
            for index, instance_id in enumerate(payload.moved_instance_ids):
                event_id = (
                    payload.client_mutation_id
                    if len(payload.moved_instance_ids) == 1
                    else f"{payload.client_mutation_id[:88]}:{index}"
                )
                feedback_service.create_feedback_event(
                    db,
                    task_id=task_id,
                    payload=DesignFeedbackEventRequest(
                        client_event_id=event_id,
                        action_type="move",
                        scene_id=scene.id,
                        scene_version=version.version,
                        room_id=payload.feedback_room_id,
                        instance_id=instance_id,
                    ),
                    commit=False,
                )
            design_agent_service.record_scene_reference(
                db,
                task_id=task_id,
                scene_id=scene.id,
                version=version.version,
            )
        db.commit()
        db.refresh(scene)
        db.refresh(version)
    except scene_tools.SceneCatalogEligibilityError as error:
        db.rollback()
        raise _catalog_error(error) from error
    except scene_service.CustomSceneBindingError as error:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": error.code, "message": str(error)},
        ) from error
    except scene_service.SceneConflictError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except scene_service.SceneValidationError as error:
        db.rollback()
        raise _validation_error(error) from error
    except (
        feedback_service.FeedbackResourceNotFound,
        feedback_service.FeedbackIdempotencyConflict,
    ) as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except aggregate_lock_service.AggregateLockBusy as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "aggregate_busy", "message": str(error)},
        ) from error
    return _scene_response(scene, version)


@router.get(
    "/scenes/{scene_id}/versions",
    response_model=SceneVersionListResponse,
)
def get_scene_versions(
    scene_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=scene_id,
    )
    if scene is None:
        raise _not_found("3D 场景")
    return SceneVersionListResponse(
        versions=[
            _version_response(version)
            for version in scene_service.list_versions(db, scene.id)
        ]
    )


@router.post(
    "/scenes/{scene_id}/validate",
    response_model=SceneValidationReport,
)
def validate_scene(
    scene_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=scene_id,
    )
    if scene is None:
        raise _not_found("3D 场景")
    version = scene_service.get_current_version(db, scene)
    document = SceneDocument.model_validate(version.scene_json)
    return scene_service.validate_scene(db, document)


@router.post(
    "/scenes/{scene_id}/render-jobs",
    response_model=BlenderRenderJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_blender_render(
    scene_id: int,
    payload: BlenderRenderRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    """把当前不可变场景版本加入独立 Blender Worker 队列。"""
    require_active_session(db, x_session_id)
    scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=scene_id,
    )
    if scene is None:
        raise _not_found("3D 场景")
    if scene.current_version != payload.base_version:
        raise HTTPException(
            status_code=409,
            detail=f"场景已经更新到版本 {scene.current_version}，请刷新后重试",
        )
    version = scene_service.get_current_version(db, scene)
    if payload.profile == "final":
        try:
            scene_service.assert_scene_catalog_deliverable(
                db,
                SceneDocument.model_validate(version.scene_json),
                region=scene_service.scene_delivery_region(db, scene),
            )
        except scene_tools.SceneCatalogEligibilityError as error:
            db.rollback()
            raise _catalog_error(error) from error
    existing = blender_job_service.get_existing_job(
        db,
        scene_version_id=version.id,
        profile=payload.profile,
    )
    if existing is not None and existing.status != "failed":
        return _render_job_response(existing)
    retry_after = blender_render_rate_limiter.retry_after(str(x_session_id))
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="高质量渲染请求过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )
    if existing is not None:
        job = blender_job_service.requeue_failed_job(db, job=existing)
    else:
        job, _ = blender_job_service.create_or_get_job(
            db,
            scene=scene,
            version=version,
            profile=payload.profile,
            max_attempts=settings.blender_worker_max_attempts,
            execution_timeout_seconds=(
                settings.blender_worker_execution_timeout_seconds
            ),
        )
    return _render_job_response(job)


@router.post(
    "/scenes/{scene_id}/render-jobs/{job_id}/cancel",
    response_model=BlenderRenderJobResponse,
)
def cancel_blender_render_job(
    scene_id: int,
    job_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=scene_id,
    )
    if scene is None:
        raise _not_found("3D 场景")
    job = blender_job_service.get_scene_job(
        db,
        scene_id=scene.id,
        job_id=job_id,
        for_update=True,
    )
    if job is None:
        raise _not_found("Blender 渲染任务")
    if job.status in {"completed", "failed", "dead_letter", "cancelled"}:
        if job.status == "cancelled":
            return _render_job_response(job)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "render_job_not_cancellable",
                "message": "Blender 渲染任务已进入终态，不能取消",
                "status": job.status,
            },
        )
    return _render_job_response(blender_job_service.cancel_job(db, job=job))


@router.get(
    "/scenes/{scene_id}/render-jobs/{job_id}",
    response_model=BlenderRenderJobResponse,
)
def get_blender_render_job(
    scene_id: int,
    job_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=scene_id,
    )
    if scene is None:
        raise _not_found("3D 场景")
    job = blender_job_service.get_scene_job(
        db,
        scene_id=scene.id,
        job_id=job_id,
    )
    if job is None:
        raise _not_found("Blender 渲染任务")
    return _render_job_response(job)


@router.post(
    "/scenes/{scene_id}/agent-command",
    response_model=SceneAgentCommandResponse,
)
def run_scene_agent_command(
    scene_id: int,
    payload: SceneAgentCommandRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    """让模型规划白名单操作，确定性执行并写入新的不可变场景版本。"""
    require_active_session(db, x_session_id)
    scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=scene_id,
    )
    if scene is None:
        raise _not_found("3D 场景")
    if scene.current_version != payload.base_version:
        raise HTTPException(
            status_code=409,
            detail=f"场景已经更新到版本 {scene.current_version}，请刷新后重试",
        )
    retry_after = scene_agent_rate_limiter.retry_after(str(x_session_id))
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Scene Agent 请求过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )
    current = scene_service.get_current_version(db, scene)
    source_document = SceneDocument.model_validate(current.scene_json)
    delivery_region = scene_service.scene_delivery_region(db, scene)
    catalog_scope = {"region": delivery_region} if delivery_region is not None else {}
    context = scene_tools.build_scene_agent_context(
        db,
        source_document,
        **catalog_scope,
    )

    # 模型调用期间不持有数据库事务或行锁。
    db.rollback()
    try:
        batch = llm_service.plan_scene_operations(
            instruction=payload.instruction,
            context=context,
        )
    except LLMUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail="Scene Agent 暂时不可用，请稍后重试",
        ) from error

    locked_scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=scene_id,
        for_update=True,
    )
    if locked_scene is None:
        raise _not_found("3D 场景")
    if locked_scene.current_version != payload.base_version:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"场景已经更新到版本 {locked_scene.current_version}，本次 AI 建议未写入"
            ),
        )

    workflow = SceneAgentWorkflow(
        plan_operations=lambda **_: batch,
        execute_operations=lambda document, operations: (
            scene_tools.apply_scene_operations(
                db,
                document,
                operations,
                **catalog_scope,
            )
        ),
        validate_scene=lambda document: scene_service.validate_scene(db, document),
    )
    try:
        result = workflow.run(
            instruction=payload.instruction,
            context=context,
            source_scene=source_document,
        )
        proposed = result["proposed_scene"]
        if proposed is None:
            raise RuntimeError("Scene Agent 未生成候选场景")
        version = scene_service.update_scene(
            db,
            scene=locked_scene,
            base_version=payload.base_version,
            document=proposed,
            source="scene_agent",
        )
        db.commit()
        db.refresh(locked_scene)
        db.refresh(version)
    except scene_tools.SceneCatalogEligibilityError as error:
        db.rollback()
        raise _catalog_error(error) from error
    except scene_tools.SceneToolError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SceneAgentSafetyError as error:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(error),
                "validation": error.report.model_dump(mode="json"),
            },
        ) from error
    except scene_service.SceneConflictError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error

    return SceneAgentCommandResponse(
        message=batch.message,
        operations=batch.operations,
        scene=_scene_response(locked_scene, version),
    )
