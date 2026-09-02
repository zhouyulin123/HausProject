# -*- coding: utf-8 -*-
"""从 Excel 导入自家产品到商品库。

用法：
    python import_products.py --template          # 生成空白模板 products_import.xlsx
    python import_products.py products_import.xlsx  # 导入（按 SKU 去重：已存在则更新，否则新增）

Excel 有两个工作表：
    「商品主表」：商品、尺寸、核验、库存、地区、交期、价格有效期与替代 SKU
    「定制报价」：项目名, 分类, 计价单位, 材料档位, 单价, 说明
"""

import sys
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from openpyxl import Workbook, load_workbook

from app.db.database import Base, SessionLocal, engine
from app.db.models import CustomQuoteRule, Product

PRODUCT_HEADERS = [
    "sku", "名称", "类别", "空间", "风格", "材质", "参考价", "价格上限",
    "尺寸", "宽(mm)", "深(mm)", "高(mm)", "卖点", "替代选择",
    "启用状态", "人工复核状态", "价格备注",
    "可售状态", "地区代码", "库存数量", "最短交期(天)", "最长交期(天)",
    "价格生效时间", "价格失效时间", "复核负责人", "数据版本", "替代SKU",
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
        "内部参考零售价，待人工复核", "未知", "", "", "", "", "", "",
        "", "draft-v1", "",
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


def _non_negative_int(value: Any, label: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if number < 0:
        raise ValueError(f"{label}不能小于 0")
    return number


def _datetime_value(value: Any, label: str) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label}必须是 ISO 8601 时间") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _code_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    raw = value if isinstance(value, list) else str(value).replace("，", ",").split(",")
    return list(dict.fromkeys(str(item).strip().upper() for item in raw if str(item).strip()))


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
    product["verification_status"] = (
        "verified" if review_status == "manual_verified" else "draft"
    )
    if "可售状态" in cells:
        product["availability_status"] = _controlled_value(
            cells.get("可售状态", "未知"),
            "可售状态",
            {
                "现货": "in_stock",
                "低库存": "low_stock",
                "缺货": "out_of_stock",
                "预售": "preorder",
                "未知": "unknown",
            },
        )
    if "地区代码" in cells:
        product["region_codes"] = _code_list(cells.get("地区代码"))
    for header, field in {
        "库存数量": "stock_quantity",
        "最短交期(天)": "lead_time_days_min",
        "最长交期(天)": "lead_time_days_max",
    }.items():
        if header in cells:
            product[field] = _non_negative_int(cells.get(header), header)
    for header, field in {
        "价格生效时间": "price_valid_from",
        "价格失效时间": "price_valid_to",
    }.items():
        if header in cells:
            product[field] = _datetime_value(cells.get(header), header)
    if "复核负责人" in cells:
        product["verified_by"] = cells.get("复核负责人")
    if "数据版本" in cells:
        product["data_version"] = cells.get("数据版本") or "draft-v1"
    if "替代SKU" in cells:
        product["alternative_skus"] = _code_list(cells.get("替代SKU"))
    if product["verification_status"] == "verified":
        product["verified_at"] = datetime.now(timezone.utc)
        if not product.get("verified_by"):
            raise ValueError("已复核商品必须填写复核负责人")
    if (
        product.get("lead_time_days_min") is not None
        and product.get("lead_time_days_max") is not None
        and product["lead_time_days_min"] > product["lead_time_days_max"]
    ):
        raise ValueError("最短交期不能大于最长交期")
    if (
        product.get("price_valid_from")
        and product.get("price_valid_to")
        and product["price_valid_from"] > product["price_valid_to"]
    ):
        raise ValueError("价格生效时间不能晚于失效时间")
    if product.get("price_max") is not None and product["price_max"] < product["price"]:
        raise ValueError("价格上限不能低于参考价")
    if product["sku"].upper() in product.get("alternative_skus", []):
        raise ValueError("替代 SKU 不能包含商品自身")
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
                previous_version = product.record_version or 1
                for field, value in data.items():
                    setattr(product, field, value)
                product.record_version = previous_version + 1
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


def product_to_export_record(product: Product) -> dict[str, Any]:
    """导出可再次导入的 JSON 记录，保留生命周期字段。"""
    return {
        "sku": product.sku,
        "名称": product.name,
        "类别": product.category,
        "空间": product.room,
        "风格": product.style,
        "材质": product.material,
        "参考价": product.price,
        "价格上限": product.price_max,
        "尺寸": product.size,
        "宽(mm)": product.model_width_mm,
        "深(mm)": product.model_depth_mm,
        "高(mm)": product.model_height_mm,
        "卖点": product.selling_point,
        "替代选择": product.alternative,
        "启用状态": "是" if product.is_active else "否",
        "人工复核状态": "已复核" if product.verification_status == "verified" else "待复核",
        "价格备注": product.price_note,
        "可售状态": {
            "in_stock": "现货", "low_stock": "低库存", "out_of_stock": "缺货",
            "preorder": "预售", "unknown": "未知",
        }.get(product.availability_status, "未知"),
        "地区代码": ",".join(product.region_codes or []),
        "库存数量": product.stock_quantity,
        "最短交期(天)": product.lead_time_days_min,
        "最长交期(天)": product.lead_time_days_max,
        "价格生效时间": product.price_valid_from.isoformat() if product.price_valid_from else None,
        "价格失效时间": product.price_valid_to.isoformat() if product.price_valid_to else None,
        "复核负责人": product.verified_by,
        "数据版本": product.data_version,
        "替代SKU": ",".join(product.alternative_skus or []),
        "record_version": product.record_version,
    }


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
