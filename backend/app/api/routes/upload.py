import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    SessionIdHeader,
    require_active_session,
    require_owned_design_task,
)
from app.core.config import settings
from app.db.database import get_db
from app.db.models import UploadedImage, AnonymousSessionImage
from app.schemas.room_model import RoomModel, RoomModelCalibrationRequest
from app.services import (
    anonymous_session_service,
    llm_service,
    model_call_governance_service,
    prediction_evidence_service,
    room_model_service,
    task_timeline_service,
)
from app.services.llm_service import LLMUnavailable
from app.services.upload_validation import UploadValidationError, validate_image_upload
from app.services.private_image_service import private_image_response

logger = logging.getLogger(__name__)
router = APIRouter()
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")


@router.get("/images/{image_id}/content")
def read_image_content(
    image_id: int, x_session_id: SessionIdHeader, db: Session = Depends(get_db)
):
    return private_image_response(
        db, image_id=image_id, session_id=x_session_id, directory=settings.upload_dir
    )


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w.一-鿿-]", "_", name or "upload")


def _register_owner(db: Session, image: UploadedImage, session_id: str) -> None:
    require_active_session(db, session_id)
    if image.task_id is not None:
        require_owned_design_task(db, session_id=session_id, task_id=image.task_id)
    relation = db.scalar(
        select(AnonymousSessionImage).where(AnonymousSessionImage.image_id == image.id)
    )
    if relation is not None and relation.session_id != session_id:
        raise HTTPException(404, detail="图片不存在或不属于当前会话")
    if relation is None:
        db.add(AnonymousSessionImage(session_id=session_id, image_id=image.id))


def _upload_response(image: UploadedImage) -> dict:
    if image.analysis_json is None:
        raise HTTPException(
            409,
            detail={
                "code": "upload_not_completed",
                "message": "原图已登记，但识别尚未完成；本次重试不会重复调用模型",
            },
        )
    analysis = image.analysis_json or {}
    room_model = analysis.get("room_model")
    return {
        "image_id": image.id,
        "task_id": image.task_id,
        "image_url": image.file_url,
        "file_name": image.file_name,
        "file_size": image.file_size,
        "analysis": {
            "findings": analysis.get("findings", []),
            "suggestions": analysis.get("suggestions", []),
            "space_type": analysis.get("space_type", ""),
            "room_count": analysis.get("room_count", ""),
            "source": analysis.get("source", "placeholder"),
            "room_model": room_model,
        },
    }


