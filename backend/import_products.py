# -*- coding: utf-8 -*-
"""从 Excel 导入自家产品到商品库。

用法：
    python import_products.py --template          # 生成空白模板 products_import.xlsx
    python import_products.py products_import.xlsx  # 导入（按 SKU 去重：已存在则更新，否则新增）

Excel 有两个工作表：
    「成品家具」：sku, 名称, 类别, 空间, 风格, 材质, 价格, 价格上限, 尺寸, 卖点, 替代选择
    「定制报价」：项目名, 分类, 计价单位, 材料档位, 单价, 说明
"""

import sys
from typing import Any, Iterable, Sequence

from openpyxl import Workbook, load_workbook

from app.db.database import Base, SessionLocal, engine
from app.db.models import CustomQuoteRule, Product

PRODUCT_HEADERS = [
    "sku", "名称", "类别", "空间", "风格", "材质", "参考价", "价格上限",
    "尺寸", "宽(mm)", "深(mm)", "高(mm)", "卖点", "替代选择",
    "启用状态", "人工复核状态", "价格备注",
]
RULE_HEADERS = ["项目名", "分类", "计价单位", "材料档位", "单价", "说明"]

TEMPLATE_FILE = "products_import.xlsx"


def make_template() -> None:
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "商品主表"
    ws1.append(PRODUCT_HEADERS)
    ws1.append([
        "SF-100", "示例：三人位布艺沙发", "沙发", "客厅", "奶油风",
        "科技布", 4999, 6999, "宽2400×深1000×高780mm", 2400, 1000, 780,
        "耐抓易清洁，宠物家庭首选", "棉麻款（低 500 元）", "是", "待复核",
        "内部参考零售价，待人工复核",
    ])
    ws2 = wb.create_sheet("定制报价")
    ws2.append(RULE_HEADERS)
    ws2.append(["定制衣柜", "柜类定制", "㎡", "E0 颗粒板", 680, "投影面积计价，含基础五金"])
    for ws in (ws1, ws2):
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 16
    wb.save(TEMPLATE_FILE)
    print(f"模板已生成: {TEMPLATE_FILE}（示例行导入时会一并写入，请替换/删除）")


def _cell(row, idx):
    v = row[idx] if idx < len(row) else None
    if isinstance(v, str):
        v = v.strip()
    return v if v not in ("", None) else None


def _positive_int(value: Any, label: str, *, required: bool = False) -> int | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{label}不能为空")
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if number <= 0:
        raise ValueError(f"{label}必须大于 0")
    return number


def _controlled_value(value: Any, label: str, mapping: dict[str, Any]) -> Any:
    normalized = str(value).strip() if value not in (None, "") else ""
    if normalized not in mapping:
        raise ValueError(f"{label}只能是：{', '.join(mapping)}")
    return mapping[normalized]


def parse_product_row(
    headers: Sequence[Any],
    row: Sequence[Any],
) -> dict[str, Any] | None:
    """按表头解析一行，兼容旧版“价格”列和新版商品主表。"""
    normalized_headers = [str(header).strip() if header is not None else "" for header in headers]
    if len(set(normalized_headers)) != len(normalized_headers):
        raise ValueError("商品主表存在重复表头")
    cells = {
        header: _cell(row, index)
        for index, header in enumerate(normalized_headers)
        if header
    }
    if not cells.get("名称"):
        return None
    if not cells.get("sku"):
        raise ValueError("sku不能为空")

    product: dict[str, Any] = {"sku": str(cells["sku"]).strip()}
    text_fields = {
        "名称": "name",
        "类别": "category",
        "空间": "room",
        "风格": "style",
        "材质": "material",
        "尺寸": "size",
        "卖点": "selling_point",
        "替代选择": "alternative",
        "价格备注": "price_note",
    }
    for header, field in text_fields.items():
        if header in cells:
            product[field] = cells[header]

    price_header = "参考价" if "参考价" in cells else "价格"
    if price_header in cells:
        product["price"] = _positive_int(cells[price_header], price_header, required=True)
    if "价格上限" in cells:
        product["price_max"] = _positive_int(cells["价格上限"], "价格上限")
    for header, field in {
        "宽(mm)": "model_width_mm",
        "深(mm)": "model_depth_mm",
        "高(mm)": "model_height_mm",
    }.items():
        if header in cells and cells[header] is not None:
            product[field] = _positive_int(cells[header], header)

    if "启用状态" in cells:
        product["is_active"] = _controlled_value(
            cells["启用状态"], "启用状态", {"是": True, "否": False}
        )
    review_status = _controlled_value(
        cells.get("人工复核状态", "待复核"),
        "人工复核状态",
        {"待复核": "pending_manual_review", "已复核": "manual_verified"},
    )
    return {"product": product, "review_status": review_status}


