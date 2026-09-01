from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_owned_design_task
from app.db.database import get_db
from app.schemas.custom_furniture import (
    CustomFurniturePreviewRequest,
    CustomFurniturePreviewResponse,
)
from app.services import custom_furniture_service


router = APIRouter()


@router.post(
    "/{task_id}/custom-furniture-previews",
    response_model=CustomFurniturePreviewResponse,
)
def preview_custom_furniture(
    task_id: int,
    payload: CustomFurniturePreviewRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    preview = custom_furniture_service.build_preview(db, payload.spec)
    return CustomFurniturePreviewResponse(task_id=task_id, **preview.model_dump())
