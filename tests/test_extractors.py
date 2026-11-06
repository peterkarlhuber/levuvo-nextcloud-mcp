from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document
from openpyxl import Workbook

from levuvo_nextcloud_mcp.errors import UnsupportedFormatError as UnsupportedFormat
from levuvo_nextcloud_mcp.extractors import extract_text


def test_markdown_content_truncated() -> None:
    text, truncated, fmt, _ = extract_text("05_Projekte/roadmap.md", b"x" * 150, max_chars=100)
    assert len(text) == 100
    assert truncated
    assert fmt == ".md"


def test_docx_text() -> None:
    doc = Document()
    doc.add_paragraph("Levuvo Vision und Mission")
    buffer = BytesIO()
    doc.save(buffer)
    text, _, fmt, _ = extract_text("01_Unternehmen/vision.docx", buffer.getvalue(), max_chars=3000)
    assert "Levuvo Vision" in text
    assert fmt == ".docx"


def test_xlsx_text() -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "Budget"
    sheet.append(["Kategorie", "Betrag"])
    sheet.append(["Hosting", 100])
    buffer = BytesIO()
    book.save(buffer)
    text, _, fmt, _ = extract_text("02_Finanzen/budget.xlsx", buffer.getvalue(), max_chars=3000)
    assert "Hosting | 100" in text
    assert fmt == ".xlsx"


def test_executable_binary_is_rejected() -> None:
    with pytest.raises(UnsupportedFormat):
        extract_text("05_Projekte/setup.exe", b"hello", max_chars=1000)
