import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.db.models import UploadedImage
from app.services import llm_service
from app.services.llm_service import LLMUnavailable
from app.services.upload_validation import UploadValidationError, validate_image_upload

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w.一-鿿-]", "_", name or "upload")


@router.post("/image")
async def upload_image(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
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

    # Qwen3-VL 真实空间识别；不可用时降级占位
    source = "vl"
    try:
        analysis = llm_service.analyze_image(content, file.filename or "")
    except LLMUnavailable as exc:
        logger.warning("图片分析降级到占位: %s", exc)
        source = "placeholder"
        analysis = llm_service.placeholder_image_analysis()

    # VL 判断的类型更准，覆盖按文件名的粗猜
    if analysis.get("image_kind") in ("floor_plan", "room_photo"):
        image.image_type = analysis["image_kind"]
    image.file_url = f"/uploads/{stored_name}"
    image.analysis_json = {**analysis, "source": source}
    db.commit()

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
        },
    }
