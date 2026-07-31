"""客户 Web 3D 编辑器的场景版本 API。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_active_session
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
from app.services import scene_service

router = APIRouter()


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
