"""Bounded text extraction for common office document formats."""
from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader


class UnsupportedFormat(ValueError):
    pass


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".xml", ".html", ".htm", ".log", ".toml",
    ".ini", ".cfg", ".py", ".js", ".ts", ".css", ".sql", ".rst",
}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx", ".xlsx"}


def _check_zip_expansion(data: bytes) -> None:
    """Reject unusually large compressed XML archives before document parsing."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 1500 or sum(item.file_size for item in entries) > 35_000_000:
            raise ValueError("Office-Datei ist nach Entpacken zu groß.")
        if any(item.file_size > 20_000_000 for item in entries):
            raise ValueError("Ein Bestandteil der Office-Datei ist zu groß.")


def extract_text(path: str, data: bytes, *, max_chars: int) -> tuple[str, bool, str]:
    """Returns (text, truncated, format). No OCR; max_chars caps returned model context."""
    extension = PurePosixPath(path).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormat(f"Dateiformat {extension or '(ohne Endung)'} wird nicht unterstützt.")
    partial = False
    if extension in TEXT_EXTENSIONS:
        text = data.decode("utf-8-sig", errors="replace")
    elif extension == ".pdf":
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError("Verschlüsselte PDF kann nicht gelesen werden.")
        chunks = []
        # Bounded for quick local use; a scan has no extractable text.
        for i, page in enumerate(reader.pages):
            if i >= 40 or sum(len(c) for c in chunks) > max_chars:
                break
            chunks.append(f"[Seite {i + 1}]\n{page.extract_text() or ''}")
        text = "\n\n".join(chunks)
        if len(reader.pages) > 40:
            partial = True
            text += "\n[Hinweis: Nur die ersten 40 PDF-Seiten verarbeitet]"
    elif extension == ".docx":
        _check_zip_expansion(data)
        doc = Document(io.BytesIO(data))
        chunks = []
        size = 0
        for paragraph in doc.paragraphs:
            if paragraph.text:
                chunks.append(paragraph.text)
                size += len(paragraph.text) + 1
            if size > max_chars:
                break
        if size <= max_chars:
            for table in doc.tables:
                for row in table.rows:
                    line = " | ".join(cell.text for cell in row.cells)
                    chunks.append(line)
                    size += len(line) + 1
                    if size > max_chars:
                        break
                if size > max_chars:
                    break
        text = "\n".join(chunks)
    else:
        _check_zip_expansion(data)
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        chunks = []
        size = 0
        try:
            if len(wb.worksheets) > 10:
                partial = True
            for sheet in wb.worksheets[:10]:
                if (sheet.max_row or 0) > 1000 or (sheet.max_column or 0) > 60:
                    partial = True
                chunks.append(f"[Tabellenblatt: {sheet.title}]")
                for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                    if row_index > 1000 or size > max_chars:
                        break
                    text_row = " | ".join("" if cell is None else str(cell) for cell in row[:60])
                    chunks.append(text_row)
                    size += len(text_row) + 1
                if size > max_chars:
                    break
        finally:
            wb.close()
        text = "\n".join(chunks)
    return text[:max_chars], partial or len(text) > max_chars, extension