def upsert_product_rows(
    db,
    headers: Sequence[Any],
    rows: Iterable[Sequence[Any]],
) -> dict[str, int]:
    """整批校验后按 SKU 回写，拒绝覆盖官网公开参考商品。"""
    parsed_rows = []
    skipped = 0
    for row_number, row in enumerate(rows, start=2):
        try:
            parsed = parse_product_row(headers, row)
        except ValueError as exc:
            raise ValueError(f"商品主表第 {row_number} 行：{exc}") from exc
        if parsed is None:
            skipped += 1
        else:
            parsed_rows.append(parsed)

    skus = [parsed["product"]["sku"] for parsed in parsed_rows]
    if len(skus) != len(set(skus)):
        raise ValueError("商品主表存在重复 SKU")
    existing = {
        product.sku: product
        for product in db.query(Product).filter(Product.sku.in_(skus)).all()
    }
    conflicts = [
        sku for sku, product in existing.items()
        if product.data_origin == "public_reference"
    ]
    if conflicts:
        db.rollback()
        raise ValueError(f"拒绝覆盖公开参考商品：{', '.join(sorted(conflicts))}")

    result = {"added": 0, "updated": 0, "skipped": skipped}
    try:
        for parsed in parsed_rows:
            data = parsed["product"]
            sku = data["sku"]
            product = existing.get(sku)
            if product is None:
                required = [field for field in ("name", "category", "room", "style", "price") if not data.get(field)]
                if required:
                    raise ValueError(f"新增商品 {sku} 缺少字段：{', '.join(required)}")
                product = Product(**data)
                db.add(product)
                result["added"] += 1
            else:
                for field, value in data.items():
                    setattr(product, field, value)
                result["updated"] += 1

            product.data_origin = "merchant_draft"
            product.source_name = "内部商品主表"
            product.source_url = None
            product.source_product_id = sku
            product.source_metadata = {
                **(product.source_metadata or {}),
                "verification_status": parsed["review_status"],
                "workbook_schema": "catalog-v1",
                "editable_fields": ["name", "material", "price", "price_max", "size"],
            }
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def import_file(path: str) -> None:
    Base.metadata.create_all(bind=engine)
    wb = load_workbook(path, data_only=True)
    db = SessionLocal()
    added = updated = rules_added = 0
    try:
        product_sheet_name = next(
            (name for name in ("商品主表", "成品家具") if name in wb.sheetnames),
            None,
        )
        if product_sheet_name:
            rows = wb[product_sheet_name].iter_rows(values_only=True)
            headers = next(rows)
            product_result = upsert_product_rows(db, headers, rows)
            added = product_result["added"]
            updated = product_result["updated"]

        if "定制报价" in wb.sheetnames:
            for row in wb["定制报价"].iter_rows(min_row=2, values_only=True):
                if not _cell(row, 0):
                    continue
                db.add(CustomQuoteRule(
                    project_name=_cell(row, 0), category=_cell(row, 1),
                    pricing_unit=_cell(row, 2) or "㎡", material_grade=_cell(row, 3),
                    unit_price=int(_cell(row, 4) or 0), description=_cell(row, 5),
                ))
                rules_added += 1

        db.commit()
        print(f"OK: 成品新增 {added}、更新 {updated}；定制规则新增 {rules_added}")
    finally:
        db.close()


if __name__ == "__main__":
    if "--template" in sys.argv:
        make_template()
    elif len(sys.argv) > 1:
        import_file(sys.argv[1])
    else:
        print(__doc__)
