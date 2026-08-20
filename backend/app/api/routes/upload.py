import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_active_session
from app.core.config import settings
from app.db.database import get_db
from app.db.models import UploadedImage
from app.schemas.room_model import RoomModel, RoomModelCalibrationRequest
from app.services import anonymous_session_service, llm_service, room_model_service
from app.services.llm_service import LLMUnavailable
from app.services.upload_validation import UploadValidationError, validate_image_upload

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w.一-鿿-]", "_", name or "upload")


@router.post("/image")
async def upload_image(
    x_session_id: SessionIdHeader,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)

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

    image = UploadedImage(
        image_type="floor_plan" if "户型" in (file.filename or "") else "room_photo",
        file_name=file.filename,
        file_size=len(content),
    )
    db.add(image)
    db.commit()
    db.refresh(image)

    # 保存到本地 uploads 目录，通过 /uploads 静态路由访问
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = _safe_filename(Path(file.filename or "upload").stem)
    stored_name = f"{image.id}_{safe_stem}.{validated.extension}"
    (upload_dir / stored_name).write_bytes(content)

    # Qwen3-VL 输出统一空间事实模型 RoomModel；不可用或结构无效时降级占位
    source = "vl"
    room_model = None
    try:
        room_model = llm_service.analyze_room_model(content, file.filename or "")
    except LLMUnavailable as exc:
        logger.warning("图片分析降级到占位: %s", exc)
        source = "placeholder"

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
        analysis = llm_service.placeholder_image_analysis()

    # VL 判断的类型更准，覆盖按文件名的粗猜
    if analysis.get("image_kind") in ("floor_plan", "room_photo"):
        image.image_type = analysis["image_kind"]
    image.file_url = f"/uploads/{stored_name}"
    image.analysis_json = {**analysis, "source": source}
    db.commit()
    anonymous_session_service.attach_image(db, x_session_id, image.id)

    return {
        "image_id": image.id,
        "image_url": image.file_url,
        "file_name": image.file_name,
        "file_size": image.file_size,
        "analysis": {
            "findings": analysis.get("findings", []),
            "suggestions": analysis.get("suggestions", []),
            "space_type": analysis.get("space_type", ""),
            "room_count": analysis.get("room_count", ""),
            "source": source,
            "room_model": room_model,
        },
    }


@router.put("/images/{image_id}/room-model")
def calibrate_image_room_model(
    image_id: int,
    payload: RoomModelCalibrationRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    """用户校准 VL 识别出的主空间真实尺寸，写回该图片的 RoomModel。"""
    require_active_session(db, x_session_id)
    if not anonymous_session_service.session_owns_images(
        db, x_session_id, [image_id]
    ):
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
    calibrated = room_model_service.apply_calibration(
        room_model,
        room_id=payload.room_id,
        width_m=payload.width_m,
        depth_m=payload.depth_m,
        ceiling_height=payload.ceiling_height_m,
    )
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
    db.commit()

    return {"image_id": image.id, "room_model": calibrated_dict}
