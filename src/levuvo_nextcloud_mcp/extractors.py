"""Bounded text extraction for common document formats (no OCR, no macro execution).

All parsers run on bytes that were already size-limited by the WebDAV client. The
function is synchronous and CPU-bound; callers run it in a worker thread.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath

from .errors import DocumentError, LimitExceededError, UnsupportedFormatError

TEXT_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".tsv",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".xml",
        ".html",
        ".htm",
        ".log",
        ".toml",
        ".ini",
        ".cfg",
        ".py",
        ".js",
        ".ts",
        ".css",
        ".sql",
        ".rst",
    }
)
OFFICE_EXTENSIONS = frozenset({".docx", ".xlsx"})
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | OFFICE_EXTENSIONS | {".pdf"}

MAX_PDF_PAGES = 40
MAX_SHEETS = 10
MAX_SHEET_ROWS = 1000
MAX_SHEET_COLUMNS = 60
MAX_ZIP_ENTRIES = 1500
MAX_ZIP_TOTAL = 35_000_000
MAX_ZIP_MEMBER = 20_000_000


def _check_zip_expansion(data: bytes) -> None:
    """Reject damaged or unusually large Office archives (zip bombs) before parsing."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise DocumentError("Die Office-Datei ist beschädigt oder kein gültiges Office-Dokument.") from None
    if len(entries) > MAX_ZIP_ENTRIES or sum(item.file_size for item in entries) > MAX_ZIP_TOTAL:
        raise LimitExceededError("Die Office-Datei ist nach dem Entpacken zu groß.")
    if any(item.file_size > MAX_ZIP_MEMBER for item in entries):
        raise LimitExceededError("Ein Bestandteil der Office-Datei ist zu groß.")


def decode_text(data: bytes) -> tuple[str, str]:
    """Decode plain text: UTF-8 (with/without BOM), UTF-16 with BOM, else Windows-1252."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    if b"\x00" in data[:8192]:
        raise UnsupportedFormatError("Die Datei scheint binär zu sein und wird nicht als Text gelesen.")
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        # Typical for CSV exports from Excel on Windows (Umlaute in cp1252).
        return data.decode("cp1252", errors="replace"), "cp1252"


def _docx_text(data: bytes, max_chars: int) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    _check_zip_expansion(data)
    try:
        doc = Document(io.BytesIO(data))
    except Exception:  # python-docx raises many different parser errors
        raise DocumentError("Das DOCX-Dokument ist beschädigt oder kann nicht gelesen werden.") from None
    chunks: list[str] = []
    size = 0

    def add(line: str) -> bool:
        nonlocal size
        if line:
            chunks.append(line)
            size += len(line) + 1
        return size <= max_chars

    # Iterate the body in document order so tables stay where they belong.
    for element in doc.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            if not add(Paragraph(element, doc).text):
                break
        elif tag == "tbl":
            keep_going = True
            for row in Table(element, doc).rows:
                if not add(" | ".join(cell.text.strip() for cell in row.cells)):
                    keep_going = False
                    break
            if not keep_going:
                break
    return "\n".join(chunks)


def _xlsx_text(data: bytes, max_chars: int) -> tuple[str, bool]:
    from openpyxl import load_workbook

    _check_zip_expansion(data)
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise DocumentError("Die XLSX-Datei ist beschädigt oder kann nicht gelesen werden.") from None
    chunks: list[str] = []
    size = 0
    partial = False
    try:
        if len(workbook.worksheets) > MAX_SHEETS:
            partial = True
        for sheet in workbook.worksheets[:MAX_SHEETS]:
            if (sheet.max_row or 0) > MAX_SHEET_ROWS or (sheet.max_column or 0) > MAX_SHEET_COLUMNS:
                partial = True
            chunks.append(f"[Tabellenblatt: {sheet.title}]")
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if row_index > MAX_SHEET_ROWS or size > max_chars:
                    break
                line = " | ".join("" if cell is None else str(cell) for cell in row[:MAX_SHEET_COLUMNS])
                chunks.append(line)
                size += len(line) + 1
            if size > max_chars:
                break
    except Exception:
        raise DocumentError("Die XLSX-Datei ist beschädigt oder kann nicht gelesen werden.") from None
    finally:
        workbook.close()
    return "\n".join(chunks), partial


def _pdf_text(data: bytes, max_chars: int) -> tuple[str, bool]:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise DocumentError("Verschlüsselte PDF-Dateien können nicht gelesen werden.")
        page_count = len(reader.pages)
        chunks: list[str] = []
        size = 0
        has_text = False
        for index in range(min(page_count, MAX_PDF_PAGES)):
            if size > max_chars:
                break
            page_text = reader.pages[index].extract_text() or ""
            has_text = has_text or bool(page_text.strip())
            chunk = f"[Seite {index + 1}]\n{page_text}"
            chunks.append(chunk)
            size += len(chunk) + 2
    except DocumentError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError, RecursionError, AttributeError, IndexError):
        raise DocumentError("Die PDF-Datei ist beschädigt oder kann nicht gelesen werden.") from None
    text = "\n\n".join(chunks)
    partial = page_count > MAX_PDF_PAGES
    if partial:
        text += f"\n[Hinweis: Nur die ersten {MAX_PDF_PAGES} PDF-Seiten verarbeitet]"
    if not has_text:
        text += "\n[Hinweis: Kein extrahierbarer Text gefunden – evtl. gescanntes PDF (keine OCR).]"
    return text, partial


def extract_text(path: str, data: bytes, *, max_chars: int) -> tuple[str, bool, str, str | None]:
    """Return ``(text, truncated, format, encoding)``. ``max_chars`` caps the returned text."""
    extension = PurePosixPath(path).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Dateiformat {extension or '(ohne Endung)'} wird nicht unterstützt. Unterstützt: "
            "Textformate (z. B. .txt, .md, .csv, .json), .pdf, .docx, .xlsx."
        )
    partial = False
    encoding: str | None = None
    if extension in TEXT_EXTENSIONS:
        text, encoding = decode_text(data)
    elif extension == ".pdf":
        text, partial = _pdf_text(data, max_chars)
    elif extension == ".docx":
        text = _docx_text(data, max_chars)
    else:
        text, partial = _xlsx_text(data, max_chars)
    return text[:max_chars], partial or len(text) > max_chars, extension, encoding
