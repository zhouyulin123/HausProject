"""Scene Agent 的确定性白名单工具；不执行模型生成的代码。"""

from datetime import datetime, timezone
from math import pi
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Product
from app.schemas.scene_agent import (
    AddSceneItem,
    MoveSceneItem,
    RemoveSceneItem,
    RotateSceneItem,
    SceneOperation,
)
from app.schemas.scenes import (
    PositiveVector3,
    SceneDocument,
    SceneItem,
    Transform,
    Vector3,
)
from app.services import catalog_service
from app.services.product_asset_service import product_asset_contract


class SceneToolError(ValueError):
    """白名单操作无法安全应用到当前场景。"""


class SceneCatalogEligibilityError(SceneToolError):
    """商品不满足统一商用目录资格，携带稳定机器可读原因。"""

    code = "catalog_product_ineligible"

    def __init__(self, *, sku: str, reason_codes: tuple[str, ...]) -> None:
        message = f"商品 {sku} 当前不可用于场景新增或正式交付"
        if "dimensions_missing" in reason_codes:
            message = f"商品 {sku} 缺少可靠的三维尺寸，不能加入场景"
        super().__init__(message)
        self.sku = sku
        self.reason_codes = reason_codes

    @property
    def details(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            "sku": self.sku,
            "reason_codes": list(self.reason_codes),
        }


def _normalize_rotation(value: float) -> float:
    return (value + pi) % (2 * pi) - pi


def _find_item(document: SceneDocument, instance_id: str) -> SceneItem:
    item = next(
        (candidate for candidate in document.items if candidate.instance_id == instance_id),
        None,
    )
    if item is None:
        raise SceneToolError(f"场景中不存在家具实例：{instance_id}")
    return item


