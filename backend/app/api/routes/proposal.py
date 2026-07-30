"""品牌提案 PDF 导出：方案 + 效果图 + 报价单合成一份可发客户的文件。"""

import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    SessionIdHeader,
    require_active_session,
    require_owned_design_task,
)
from app.core.config import settings
from app.db.database import get_db
from app.db.models import RenderedImage
from app.services import design_version_service, pdf_service, shop_service

logger = logging.getLogger(__name__)
router = APIRouter()


class ProposalRequest(BaseModel):
    task_id: int
    plan_id: str


@router.post("/proposal-pdf")
def export_proposal_pdf(
    req: ProposalRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=req.task_id,
    )

    plan_version = design_version_service.get_latest_plan(
        db,
        task_id=req.task_id,
        plan_key=req.plan_id,
    )
    if plan_version is None:
        raise HTTPException(status_code=404, detail="方案不存在")

    plan = plan_version.plan_json
    if not plan.get("name"):
        raise HTTPException(status_code=422, detail="服务端方案缺少名称")

    # 找该任务 + 方案最近一次生成的效果图作为提案封面
    effect_path: Optional[str] = None
    if plan.get("id"):
        rendered = db.scalars(
            select(RenderedImage)
            .where(
                RenderedImage.task_id == req.task_id,
                RenderedImage.plan_id == req.plan_id,
            )
            .order_by(RenderedImage.id.desc())
        ).first()
        if rendered and rendered.image_url:
            candidate = Path(settings.upload_dir) / Path(rendered.image_url).name
            if candidate.exists():
                effect_path = str(candidate)

    # 店铺信息（含 logo 本地路径解析）
    shop = shop_service.to_dict(shop_service.get_or_create(db))
    if shop.get("logo_url"):
        logo_file = Path(settings.upload_dir) / "shop" / Path(shop["logo_url"]).name
        if logo_file.exists():
            shop["_logo_path"] = str(logo_file)

    try:
        pdf_bytes = pdf_service.build_proposal_pdf(plan, effect_path, shop)
    except Exception as exc:
        logger.exception("提案 PDF 生成失败")
        raise HTTPException(status_code=500, detail=f"PDF 生成失败: {exc}")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    fname = (
        f"proposal_{req.task_id}_{plan_version.id}_{int(time.time())}.pdf"
    )
    (upload_dir / fname).write_bytes(pdf_bytes)

    return {
        "pdf_url": f"/uploads/{fname}",
        "filename": fname,
        "has_effect_image": bool(effect_path),
    }
