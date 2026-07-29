"""店铺信息读写：单行 shop_settings，首次访问用 .env 默认值播种。"""

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ShopSetting


def get_or_create(db: Session) -> ShopSetting:
    shop = db.get(ShopSetting, 1)
    if shop is None:
        shop = ShopSetting(
            id=1,
            shop_name=settings.shop_name,
            phone=settings.shop_phone or None,
            wechat=settings.shop_wechat or None,
            address=settings.shop_address or None,
            slogan=settings.shop_slogan or None,
        )
        db.add(shop)
        db.commit()
        db.refresh(shop)
    return shop


def to_dict(shop: ShopSetting) -> Dict[str, Any]:
    return {
        "shop_name": shop.shop_name,
        "phone": shop.phone,
        "wechat": shop.wechat,
        "address": shop.address,
        "slogan": shop.slogan,
        "logo_url": shop.logo_url,
    }
