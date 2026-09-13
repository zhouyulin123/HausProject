from pathlib import Path
from datetime import datetime, timezone

import pytest

from app.services import pdf_service


def test_resolve_pdf_fonts_prefers_configured_files(monkeypatch):
    # 这里只验证路径选择；字体二进制合法性由 ReportLab 在注册阶段负责。
    regular = Path(pdf_service.__file__)
    bold = Path(pdf_service.__file__)
    monkeypatch.setattr(pdf_service.settings, "pdf_font_regular_path", str(regular))
    monkeypatch.setattr(pdf_service.settings, "pdf_font_bold_path", str(bold))

    assert pdf_service.resolve_pdf_font_paths() == (regular, bold)


def test_resolve_pdf_fonts_rejects_missing_configured_font(monkeypatch):
    monkeypatch.setattr(
        pdf_service.settings,
        "pdf_font_regular_path",
        str(Path("missing-font.ttf")),
    )
    monkeypatch.setattr(pdf_service.settings, "pdf_font_bold_path", "")

    with pytest.raises(RuntimeError, match="PDF 中文字体"):
        pdf_service.resolve_pdf_font_paths()


def test_quote_validity_text_never_invents_a_duration_without_frozen_fact():
    assert pdf_service.quote_validity_text(None) == (
        "报价有效期未提供，不承诺具体天数。"
    )


def test_quote_validity_text_uses_exact_frozen_expiry_date():
    valid_until = datetime(2027, 1, 1, tzinfo=timezone.utc)

    assert pdf_service.quote_validity_text(valid_until) == (
        "报价有效至 2027-01-01（来自冻结价格凭证）。"
    )
