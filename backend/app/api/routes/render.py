"""效果图生成接口（本地 SD1.5 + ControlNet，按需触发）。"""

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    SessionIdHeader,
    require_active_session,
    require_owned_design_task,
)
from app.core.config import settings
from app.db.database import get_db
from app.db.models import DesignTask, RenderedImage, UploadedImage
from app.schemas.tasks import RenderRequest, RenderResponse
from app.services import sd_service
from app.services.sd_service import SDUnavailable

logger = logging.getLogger(__name__)
router = APIRouter()

# 中文风格/空间 → 英文 prompt 片段（SD 对英文响应更好）
_STYLE_MAP = {
    "奶油": "cream style, soft beige and off-white tones",
    "原木": "natural wood, light oak furniture, warm wood tones",
    "现代简约": "modern minimalist, clean lines",
    "简约": "modern minimalist, clean lines",
    "轻奢": "light luxury, marble and brass accents, elegant",
    "侘寂": "japandi wabi-sabi style, muji, textured plaster",
    "日式": "japandi style, muji, natural materials",
    "北欧": "scandinavian nordic style, bright and airy",
    "中古": "mid-century modern style, vintage furniture",
    "法式": "french vintage style, molding, arched details",
    "工业": "industrial loft style, exposed brick and metal",
}

_ROOM_MAP = {
    "客厅": "living room",
    "卧室": "bedroom",
    "厨房": "kitchen",
    "餐厅": "dining room",
    "书房": "study room, home office",
    "儿童房": "children's room",
    "卫生间": "bathroom",
    "阳台": "balcony",
    "衣帽间": "walk-in closet",
    "玄关": "entryway",
    "全屋": "living room",
}


def _build_prompt(style: str, room_type: str) -> str:
    style_en = next(
        (v for k, v in _STYLE_MAP.items() if k in style), "modern cozy interior"
    )
    room_en = _ROOM_MAP.get(room_type, "living room")
    return f"a {room_en}, {style_en}, well decorated, furnished"


def _room_type_from_task(task: DesignTask) -> str:
    req = task.confirmed_requirement_json or {}
    rooms = req.get("rooms") or []
    return rooms[0] if rooms else "客厅"


@router.post("", response_model=RenderResponse)
def render_effect(
    req: RenderRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    if req.task_id is not None:
        require_owned_design_task(
            db,
            session_id=x_session_id,
            task_id=req.task_id,
        )

    if not sd_service.is_available():
        raise HTTPException(status_code=503, detail="效果图生成服务未启用")

    room_type = req.room_type
    room_bytes = None

    if req.task_id:
        task = db.get(DesignTask, req.task_id)
        if task:
            if not room_type:
                room_type = _room_type_from_task(task)
            # 取该任务下第一张有落地文件的房间图作为结构参考
            for img in db.scalars(
                select(UploadedImage).where(UploadedImage.task_id == req.task_id)
            ):
                if not img.file_url:
                    continue
                fpath = Path(settings.upload_dir) / Path(img.file_url).name
                if fpath.exists():
                    room_bytes = fpath.read_bytes()
                    break

    prompt = _build_prompt(req.style, room_type or "客厅")

    try:
        png_bytes, mode = sd_service.render_effect_image(prompt, room_bytes)
    except SDUnavailable as exc:
        logger.warning("效果图生成失败: %s", exc)
        raise HTTPException(status_code=503, detail=f"效果图生成失败: {exc}")

    # 落地保存 + 静态访问
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    fname = f"render_{req.task_id or 0}_{req.plan_id}_{int(time.time())}.png"
    (upload_dir / fname).write_bytes(png_bytes)
    image_url = f"/uploads/{fname}"

    db.add(
        RenderedImage(
            task_id=req.task_id,
            plan_id=req.plan_id,
            prompt=prompt,
            image_url=image_url,
            mode=mode,
        )
    )
    db.commit()

    return RenderResponse(image_url=image_url, mode=mode, source="sd")
