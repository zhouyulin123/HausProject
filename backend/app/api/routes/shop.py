"""店铺设置接口：读取 / 更新店铺信息 + logo 上传。"""

import re
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import require_factory
from app.core.config import settings
from app.db.database import get_db
from app.db.models import User
from app.services import shop_service

router = APIRouter()


class ShopUpdate(BaseModel):
    shop_name: Optional[str] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    address: Optional[str] = None
    slogan: Optional[str] = None
    logo_url: Optional[str] = None


@router.get("")
def get_shop(db: Session = Depends(get_db)):
    return shop_service.to_dict(shop_service.get_or_create(db))


@router.put("")
def update_shop(
    data: ShopUpdate,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    shop = shop_service.get_or_create(db)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(shop, k, v)
    db.commit()
    db.refresh(shop)
    return shop_service.to_dict(shop)


@router.post("/logo")
async def upload_logo(
    file: UploadFile = File(...),
    _user: User = Depends(require_factory),
):
    content = await file.read()
    upload_dir = Path(settings.upload_dir) / "shop"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]", "_", file.filename or "logo.png")
    fname = f"logo_{int(time.time())}_{safe}"
    (upload_dir / fname).write_bytes(content)
    return {"logo_url": f"/uploads/shop/{fname}"}