@router.post("/image")
async def upload_image(
    x_session_id: SessionIdHeader,
    file: UploadFile = File(...),
    task_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
):
    require_active_session(db, x_session_id)
    if task_id is not None:
        require_owned_design_task(
            db,
            session_id=x_session_id,
            task_id=task_id,
        )

    content = await file.read()
    try:
        validated = validate_image_upload(
            content=content,
            content_type=file.content_type or "",
            filename=file.filename or "",
            max_bytes=settings.max_upload_image_mb * 1024 * 1024,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    normalized_key = (idempotency_key or "").strip() or None
    if normalized_key is not None and not _IDEMPOTENCY_KEY_PATTERN.fullmatch(
        normalized_key
    ):
        raise HTTPException(status_code=422, detail="Idempotency-Key 格式无效")
    content_digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    request_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {
                    "content_digest": content_digest,
                    "content_type": file.content_type or "",
                    "file_name": file.filename or "",
                    "task_id": task_id,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    operation_key = (
        "sha256:"
        + hashlib.sha256(
            f"{x_session_id}:{task_id}:{normalized_key}".encode("utf-8")
        ).hexdigest()
        if normalized_key is not None
        else None
    )
    if operation_key is not None:
        existing = db.scalar(
            select(UploadedImage).where(
                UploadedImage.upload_operation_key == operation_key
            )
        )
        if existing is not None:
            if existing.upload_request_digest != request_digest:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key 已用于不同的图片上传输入",
                )
            _register_owner(db, existing, x_session_id)
            db.commit()
            return _upload_response(existing)

    image = UploadedImage(
        task_id=task_id,
        image_type="floor_plan" if "户型" in (file.filename or "") else "room_photo",
        file_name=file.filename,
        file_size=len(content),
        content_digest=content_digest,
        upload_operation_key=operation_key,
        upload_request_digest=request_digest,
    )
    db.add(image)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if operation_key is None:
            raise
        existing = db.scalar(
            select(UploadedImage).where(
                UploadedImage.upload_operation_key == operation_key
            )
        )
        if existing is None or existing.upload_request_digest != request_digest:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key 已用于不同的图片上传输入",
            ) from exc
        _register_owner(db, existing, x_session_id)
        db.commit()
        return _upload_response(existing)

    # 原图登记与会话归属先原子提交，再写文件，防止识别期间暴露静态直链。
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = _safe_filename(Path(file.filename or "upload").stem)
    stored_name = f"{image.id}_{safe_stem}.{validated.extension}"
    image.file_url = f"/uploads/{stored_name}"
    _register_owner(db, image, x_session_id)
    db.commit()
    (upload_dir / stored_name).write_bytes(content)

    # Qwen3-VL 输出统一空间事实模型 RoomModel；不可用或结构无效时降级占位
    source = "vl"
    room_model = None
    vision_operation_key = f"vision:{image.id}:{content_digest}"
    governance = (
        model_call_governance_service.govern_task_model_calls(
            db,
            task_id=task_id,
            operation_key=vision_operation_key,
        )
        if task_id is not None
        else model_call_governance_service.govern_session_model_calls(
            db,
            session_id=x_session_id,
            operation_key=vision_operation_key,
        )
    )
    with (
        governance,
        llm_service.capture_model_call() as model_call,
    ):
        try:
            room_model = llm_service.analyze_room_model(content, file.filename or "")
        except LLMUnavailable as exc:
            logger.warning("图片分析降级到占位: %s", exc)
            source = "placeholder"

    billing_status, cost_cny = task_timeline_service.billing_for_model_call(
        attempted=model_call.attempted,
        usage=model_call.usage,
        input_price_per_mtok=settings.vl_input_price_per_mtok,
        output_price_per_mtok=settings.vl_output_price_per_mtok,
    )

    if room_model:
        # RoomModel 为 camelCase，转成 analysis_json 的 snake_case 兼容结构
        analysis = {
            "image_kind": room_model.get("imageKind"),
            "space_type": room_model.get("spaceType"),
            "room_count": room_model.get("roomCount"),
            "findings": room_model.get("analysisNotes") or [],
            "suggestions": room_model.get("suggestions") or [],
            "room_model": room_model,
        }
    else:
        source = "placeholder"
        analysis = llm_service.placeholder_image_analysis()

    # VL 判断的类型更准，覆盖按文件名的粗猜
    if analysis.get("image_kind") in ("floor_plan", "room_photo"):
        image.image_type = analysis["image_kind"]
    image.file_url = f"/uploads/{stored_name}"
    image.analysis_json = {**analysis, "source": source}
    image.analysis_model_call_attempted = model_call.attempted
    image.analysis_billing_status = billing_status
    image.analysis_cost_cny = cost_cny
    prediction_evidence_service.capture_uploaded_prediction(
        image,
        raw_room_model=room_model,
        source=source,
        model=settings.vl_model if source == "vl" else None,
    )
    if task_id is not None:
        task_timeline_service.project_visual_analysis(
            db,
            task_id=task_id,
            image=image,
        )
    require_active_session(db, x_session_id)
    if image.task_id is not None:
        require_owned_design_task(db, session_id=x_session_id, task_id=image.task_id)
    db.commit()

    return _upload_response(image)


@router.put("/images/{image_id}/room-model")
def calibrate_image_room_model(
    image_id: int,
    payload: RoomModelCalibrationRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    """用户校准 VL 识别出的主空间真实尺寸，写回该图片的 RoomModel。"""
    require_active_session(db, x_session_id)
    if not anonymous_session_service.session_owns_images(db, x_session_id, [image_id]):
        raise HTTPException(status_code=404, detail="图片不存在或不属于当前会话")

    image = db.get(UploadedImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="图片不存在")

    room_model_data = (image.analysis_json or {}).get("room_model")
    if not isinstance(room_model_data, dict):
        raise HTTPException(
            status_code=409,
            detail="该图片没有可校准的空间识别结果",
        )

    room_model = RoomModel.model_validate(room_model_data)
    try:
        calibrated = room_model_service.apply_calibration(
            room_model,
            room_id=payload.room_id,
            width_m=payload.width_m,
            depth_m=payload.depth_m,
            ceiling_height=payload.ceiling_height_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    calibrated_dict = calibrated.model_dump(by_alias=True, mode="json")

    analysis = dict(image.analysis_json or {})
    analysis["room_model"] = calibrated_dict
    # 文字观察与 RoomModel 保持一致（findings 兼容旧链路）
    analysis["findings"] = calibrated_dict.get("analysisNotes") or analysis.get(
        "findings", []
    )
    analysis["suggestions"] = calibrated_dict.get("suggestions") or analysis.get(
        "suggestions", []
    )
    image.analysis_json = analysis
    room_model_service.record_calibration_confirmations(
        db,
        image=image,
        original=room_model,
        calibrated=calibrated,
        confirmed_by_session_id=str(x_session_id),
        room_id=payload.room_id,
    )
    db.commit()

    return {"image_id": image.id, "room_model": calibrated_dict}
