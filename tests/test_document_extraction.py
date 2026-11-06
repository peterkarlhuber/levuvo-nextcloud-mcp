"""AP3: document extraction - formats, encodings, order, limits and damaged files."""

from __future__ import annotations

import io
import zipfile

import pytest
from docx import Document
from openpyxl import Workbook

from levuvo_nextcloud_mcp import extractors
from levuvo_nextcloud_mcp.errors import DocumentError, LimitExceededError, UnsupportedFormatError
from levuvo_nextcloud_mcp.extractors import decode_text, extract_text


def make_pdf(pages: list[str]) -> bytes:
    """Build a small valid PDF with one text line per page (no external tools)."""
    objects: list[bytes] = []
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_id = 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def docx_bytes(build) -> bytes:
    doc = Document()
    build(doc)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------- text & encodings
@pytest.mark.parametrize(
    "data, text, encoding",
    [
        ("Größe;Wert\n".encode(), "Größe;Wert\n", "utf-8"),
        ("﻿BOM-Text".encode(), "BOM-Text", "utf-8"),
        ("Größe;Wert\n".encode("cp1252"), "Größe;Wert\n", "cp1252"),
        ("€ Preis".encode("cp1252"), "€ Preis", "cp1252"),
        ("UTF16 Ä".encode("utf-16"), "UTF16 Ä", "utf-16"),
    ],
)
def test_text_encodings(data: bytes, text: str, encoding: str) -> None:
    assert decode_text(data) == (text, encoding)


def test_csv_from_excel_keeps_umlauts() -> None:
    text, truncated, fmt, encoding = extract_text(
        "02_Finanzen/export.csv", "Kategorie;Betrag\nMöbel;100\n".encode("cp1252"), max_chars=1000
    )
    assert "Möbel;100" in text and encoding == "cp1252" and fmt == ".csv" and truncated is False


def test_binary_content_with_text_extension_is_rejected() -> None:
    with pytest.raises(UnsupportedFormatError, match="appears to be binary"):
        extract_text("x.txt", b"MZ\x00\x00\x00binary", max_chars=1000)


@pytest.mark.parametrize(
    "name", ["setup.exe", "bild.png", "archiv.zip", "alt.doc", "alt.xls", "DateiOhneEndung", "makro.xlsm"]
)
def test_unsupported_formats(name: str) -> None:
    with pytest.raises(UnsupportedFormatError, match="is not supported"):
        extract_text(name, b"data", max_chars=1000)


def test_extension_is_case_insensitive() -> None:
    assert extract_text("README.MD", b"hallo", max_chars=1000)[0] == "hallo"


def test_html_and_markup_are_returned_as_plain_text_not_executed() -> None:
    text = extract_text("x.html", b"<script>alert(1)</script>", max_chars=1000)[0]
    assert text == "<script>alert(1)</script>"


# --------------------------------------------------------------------------- DOCX
def test_docx_keeps_document_order_of_paragraphs_and_tables() -> None:
    def build(doc) -> None:
        doc.add_paragraph("Einleitung")
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text, table.cell(0, 1).text = "Posten", "Betrag"
        table.cell(1, 0).text, table.cell(1, 1).text = "Hosting", "100"
        doc.add_paragraph("Schluss")

    text = extract_text("a.docx", docx_bytes(build), max_chars=3000)[0]
    assert text.splitlines() == ["Einleitung", "Posten | Betrag", "Hosting | 100", "Schluss"]


def test_docx_output_limit() -> None:
    text, truncated, _, _ = extract_text(
        "a.docx", docx_bytes(lambda d: [d.add_paragraph("x" * 80) for _ in range(20)]), max_chars=200
    )
    assert len(text) == 200 and truncated is True


@pytest.mark.parametrize("data", [b"not a zip", b"PK\x03\x04broken", zipfile.ZipFile.__name__.encode()])
def test_damaged_docx_and_xlsx(data: bytes) -> None:
    for name in ("a.docx", "a.xlsx"):
        with pytest.raises(DocumentError, match="damaged"):
            extract_text(name, data, max_chars=1000)


def test_zip_without_word_document_is_damaged() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(DocumentError):
        extract_text("a.docx", buffer.getvalue(), max_chars=1000)


def test_zip_bomb_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "0" * 200_000)
    monkeypatch.setattr(extractors, "MAX_ZIP_MEMBER", 100_000)
    with pytest.raises(LimitExceededError, match="too large"):
        extract_text("a.docx", buffer.getvalue(), max_chars=1000)
    monkeypatch.setattr(extractors, "MAX_ZIP_MEMBER", 10_000_000)
    monkeypatch.setattr(extractors, "MAX_ZIP_TOTAL", 100_000)
    with pytest.raises(LimitExceededError, match="after decompression"):
        extract_text("a.xlsx", buffer.getvalue(), max_chars=1000)


# --------------------------------------------------------------------------- XLSX
def xlsx_bytes(sheets: dict[str, list[list[object]]]) -> bytes:
    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_xlsx_values_and_formulas_are_not_evaluated() -> None:
    data = xlsx_bytes({"Budget": [["Kategorie", "Betrag"], ["Hosting", 100], ["Summe", "=SUM(B2:B2)"]]})
    text = extract_text("b.xlsx", data, max_chars=3000)[0]
    assert "[Sheet: Budget]" in text and "Hosting | 100" in text
    assert "Summe | " in text  # cached value is empty: formulas are never executed


def test_xlsx_sheet_limit_marks_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extractors, "MAX_SHEETS", 2)
    _, truncated, _, _ = extract_text("b.xlsx", xlsx_bytes({f"S{i}": [["x"]] for i in range(3)}), max_chars=3000)
    assert truncated is True


# --------------------------------------------------------------------------- PDF
def test_pdf_text_per_page() -> None:
    text, truncated, fmt, _ = extract_text("a.pdf", make_pdf(["Hallo Levuvo", "Seite zwei"]), max_chars=3000)
    assert "[Page 1]" in text and "Hallo Levuvo" in text and "Seite zwei" in text
    assert fmt == ".pdf" and truncated is False


def test_pdf_page_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extractors, "MAX_PDF_PAGES", 2)
    text, truncated, _, _ = extract_text("a.pdf", make_pdf(["eins", "zwei", "drei"]), max_chars=3000)
    assert "drei" not in text and truncated is True and "first 2 PDF pages" in text


def test_pdf_without_text_gets_scan_hint() -> None:
    text = extract_text("scan.pdf", make_pdf([""]), max_chars=3000)[0]
    assert "no OCR" in text


@pytest.mark.parametrize("data", [b"%PDF-1.4 garbage", b"not a pdf", make_pdf(["ok"])[:60]])
def test_damaged_pdf(data: bytes) -> None:
    with pytest.raises(DocumentError, match="PDF"):
        extract_text("a.pdf", data, max_chars=1000)


def test_encrypted_pdf_is_rejected() -> None:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["geheim"]))))
    writer.encrypt(user_password="pw", owner_password="pw2")
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(DocumentError, match="Encrypted PDF"):
        extract_text("a.pdf", buffer.getvalue(), max_chars=1000)
