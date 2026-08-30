"""把现有活动商品整理为可人工维护的内部商品初稿。"""

from __future__ import annotations

import argparse
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Product


def _spec(width: int, height: int, depth: int, size: str) -> dict[str, Any]:
    return {
        "model_width_mm": width,
        "model_height_mm": height,
        "model_depth_mm": depth,
        "size": size,
    }


# 尺寸取自当前确定性 3D 规则的包围尺寸，统一采用 宽×深×高 的表达。
ACTIVE_DRAFT_SPECS = {
    "SF-001": _spec(2380, 760, 980, "宽2380×深980×高760mm"),
    "SF-002": _spec(2860, 790, 1680, "宽2860×深1680×高790mm（右转角）"),
    "SF-003": _spec(720, 790, 780, "宽720×深780×高790mm"),
    "CJ-001": _spec(1100, 360, 620, "宽1100×深620×高360mm"),
    "CJ-002": _spec(1210, 460, 800, "组合占地宽1210×深800×高460mm"),
    "DG-001": _spec(360, 1450, 360, "灯体宽360×深360×高1450mm"),
    "DT-001": _spec(2400, 10, 1600, "长2400×宽1600×厚10mm"),
    "CH-001": _spec(1960, 920, 2120, "外宽1960×外长2120×床头高920mm"),
    "CH-002": _spec(1980, 1030, 2200, "外宽1980×外长2200×床头高1030mm"),
    "CT-001": _spec(480, 520, 390, "宽480×深390×高520mm"),
    "DG-002": _spec(720, 1874, 300, "双灯组合宽720×深300×总高1874mm"),
    "CL-001": _spec(3628, 2756, 110, "展开宽3628×高2756×厚110mm"),
    "ZY-001": _spec(1350, 750, 1350, "直径1350×高750mm"),
    "ZY-002": _spec(1800, 750, 850, "长1800×宽850×高750mm"),
    "CY-001": _spec(460, 810, 535, "宽460×深535×高810mm"),
    "DG-003": _spec(750, 1744, 750, "灯体直径750×总高1744mm"),
    "SZ-001": _spec(1600, 1250, 750, "宽1600×深750×升降高750-1250mm"),
    "YZ-001": _spec(680, 1120, 650, "宽680×深650×高1120mm"),
    "SJ-001": _spec(1000, 1850, 320, "宽1000×深320×高1850mm"),
    "DT-002": _spec(2000, 13, 1400, "长2000×宽1400×厚13mm"),
    "HAUS-SOFA-003": _spec(2360, 760, 960, "宽2360×深960×高760mm"),
    "HAUS-SOFA-004": _spec(2280, 790, 900, "宽2280×深900×高790mm"),
    "HAUS-SOFA-005": _spec(2950, 780, 1700, "宽2950×深1700×高780mm（右转角）"),
    "HAUS-SOFA-006": _spec(1680, 800, 840, "宽1680×深840×高800mm"),
    "HAUS-COFFEE-003": _spec(1200, 360, 600, "宽1200×深600×高360mm"),
    "HAUS-COFFEE-004": _spec(1100, 360, 650, "宽1100×深650×高360mm"),
    "HAUS-COFFEE-005": _spec(900, 350, 900, "宽900×深900×高350mm"),
    "HAUS-COFFEE-006": _spec(1050, 340, 700, "宽1050×深700×高340mm"),
    "HAUS-DINING-003": _spec(1800, 750, 850, "长1800×宽850×高750mm"),
    "HAUS-DINING-004": _spec(1350, 750, 1350, "直径1350×高750mm"),
    "HAUS-DINING-005": _spec(1800, 750, 900, "长1800×宽900×高750mm"),
    "HAUS-DINING-006": _spec(1500, 750, 850, "常态长1500×宽850×高750mm（可伸缩）"),
    "HAUS-CHAIR-004": _spec(460, 810, 535, "宽460×深535×高810mm"),
    "HAUS-CHAIR-005": _spec(485, 790, 550, "宽485×深550×高790mm"),
    "HAUS-CHAIR-006": _spec(500, 800, 560, "宽500×深560×高800mm"),
    "HAUS-CHAIR-007": _spec(470, 800, 550, "宽470×深550×高800mm"),
    "HAUS-BED-004": _spec(1960, 920, 2120, "外宽1960×外长2120×床头高920mm"),
    "HAUS-BED-005": _spec(1980, 1040, 2200, "外宽1980×外长2200×床头高1040mm"),
    "HAUS-BED-006": _spec(1940, 980, 2140, "外宽1940×外长2140×床头高980mm"),
    "HAUS-BED-007": _spec(1960, 980, 2180, "外宽1960×外长2180×床头高980mm"),
}

