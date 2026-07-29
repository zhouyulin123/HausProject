"""品牌提案 PDF 生成（reportlab，微软雅黑中文字体）。

一份可直接微信发给客户的提案书：方案 + 效果图 + 本店产品报价单 + 建议。
"""

import io
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_SAGE = colors.HexColor("#5F7350")
_TERRA = colors.HexColor("#B06A45")
_INK = colors.HexColor("#44403C")
_MUTED = colors.HexColor("#78716C")
_CREAM = colors.HexColor("#F6F1E7")
_LINE = colors.HexColor("#E7DFD1")

_fonts_ready = False


def _ensure_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(TTFont("MSYH", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))
    try:
        pdfmetrics.registerFont(
            TTFont("MSYH-B", "C:/Windows/Fonts/msyhbd.ttc", subfontIndex=0)
        )
    except Exception:
        pdfmetrics.registerFont(TTFont("MSYH-B", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))
    _fonts_ready = True


def _styles() -> Dict[str, ParagraphStyle]:
    return {
        "brand": ParagraphStyle("brand", fontName="MSYH-B", fontSize=16, leading=22, textColor=_SAGE),
        "title": ParagraphStyle("title", fontName="MSYH-B", fontSize=20, leading=28, textColor=_INK, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName="MSYH-B", fontSize=12, leading=17, textColor=_SAGE, spaceBefore=10, spaceAfter=5),
        "body": ParagraphStyle("body", fontName="MSYH", fontSize=10, textColor=_INK, leading=16),
        "muted": ParagraphStyle("muted", fontName="MSYH", fontSize=8.5, textColor=_MUTED, leading=13),
        "cell": ParagraphStyle("cell", fontName="MSYH", fontSize=9, textColor=_INK, leading=13),
        "cellMuted": ParagraphStyle("cellMuted", fontName="MSYH", fontSize=8, textColor=_MUTED, leading=11),
    }


def _fmt(n: Any) -> str:
    try:
        return f"¥{int(n):,}"
    except (TypeError, ValueError):
        return str(n or "-")


def _quote_table(plan: Dict[str, Any], st: Dict[str, ParagraphStyle]) -> Optional[Table]:
    rows: List[List[Any]] = [["项目", "规格", "单价", "数量", "小计"]]
    for f in plan.get("furnitureSuggestions", []):
        if f.get("subtotal") is None:
            continue
        rows.append([
            Paragraph(str(f.get("name", "")), st["cell"]),
            Paragraph(f"{f.get('sku', '')} · {f.get('material', '')}", st["cellMuted"]),
            _fmt(f.get("unitPrice")),
            f"x{f.get('quantity', 1)}",
            _fmt(f.get("subtotal")),
        ])
    for c in plan.get("customItems", []):
        rows.append([
            Paragraph(str(c.get("project", "")), st["cell"]),
            Paragraph(f"{c.get('grade') or '标准'} · {c.get('note', '')}", st["cellMuted"]),
            f"{_fmt(c.get('unitPrice'))}/{c.get('unit', '')}",
            f"{c.get('quantity', 1)} {c.get('unit', '')}",
            _fmt(c.get("subtotal")),
        ])
    if len(rows) == 1:
        return None

    quote = plan.get("shopQuote") or {}
    rows.append(["", "", "", "本店产品合计", _fmt(quote.get("total"))])

    table = Table(rows, colWidths=[46 * mm, 52 * mm, 24 * mm, 22 * mm, 26 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "MSYH"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), _SAGE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, _CREAM]),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _LINE),
        ("FONTNAME", (3, -1), (-1, -1), "MSYH-B"),
        ("TEXTCOLOR", (4, -1), (4, -1), _TERRA),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def build_proposal_pdf(
    plan: Dict[str, Any],
    effect_image_path: Optional[str] = None,
    shop: Optional[Dict[str, Any]] = None,
) -> bytes:
    """把一套方案渲染成品牌提案 PDF，返回文件字节。

    shop：店铺信息 dict（shop_name/phone/wechat/address/slogan/logo_url）。
    """
    _ensure_fonts()
    st = _styles()
    shop = shop or {}
    shop_name = shop.get("shop_name") or "家装定制方案"
    # 页脚联系方式：微信/电话/地址按有值的拼接
    contact_bits = [
        shop.get("slogan"),
        f"电话 {shop['phone']}" if shop.get("phone") else None,
        f"微信 {shop['wechat']}" if shop.get("wechat") else None,
        shop.get("address"),
    ]
    footer = "  ·  ".join(b for b in contact_bits if b) or "到店咨询"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"{plan.get('name', '家装方案')} - {shop_name}",
    )

    story: List[Any] = []
    # 品牌头：有 logo 展示 logo + 店名，否则只展示店名
    logo_path = shop.get("_logo_path")
    if logo_path and Path(logo_path).exists():
        logo = Image(logo_path, width=14 * mm, height=14 * mm, kind="proportional")
        header = Table(
            [[logo, Paragraph(shop_name, st["brand"])]],
            colWidths=[16 * mm, 158 * mm],
        )
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 4),
        ]))
        story.append(header)
    else:
        story.append(Paragraph(shop_name, st["brand"]))
    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=_LINE))
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph(str(plan.get("name", "家装方案")), st["title"]))
    meta = (
        f"风格：{plan.get('style', '-')}    AI 推荐指数：{plan.get('score', '-')}%    "
        f"整体预算参考：{_fmt(plan.get('budget'))}    日期：{time.strftime('%Y-%m-%d')}"
    )
    story.append(Paragraph(meta, st["muted"]))
    story.append(Spacer(1, 4 * mm))

    if effect_image_path and Path(effect_image_path).exists():
        img = Image(effect_image_path, width=174 * mm, height=116 * mm, kind="proportional")
        story.append(img)
        story.append(Paragraph("AI 生成效果图（实际交付以现场方案为准）", st["muted"]))
        story.append(Spacer(1, 3 * mm))

    if plan.get("description"):
        story.append(Paragraph("方案综述", st["h2"]))
        story.append(Paragraph(str(plan["description"]), st["body"]))

    layouts = plan.get("layoutSuggestions") or []
    if layouts:
        story.append(Paragraph("空间布局建议", st["h2"]))
        for i, item in enumerate(layouts, 1):
            story.append(Paragraph(f"{i}. {item}", st["body"]))

    quote_table = _quote_table(plan, st)
    if quote_table:
        story.append(Paragraph("本店产品报价单", st["h2"]))
        story.append(quote_table)
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            "以上为本店产品预估报价，定制项目工程量以现场测量为准；报价有效期 30 天。",
            st["muted"],
        ))

    tips = plan.get("aiTips") or []
    if tips:
        story.append(Paragraph("温馨提示", st["h2"]))
        for tip in tips:
            story.append(Paragraph(f"· {tip}", st["body"]))

    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=_LINE))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"{shop_name}  ·  {footer}", st["muted"]))

    doc.build(story)
    return buf.getvalue()