def _safe_instance_stem(sku: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", sku).strip("-")
    return stem or "item"


def _next_instance_id(document: SceneDocument, sku: str) -> str:
    stem = _safe_instance_stem(sku)
    used = {item.instance_id for item in document.items}
    index = 1
    while f"item-{stem}-{index}" in used:
        index += 1
    return f"item-{stem}-{index}"


def _find_product(db: Session, sku: str) -> Product:
    normalized_sku = sku.strip().upper()
    product = db.scalar(
        select(Product).where(Product.sku == normalized_sku)
    )
    if product is None:
        raise SceneToolError(f"商品库中不存在 SKU：{normalized_sku}")
    return product


def _load_eligible_product(
    db: Session,
    sku: str,
    *,
    region: str | None = None,
    at: datetime | None = None,
) -> Product:
    product = _find_product(db, sku)
    eligibility = catalog_service.is_product_eligible(
        product,
        at=at,
        region=region,
    )
    if not eligibility.eligible:
        raise SceneCatalogEligibilityError(
            sku=product.sku or sku.strip().upper(),
            reason_codes=eligibility.reason_codes,
        )
    return product


def assert_catalog_skus_eligible(
    db: Session,
    skus: list[str],
    *,
    region: str | None = None,
) -> None:
    """按稳定顺序校验待新增或待交付 SKU。"""
    checked_at = datetime.now(timezone.utc)
    for sku in dict.fromkeys(skus):
        _load_eligible_product(db, sku, region=region, at=checked_at)


def _is_ceiling_anchored(product: Product) -> bool:
    spec = product.model_spec_json or {}
    installation = spec.get("安装参数") or {}
    return installation.get("锚点") == "ceiling"


def _vertical_center(
    document: SceneDocument,
    product: Product,
    dimensions: PositiveVector3,
) -> float:
    if _is_ceiling_anchored(product):
        return document.room.ceiling_height - dimensions.y / 2
    return dimensions.y / 2


def _hydrate_scene_items(db: Session, document: SceneDocument) -> None:
    """用商品库补齐 demo 场景缺失的类别、尺寸和垂直锚点。"""
    for item in document.items:
        if item.dimensions is not None and item.category:
            continue
        product = _find_product(db, item.sku)
        dimensions = (
            product.model_width_mm,
            product.model_height_mm,
            product.model_depth_mm,
        )
        if any(value is None or value <= 0 for value in dimensions):
            raise SceneToolError(
                f"商品 {item.sku} 缺少可靠的三维尺寸，不能编辑场景"
            )
        dimensions = PositiveVector3(
            x=product.model_width_mm / 1000,
            y=product.model_height_mm / 1000,
            z=product.model_depth_mm / 1000,
        )
        item.category = product.category
        item.dimensions = dimensions
        if _is_ceiling_anchored(product):
            item.transform.position.y = _vertical_center(
                document, product, dimensions
            )
        elif item.transform.position.y <= 0:
            item.transform.position.y = dimensions.y / 2


def apply_scene_operations(
    db: Session,
    source: SceneDocument,
    operations: list[SceneOperation],
    *,
    region: str | None = None,
) -> SceneDocument:
    """顺序执行已通过 Pydantic 鉴别联合校验的操作并返回新文档。"""
    document = source.model_copy(deep=True)
    _hydrate_scene_items(db, document)
    for operation in operations:
        if isinstance(operation, MoveSceneItem):
            item = _find_item(document, operation.instance_id)
            item.transform.position.x = operation.position.x
            item.transform.position.z = operation.position.z
            if item.dimensions is not None:
                product = _find_product(db, item.sku)
                scaled_dimensions = PositiveVector3(
                    x=item.dimensions.x * item.transform.scale.x,
                    y=item.dimensions.y * item.transform.scale.y,
                    z=item.dimensions.z * item.transform.scale.z,
                )
                item.transform.position.y = _vertical_center(
                    document,
                    product,
                    scaled_dimensions,
                )
        elif isinstance(operation, RotateSceneItem):
            item = _find_item(document, operation.instance_id)
            item.transform.rotation.y = _normalize_rotation(
                operation.rotation_y
            )
        elif isinstance(operation, RemoveSceneItem):
            _find_item(document, operation.instance_id)
            document.items = [
                item
                for item in document.items
                if item.instance_id != operation.instance_id
            ]
        elif isinstance(operation, AddSceneItem):
            product = _load_eligible_product(db, operation.sku, region=region)
            asset_contract = product_asset_contract(product)
            dimensions = PositiveVector3(
                x=product.model_width_mm / 1000,
                y=product.model_height_mm / 1000,
                z=product.model_depth_mm / 1000,
            )
            position_y = _vertical_center(document, product, dimensions)
            document.items.append(
                SceneItem(
                    instance_id=_next_instance_id(document, product.sku),
                    sku=product.sku,
                    category=product.category,
                    asset_mode=asset_contract["asset_mode"],
                    fallback_reason=asset_contract["fallback_reason"],
                    dimensions=dimensions,
                    transform=Transform(
                        position=Vector3(
                            x=operation.position.x,
                            y=position_y,
                            z=operation.position.z,
                        ),
                        rotation=Vector3(
                            x=0,
                            y=_normalize_rotation(operation.rotation_y),
                            z=0,
                        ),
                        scale=PositiveVector3(x=1, y=1, z=1),
                    ),
                )
            )
    return document


def build_scene_agent_context(
    db: Session,
    document: SceneDocument,
    *,
    region: str | None = None,
) -> dict:
    """只向模型暴露完成空间操作所需的最小商品与场景数据。"""
    products = db.scalars(
        select(Product)
        .where(
            Product.is_active.is_(True),
            Product.model_width_mm.is_not(None),
            Product.model_height_mm.is_not(None),
            Product.model_depth_mm.is_not(None),
        )
        .order_by(Product.sku)
    ).all()
    checked_at = datetime.now(timezone.utc)
    return {
        "scene": document.model_dump(by_alias=True, mode="json"),
        "catalog": [
            {
                "sku": product.sku,
                "name": product.name,
                "category": product.category,
                "dimensionsMm": {
                    "width": product.model_width_mm,
                    "height": product.model_height_mm,
                    "depth": product.model_depth_mm,
                },
            }
            for product in products
            if product.sku
            and catalog_service.is_product_eligible(
                product,
                at=checked_at,
                region=region,
            ).eligible
        ],
    }