DRAFT_PRICE_NOTE = "内部参考零售价，待人工复核；不含配送、安装和选配费用。"


def validate_draft_specs(
    specs: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    if not specs:
        raise ValueError("商品初稿规格不能为空")
    for sku, spec in specs.items():
        if not isinstance(sku, str) or not sku.strip():
            raise ValueError("商品初稿 SKU 不能为空")
        for field in ("model_width_mm", "model_height_mm", "model_depth_mm"):
            value = spec.get(field)
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{sku} 的 {field} 必须是正整数")
        size = spec.get("size")
        if not isinstance(size, str) or not size.strip() or "详见" in size:
            raise ValueError(f"{sku} 必须提供明确尺寸文本")
    return specs


def compile_active_products(
    db: Session,
    *,
    strict: bool = True,
    commit: bool = True,
) -> dict[str, int]:
    """整理已存在的目标 SKU，不创建商品，也不触碰名单外记录。"""
    specs = validate_draft_specs(ACTIVE_DRAFT_SPECS)
    active_products = db.scalars(
        select(Product).where(Product.is_active.is_(True))
    ).all()
    by_sku = {product.sku: product for product in active_products if product.sku}
    missing_skus = sorted(set(specs) - set(by_sku))
    skipped = len([sku for sku in by_sku if sku not in specs])
    if strict and missing_skus:
        db.rollback()
        raise ValueError(
            f"活动商品库缺少 {len(missing_skus)} 个目标 SKU：{', '.join(missing_skus)}"
        )

    updated = 0
    try:
        for sku, spec in specs.items():
            product = by_sku.get(sku)
            if product is None:
                continue
            product.model_width_mm = spec["model_width_mm"]
            product.model_height_mm = spec["model_height_mm"]
            product.model_depth_mm = spec["model_depth_mm"]
            product.size = spec["size"]
            product.data_origin = "merchant_draft"
            product.source_name = "内部商品初稿"
            product.source_url = None
            product.source_product_id = sku
            product.source_retrieved_at = None
            product.price_observed_at = None
            product.price_note = DRAFT_PRICE_NOTE
            product.source_metadata = {
                **(product.source_metadata or {}),
                "catalog_version": "2026-08-30",
                "verification_status": "pending_manual_review",
                "dimension_basis": "现有确定性3D模型包围尺寸",
                "price_basis": "当前内部参考价",
                "editable_fields": ["name", "material", "price", "price_max", "size"],
            }
            updated += 1

        if commit:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    return {"updated": updated, "skipped": skipped, "missing": len(missing_skus)}


def main() -> None:
    parser = argparse.ArgumentParser(description="整理现有 40 条活动商品为内部商品初稿")
    parser.add_argument("--dry-run", action="store_true", help="只校验和预览，不写入数据库")
    args = parser.parse_args()

    with SessionLocal() as db:
        result = compile_active_products(db, commit=not args.dry_run)
    action = "校验通过" if args.dry_run else "整理完成"
    print(
        f"{action}：更新 {result['updated']} 条，"
        f"跳过 {result['skipped']} 条，缺少 {result['missing']} 条"
    )


if __name__ == "__main__":
    main()
