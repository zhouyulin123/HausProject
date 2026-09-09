from pathlib import Path

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
