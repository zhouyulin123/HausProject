"""把方案商品与空间事实组装成布局生成器输入的桥接层。

职责：
1. build_layout_furniture —— 从方案的 furnitureSuggestions + Product 真实三维尺寸
   组装 LayoutFurniture（无 model 尺寸时按类别默认尺寸兜底）。
2. room_geometry_from_plan_version —— 从任务图片的 RoomModel 解析房间几何与门窗，
   缺省时用空间类型默认尺寸构造矩形房间。
3. record_layout_run —— 把每次布局生成的元数据写入 layout_runs。
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignSceneVersion,
    LayoutRun,
    Product,
    UploadedImage,
)
from app.schemas.scenes import Opening, RoomGeometry, SceneDocument, Vector2XZ
from app.services.layout_evaluator import LayoutScore
from app.services.layout_generator import LayoutFurniture
from app.services.room_model_service import room_model_from_analysis

# 类别默认占地（米）[宽, 深]，与前端 roomLayout.ts 的 CATEGORY_FOOTPRINT 对齐
_CATEGORY_FOOTPRINT: dict[str, tuple[float, float]] = {
    "沙发": (2.2, 0.95),
    "茶几": (1.0, 0.55),
    "柜子": (1.6, 0.4),
    "床": (1.8, 2.0),
    "餐桌": (1.3, 0.8),
    "餐椅": (0.5, 0.5),
    "书桌": (1.4, 0.7),
    "书椅": (0.6, 0.6),
    "灯具": (0.4, 0.4),
    "窗帘": (1.6, 0.1),
    "地毯": (2.0, 2.9),
}
# 类别默认高度（米）
_CATEGORY_HEIGHT: dict[str, float] = {
    "沙发": 0.85,
    "茶几": 0.42,
    "柜子": 1.9,
    "床": 0.5,
    "餐桌": 0.75,
    "餐椅": 0.9,
    "书桌": 0.75,
    "书椅": 0.95,
    "灯具": 1.5,
    "窗帘": 2.4,
    "地毯": 0.02,
}

# 空间类型默认尺寸（米）[宽, 深]，对齐前端 ROOM_SIZE
_DEFAULT_ROOM_SIZE: dict[str, tuple[float, float]] = {
    "客厅": (4.6, 5.6),
    "卧室": (3.6, 4.2),
    "餐厅": (3.6, 3.8),
    "书房": (3.0, 3.6),
    "厨房": (2.8, 3.6),
    "儿童房": (3.2, 3.8),
}


def build_layout_furniture(
    db: Session,
    furniture_suggestions: list[dict] | None,
) -> list[LayoutFurniture]:
    """把方案家具建议 + 商品库真实尺寸转成布局生成器输入。"""
    suggestions = furniture_suggestions or []
    if not suggestions:
        return []

    skus = [
        item.get("sku") or item.get("id")
        for item in suggestions
        if item.get("sku") or item.get("id")
    ]
    products = db.scalars(
        select(Product).where(
            Product.sku.in_(skus),
            Product.is_active.is_(True),
        )
    ).all() if skus else []
    by_sku = {product.sku: product for product in products if product.sku}

    result: list[LayoutFurniture] = []
    for item in suggestions:
        sku = item.get("sku") or item.get("id")
        if not sku:
            continue
        product = by_sku.get(sku)
        category = (product.category if product else None) or str(
            item.get("category") or ""
        )
        name = product.name if product else str(item.get("name") or sku)
        if (
            product
            and product.model_width_mm
            and product.model_depth_mm
            and product.model_height_mm
        ):
            result.append(
                LayoutFurniture(
                    sku=sku,
                    name=name,
                    category=category,
                    width_m=product.model_width_mm / 1000,
                    depth_m=product.model_depth_mm / 1000,
                    height_m=product.model_height_mm / 1000,
                )
            )
        else:
            width, depth = _CATEGORY_FOOTPRINT.get(category, (1.0, 0.8))
            height = _CATEGORY_HEIGHT.get(category, 0.8)
            result.append(
                LayoutFurniture(
                    sku=sku,
                    name=name,
                    category=category,
                    width_m=width,
                    depth_m=depth,
                    height_m=height,
                )
            )
    return result


def _room_geometry_from_task(
    db: Session,
    task_id: int,
) -> tuple[RoomGeometry, list[Opening]] | None:
    """从任务关联图片的 RoomModel 解析米制房间几何与门窗。"""
    from app.services.room_model_service import room_model_to_scene

    images = db.scalars(
        select(UploadedImage).where(UploadedImage.task_id == task_id)
    ).all()
    for image in images:
        room_model = room_model_from_analysis(image.analysis_json or {})
        if room_model is None:
            continue
        try:
            scene = room_model_to_scene(room_model)
            return scene.room, scene.openings
        except Exception:
            continue
    return None


def room_geometry_from_plan_version(
    db: Session,
    plan_version: DesignPlanVersion,
) -> tuple[RoomGeometry, list[Opening]] | None:
    """从方案版本所在任务的图片 RoomModel 解析房间几何。"""
    revision = db.get(DesignRevision, plan_version.revision_id)
    if revision is None:
        return None
    return _room_geometry_from_task(db, revision.task_id)


def default_room_geometry(room_name: str = "客厅") -> tuple[RoomGeometry, list[Opening]]:
    """无户型图/无 RoomModel 时，按空间类型默认尺寸构造矩形房间。"""
    width, depth = _DEFAULT_ROOM_SIZE.get(room_name, (4.4, 5.2))
    half_w = width / 2
    half_d = depth / 2
    room = RoomGeometry(
        id="room-default",
        name=room_name,
        floor_polygon=[
            Vector2XZ(x=-half_w, z=-half_d),
            Vector2XZ(x=half_w, z=-half_d),
            Vector2XZ(x=half_w, z=half_d),
            Vector2XZ(x=-half_w, z=half_d),
        ],
        ceiling_height=2.8,
    )
    return room, []


def record_layout_run(
    db: Session,
    *,
    plan_version_id: int,
    scene_version_id: int | None,
    room: RoomGeometry,
    furniture: list[LayoutFurniture],
    results: list[tuple["object", LayoutScore]],
    duration_ms: int | None = None,
    source: str = "auto_layout",
) -> LayoutRun | None:
    """把一次布局生成的元数据写入 layout_runs（供质量监控与失败反推）。"""
    if not results:
        return None
    best_scene, best_score = results[0]
    xs = [p.x for p in room.floor_polygon]
    zs = [p.z for p in room.floor_polygon]
    run = LayoutRun(
        plan_version_id=plan_version_id,
        scene_version_id=scene_version_id,
        room_name=room.name,
        room_width_m=max(xs) - min(xs),
        room_depth_m=max(zs) - min(zs),
        furniture_count=len(furniture),
        candidate_count=len(results),
        best_score=best_score.total,
        best_valid=best_score.valid,
        issue_codes=[issue.code for issue in best_score.issues],
        duration_ms=duration_ms,
        source=source,
    )
    db.add(run)
    return run


# ---------------------------------------------------------------- 用户修改行为反推

def diff_scene_items(
    before: SceneDocument,
    after: SceneDocument,
) -> list[dict]:
    """对比两个场景文档的家具实例，输出逐实例差异（位移/旋转/增删）。"""
    before_items = {item.instance_id: item for item in before.items}
    after_items = {item.instance_id: item for item in after.items}
    diffs: list[dict] = []

    for instance_id in sorted(before_items.keys() | after_items.keys()):
        old = before_items.get(instance_id)
        new = after_items.get(instance_id)
        if old is None and new is not None:
            diffs.append(
                {
                    "instance_id": instance_id,
                    "sku": new.sku,
                    "category": new.category,
                    "kind": "added",
                    "distance": None,
                    "rotation_delta": None,
                }
            )
        elif old is not None and new is None:
            diffs.append(
                {
                    "instance_id": instance_id,
                    "sku": old.sku,
                    "category": old.category,
                    "kind": "removed",
                    "distance": None,
                    "rotation_delta": None,
                }
            )
        else:
            distance = math.hypot(
                new.transform.position.x - old.transform.position.x,
                new.transform.position.z - old.transform.position.z,
            )
            raw_delta = new.transform.rotation.y - old.transform.rotation.y
            rotation_delta = abs((raw_delta + math.pi) % (2 * math.pi) - math.pi)
            if distance > 1e-6 or rotation_delta > 1e-3:
                diffs.append(
                    {
                        "instance_id": instance_id,
                        "sku": new.sku,
                        "category": new.category,
                        "kind": "moved",
                        "distance": round(distance, 4),
                        "rotation_delta": round(rotation_delta, 4),
                    }
                )
    return diffs


def summarize_edits(diffs: list[dict]) -> dict:
    """把逐实例差异聚合成失败类型信号（改动最多的类别即布局薄弱点）。"""
    moved = [d for d in diffs if d["kind"] == "moved"]
    by_category: dict[str, list[float]] = {}
    for diff in moved:
        key = diff["category"] or diff["sku"]
        if diff["distance"] is not None:
            by_category.setdefault(key, []).append(diff["distance"])

    top = sorted(
        by_category.items(),
        key=lambda item: (len(item[1]), sum(item[1])),
        reverse=True,
    )
    return {
        "moved_count": len(moved),
        "removed_count": sum(1 for d in diffs if d["kind"] == "removed"),
        "added_count": sum(1 for d in diffs if d["kind"] == "added"),
        "top_moved_categories": [
            {
                "category": category,
                "count": len(distances),
                "avg_distance_m": round(sum(distances) / len(distances), 4),
            }
            for category, distances in top
        ],
    }


def analyze_manual_edits(db: Session, scene: DesignScene) -> dict:
    """对比 auto_layout 初稿与最新手动修改版本，反推布局失败类型。"""
    versions = db.scalars(
        select(DesignSceneVersion)
        .where(DesignSceneVersion.scene_id == scene.id)
        .order_by(DesignSceneVersion.version)
    ).all()
    auto_version = next(
        (v for v in versions if v.source == "auto_layout"), None
    )
    manual_versions = [v for v in versions if v.source == "manual"]
    if auto_version is None or not manual_versions:
        return {
            "edited": False,
            "reason": "缺少 auto_layout 初稿或用户手动修改",
        }

    before = SceneDocument.model_validate(auto_version.scene_json)
    after = SceneDocument.model_validate(manual_versions[-1].scene_json)
    diffs = diff_scene_items(before, after)
    summary = summarize_edits(diffs)
    summary["edited"] = True
    summary["from_version"] = auto_version.version
    summary["to_version"] = manual_versions[-1].version
    return summary

