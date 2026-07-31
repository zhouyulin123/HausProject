"""Scene Agent 的确定性白名单工具；不执行模型生成的代码。"""

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


class SceneToolError(ValueError):
    """白名单操作无法安全应用到当前场景。"""


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


def _load_product(db: Session, sku: str) -> Product:
    product = db.scalar(
        select(Product).where(
            Product.sku == sku,
            Product.is_active.is_(True),
        )
    )
    if product is None:
        raise SceneToolError(f"商品库中不存在可用 SKU：{sku}")
    dimensions = (
        product.model_width_mm,
        product.model_height_mm,
        product.model_depth_mm,
    )
    if any(value is None or value <= 0 for value in dimensions):
        raise SceneToolError(f"商品 {sku} 缺少可靠的三维尺寸，不能加入场景")
    return product


def apply_scene_operations(
    db: Session,
    source: SceneDocument,
    operations: list[SceneOperation],
) -> SceneDocument:
    """顺序执行已通过 Pydantic 鉴别联合校验的操作并返回新文档。"""
    document = source.model_copy(deep=True)
    for operation in operations:
        if isinstance(operation, MoveSceneItem):
            item = _find_item(document, operation.instance_id)
            item.transform.position.x = operation.position.x
            item.transform.position.z = operation.position.z
            if item.dimensions is not None:
                item.transform.position.y = (
                    item.dimensions.y * item.transform.scale.y / 2
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
            product = _load_product(db, operation.sku)
            dimensions = PositiveVector3(
                x=product.model_width_mm / 1000,
                y=product.model_height_mm / 1000,
                z=product.model_depth_mm / 1000,
            )
            document.items.append(
                SceneItem(
                    instance_id=_next_instance_id(document, product.sku),
                    sku=product.sku,
                    category=product.category,
                    dimensions=dimensions,
                    transform=Transform(
                        position=Vector3(
                            x=operation.position.x,
                            y=dimensions.y / 2,
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


def build_scene_agent_context(db: Session, document: SceneDocument) -> dict:
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
        ],
    }
