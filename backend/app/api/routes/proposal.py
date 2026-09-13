"""品牌提案 PDF 导出：方案 + 效果图 + 报价单合成一份可发客户的文件。"""

import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
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
from app.services import (
    pdf_service,
    plan_delivery_service,
    scene_service,
    shop_service,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(ge=1)
    plan_version_id: int = Field(ge=1)


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

    plan_version = scene_service.get_owned_plan_version(
        db,
        session_id=x_session_id,
        plan_version_id=req.plan_version_id,
    )
    if (
        plan_version is None
        or plan_version.revision.task_id != req.task_id
    ):
        raise HTTPException(status_code=404, detail="方案版本不存在")

    try:
        delivery_facts = plan_delivery_service.require_deliverable(plan_version)
    except plan_delivery_service.PlanDeliveryBlocked as exc:
        raise HTTPException(status_code=409, detail=exc.detail()) from exc

    plan = delivery_facts.plan_snapshot
    if not plan.get("name"):
        raise HTTPException(status_code=422, detail="服务端方案缺少名称")

    # 找该任务 + 方案最近一次生成的效果图作为提案封面
    effect_path: Optional[str] = None
    rendered = db.scalars(
        select(RenderedImage)
        .where(
            RenderedImage.task_id == req.task_id,
            RenderedImage.plan_version_id == req.plan_version_id,
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
        pdf_bytes = pdf_service.build_proposal_pdf(
            plan,
            effect_path,
            shop,
            quote_valid_until=delivery_facts.quote_valid_until,
            development_preview=delivery_facts.delivery_mode == "development_preview",
        )
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
