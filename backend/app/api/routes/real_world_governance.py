"""管理员真实案例治理收件箱 API，仅公开匿名治理状态。"""

from __future__ import annotations

import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.config import settings
from app.db.database import get_db
from app.db.models import User
from app.schemas.real_world_governance import (
    AnnotationRevisionCreate,
    CaseGovernanceUpdate,
    CaseImportPreviewResponse,
    CaseImportRequest,
    CaseImportResponse,
    ConsentDecisionCreate,
    DatasetFreezeRequest,
    DatasetRevisionResponse,
    RealWorldCaseListResponse,
    RealWorldCaseResponse,
)
from app.services import real_world_governance_service as governance


router = APIRouter(prefix="/quality")
RequestIdHeader = Annotated[
    str | None,
    Header(alias="X-Request-ID", min_length=1, max_length=100),
]


def _request_id(value: str | None) -> str:
    return value.strip() if value else f"gov_{secrets.token_hex(16)}"


def _raise_http(exc: governance.RealWorldGovernanceError) -> None:
    if isinstance(exc, governance.RealWorldGovernanceNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, governance.RealWorldGovernanceConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/real-world-case-imports/preview",
    response_model=CaseImportPreviewResponse,
)
def preview_import(
    payload: CaseImportRequest,
    _request: RequestIdHeader = None,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CaseImportPreviewResponse:
    try:
        result = governance.preview_case_import(
            db,
            payload,
            upload_root=settings.upload_dir,
        )
    except governance.RealWorldGovernanceError as exc:
        _raise_http(exc)
    return CaseImportPreviewResponse(
        task_input_ready=bool(result.task_input),
        asset_available=True,
        duplicate_asset=result.duplicate_asset,
    )

@router.post(
    "/real-world-case-imports",
    response_model=CaseImportResponse,
)
def create_import(
    payload: CaseImportRequest,
    response: Response,
    request_id: RequestIdHeader = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CaseImportResponse:
    try:
        result = governance.create_case_import(
            db,
            payload,
            actor_user_id=admin.id,
            request_id=_request_id(request_id),
            upload_root=settings.upload_dir,
        )
    except governance.RealWorldGovernanceError as exc:
        _raise_http(exc)
    response.status_code = 201 if result.created else 200
    return CaseImportResponse(
        created=result.created,
        case=governance.project_case_record(db, result.case),
    )


@router.get(
    "/real-world-cases",
    response_model=RealWorldCaseListResponse,
)
def list_cases(
    split: Literal["unassigned", "development", "regression", "blind"] | None = Query(
        default=None
    ),
    blocker: str | None = Query(default=None, min_length=1, max_length=50),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RealWorldCaseListResponse:
    items = governance.list_case_records(db, split=split, blocker=blocker)
    return RealWorldCaseListResponse(items=items, total=len(items))


@router.patch(
    "/real-world-cases/{case_ref}",
    response_model=RealWorldCaseResponse,
)
def patch_case(
    case_ref: str,
    payload: CaseGovernanceUpdate,
    request_id: RequestIdHeader = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RealWorldCaseResponse:
    try:
        case = governance.update_case_governance(
            db,
            case_ref,
            payload,
            actor_user_id=admin.id,
            request_id=_request_id(request_id),
        )
    except governance.RealWorldGovernanceError as exc:
        _raise_http(exc)
    return governance.project_case_record(db, case)


@router.post(
    "/real-world-cases/{case_ref}/consent-decisions",
    response_model=RealWorldCaseResponse,
)
def create_consent_decision(
    case_ref: str,
    payload: ConsentDecisionCreate,
    request_id: RequestIdHeader = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RealWorldCaseResponse:
    try:
        case = governance.add_consent_decision(
            db,
            case_ref,
            payload,
            actor_user_id=admin.id,
            request_id=_request_id(request_id),
        )
    except governance.RealWorldGovernanceError as exc:
        _raise_http(exc)
    return governance.project_case_record(db, case)


@router.post(
    "/real-world-cases/{case_ref}/annotation-revisions",
    response_model=RealWorldCaseResponse,
)
def create_annotation_revision(
    case_ref: str,
    payload: AnnotationRevisionCreate,
    request_id: RequestIdHeader = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RealWorldCaseResponse:
    try:
        case = governance.add_annotation_revision(
            db,
            case_ref,
            payload,
            actor_user_id=admin.id,
            request_id=_request_id(request_id),
        )
    except governance.RealWorldGovernanceError as exc:
        _raise_http(exc)
    return governance.project_case_record(db, case)


@router.post(
    "/real-world-dataset-revisions",
    response_model=DatasetRevisionResponse,
    status_code=201,
)
def freeze_dataset(
    payload: DatasetFreezeRequest,
    request_id: RequestIdHeader = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DatasetRevisionResponse:
    try:
        result = governance.freeze_dataset_revision(
            db,
            payload,
            actor_user_id=admin.id,
            request_id=_request_id(request_id),
        )
    except governance.RealWorldGovernanceError as exc:
        _raise_http(exc)
    return DatasetRevisionResponse(
        revision_ref=result.revision_ref,
        schema_version="2.0",
        dataset_version=result.dataset_version,
        manifest_digest=result.manifest_digest,
        case_count=result.case_count,
        split_counts=result.split_counts,
        created_at=result.created_at,
    )
