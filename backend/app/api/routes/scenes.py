"""客户 Web 3D 编辑器的场景版本 API。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_active_session
from app.agents.scene_agent import SceneAgentSafetyError, SceneAgentWorkflow
from app.core.config import settings
from app.db.database import get_db
from app.db.models import DesignScene, DesignSceneVersion
from app.schemas.scenes import (
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
from app.services import llm_service, scene_service, scene_tools
from app.services.scene_agent_rate_limit import SceneAgentRateLimiter
from app.services.llm_service import LLMUnavailable

router = APIRouter()
scene_agent_rate_limiter = SceneAgentRateLimiter(
    max_requests=settings.scene_agent_requests_per_minute,
    window_seconds=60,
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


def _version_response(version: DesignSceneVersion) -> SceneVersionResponse:
    return SceneVersionResponse(
        version=version.version,
        scene=SceneDocument.model_validate(version.scene_json),
        validation=SceneValidationReport.model_validate(
            version.validation_json
        ),
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
        validation=SceneValidationReport.model_validate(
            version.validation_json
        ),
        source=version.source,
        created_at=scene.created_at,
        updated_at=scene.updated_at,
    )


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


@router.put("/scenes/{scene_id}", response_model=SceneResponse)
def update_scene(
    scene_id: int,
    payload: SceneUpdateRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    scene = scene_service.get_owned_scene(
        db,
        session_id=x_session_id,
        scene_id=scene_id,
        for_update=True,
    )
    if scene is None:
        raise _not_found("3D 场景")

    try:
        version = scene_service.update_scene(
            db,
            scene=scene,
            base_version=payload.base_version,
            document=payload.scene,
            source=payload.source,
        )
        db.commit()
        db.refresh(scene)
        db.refresh(version)
    except scene_service.SceneConflictError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except scene_service.SceneValidationError as error:
        db.rollback()
        raise _validation_error(error) from error
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
    context = scene_tools.build_scene_agent_context(db, source_document)

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
                f"场景已经更新到版本 {locked_scene.current_version}，"
                "本次 AI 建议未写入"
            ),
        )

    workflow = SceneAgentWorkflow(
        plan_operations=lambda **_: batch,
        execute_operations=lambda document, operations: (
            scene_tools.apply_scene_operations(db, document, operations)
        ),
        validate_scene=lambda document: scene_service.validate_scene(
            db, document
        ),
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
