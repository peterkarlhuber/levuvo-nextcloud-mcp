"""Bounded text extraction for common document formats (no OCR, no macro execution).

All parsers run on bytes that were already size-limited by the WebDAV client. The
function is synchronous and CPU-bound; callers run it in a worker thread.
"""

from __future__ import annotations

import codecs
import io
import re
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
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | OFFICE_EXTENSIONS | {".pdf", ".rtf"}

MAX_PDF_PAGES = 40
MAX_SHEETS = 10
MAX_SHEET_ROWS = 1000
MAX_SHEET_COLUMNS = 60
MAX_ZIP_ENTRIES = 1500
MAX_ZIP_TOTAL = 35_000_000
MAX_ZIP_MEMBER = 20_000_000
MAX_RTF_DEPTH = 256


def _check_zip_expansion(data: bytes) -> None:
    """Reject damaged or unusually large Office archives (zip bombs) before parsing."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise DocumentError("The Office file is damaged or not a valid Office document.") from None
    if len(entries) > MAX_ZIP_ENTRIES or sum(item.file_size for item in entries) > MAX_ZIP_TOTAL:
        raise LimitExceededError("The Office file is too large after decompression.")
    if any(item.file_size > MAX_ZIP_MEMBER for item in entries):
        raise LimitExceededError("A part of the Office file is too large.")


def decode_text(data: bytes) -> tuple[str, str]:
    """Decode plain text: UTF-8 (with/without BOM), UTF-16 with BOM, else Windows-1252."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    if b"\x00" in data[:8192]:
        raise UnsupportedFormatError("The file appears to be binary and is not read as text.")
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        # Typical for CSV exports from Excel on Windows (German umlauts in cp1252).
        return data.decode("cp1252", errors="replace"), "cp1252"


def _docx_text(data: bytes, max_chars: int) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    _check_zip_expansion(data)
    try:
        doc = Document(io.BytesIO(data))
    except Exception:  # python-docx raises many different parser errors
        raise DocumentError("The DOCX document is damaged or cannot be read.") from None
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
        raise DocumentError("The XLSX file is damaged or cannot be read.") from None
    chunks: list[str] = []
    size = 0
    partial = False
    try:
        if len(workbook.worksheets) > MAX_SHEETS:
            partial = True
        for sheet in workbook.worksheets[:MAX_SHEETS]:
            if (sheet.max_row or 0) > MAX_SHEET_ROWS or (sheet.max_column or 0) > MAX_SHEET_COLUMNS:
                partial = True
            chunks.append(f"[Sheet: {sheet.title}]")
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if row_index > MAX_SHEET_ROWS or size > max_chars:
                    break
                line = " | ".join("" if cell is None else str(cell) for cell in row[:MAX_SHEET_COLUMNS])
                chunks.append(line)
                size += len(line) + 1
            if size > max_chars:
                break
    except Exception:
        raise DocumentError("The XLSX file is damaged or cannot be read.") from None
    finally:
        workbook.close()
    return "\n".join(chunks), partial


def _pdf_text(data: bytes, max_chars: int) -> tuple[str, bool]:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise DocumentError("Encrypted PDF files cannot be read.")
        page_count = len(reader.pages)
        chunks: list[str] = []
        size = 0
        has_text = False
        for index in range(min(page_count, MAX_PDF_PAGES)):
            if size > max_chars:
                break
            page_text = reader.pages[index].extract_text() or ""
            has_text = has_text or bool(page_text.strip())
            chunk = f"[Page {index + 1}]\n{page_text}"
            chunks.append(chunk)
            size += len(chunk) + 2
    except DocumentError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError, RecursionError, AttributeError, IndexError):
        raise DocumentError("The PDF file is damaged or cannot be read.") from None
    text = "\n\n".join(chunks)
    partial = page_count > MAX_PDF_PAGES
    if partial:
        text += f"\n[Note: Only the first {MAX_PDF_PAGES} PDF pages were processed]"
    if not has_text:
        text += "\n[Note: No extractable text found - possibly a scanned PDF (no OCR).]"
    return text, partial


# --------------------------------------------------------------------------- RTF
# A small, purpose-built RTF reader instead of a third-party library: every token pattern below
# is bounded or a plain character class, so scanning is linear in the input size (no regex
# backtracking on crafted input), binary payloads (\binN) are skipped by length, and nothing in
# the document is ever interpreted beyond text: embedded objects, pictures, fields' instructions,
# fonts, styles and metadata are discarded.
_RTF_TOKEN = re.compile(
    rb"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?"  # control word with optional numeric parameter
    rb"|\\'([0-9a-fA-F]{2})"  # hex-encoded byte in the current code page
    rb"|\\([^a-zA-Z])"  # control symbol
    rb"|([{}])"  # group start/end
    rb"|[\r\n]+"  # raw line breaks carry no meaning in RTF
    rb"|([^\\{}\r\n]+)",  # plain text run
    re.DOTALL,
)
# Destinations whose content is never text of the main document body.
_RTF_SKIP_DESTINATIONS = frozenset(
    {
        "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "objdata", "objclass", "objname",
        "result", "fldinst", "header", "headerl", "headerr", "headerf", "footer", "footerl", "footerr",
        "footerf", "footnote", "annotation", "atnid", "atnauthor", "themedata", "colorschememapping",
        "datastore", "latentstyles", "listtable", "listoverridetable", "rsidtbl", "generator", "xmlnstbl",
        "filetbl", "revtbl", "pgdsctbl", "shp", "shpinst", "shppict", "nonshppict", "bkmkstart", "bkmkend",
        "xe", "tc", "txe", "rxe", "template", "userprops", "docvar", "mmathPr", "pn",
    }
)  # fmt: skip
_RTF_SPECIAL = {
    "par": "\n", "line": "\n", "sect": "\n\n", "page": "\n\n", "tab": "\t", "cell": " | ", "nestcell": " | ",
    "row": "\n", "nestrow": "\n", "emdash": "\u2014", "endash": "\u2013", "emspace": " ", "enspace": " ",
    "qmspace": " ", "bullet": "\u2022", "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201c",
    "rdblquote": "\u201d",
}  # fmt: skip
_RTF_SYMBOLS = {"\\": "\\", "{": "{", "}": "}", "~": "\xa0", "_": "-", "\n": "\n", "\r": "\n", "-": ""}
# \fcharsetN -> Python codec (Windows code pages; symbol fonts fall back to cp1252).
_RTF_CHARSETS = {
    0: "cp1252", 2: "cp1252", 77: "mac_roman", 128: "cp932", 129: "cp949", 134: "gbk", 136: "cp950",
    161: "cp1253", 162: "cp1254", 163: "cp1258", 177: "cp1255", 178: "cp1256", 186: "cp1257", 204: "cp1251",
    222: "cp874", 238: "cp1250",
}  # fmt: skip
_RTF_DAMAGED = "The RTF file is damaged or not a valid RTF document."


def _rtf_codec(name: str, fallback: str) -> str:
    try:
        codecs.lookup(name)
    except LookupError:
        return fallback
    return name


def _rtf_text(data: bytes, max_chars: int) -> tuple[str, bool]:
    """Extract the visible text of an RTF document (paragraphs, table cells, Unicode, code pages).

    Returns ``(text, partial)``; ``partial`` is True when scanning stopped early at ``max_chars``.
    """
    start = len(data) - len(data.lstrip(b"\xef\xbb\xbf \t\r\n"))
    if not data.startswith(b"{\\rtf", start):
        raise DocumentError(_RTF_DAMAGED)
    out: list[str] = []
    size = 0
    pending = bytearray()  # raw/hex bytes waiting to be decoded with the current code page
    doc_codec = "cp1252"
    fonts: dict[int, str] = {}  # font number -> codec, from the font table
    defining_font: int | None = None
    default_font: int | None = None
    # Group state: (skip, font, unicode skip count, in font table)
    skip, font, uc, in_fonttbl = False, None, 1, False
    stack: list[tuple[bool, int | None, int, bool]] = []
    to_skip = 0  # fallback characters still to drop after a \\uN
    started = False
    pos, end = start, len(data)

    def emit(text: str) -> None:
        nonlocal size
        if text and not skip:
            out.append(text)
            size += len(text)

    def flush() -> None:
        if pending:
            codec = fonts.get(font if font is not None else default_font, doc_codec)  # type: ignore[arg-type]
            emit(bytes(pending).decode(codec, errors="replace"))
            pending.clear()

    while pos < end and size <= max_chars:
        match = _RTF_TOKEN.match(data, pos)
        if match is None:  # a lone backslash at the very end
            raise DocumentError(_RTF_DAMAGED)
        pos = match.end()
        word, param, hex_byte, symbol, brace, text = match.groups()
        if hex_byte is not None:
            if to_skip:
                to_skip -= 1
            elif not skip:
                pending.append(int(hex_byte, 16))
            continue
        if text is not None:
            if to_skip:
                dropped = min(to_skip, len(text))
                text, to_skip = text[dropped:], to_skip - dropped
            if not skip:
                pending.extend(text)
            continue
        flush()
        if brace == b"{":
            if len(stack) >= MAX_RTF_DEPTH:
                raise LimitExceededError("The RTF file is nested too deeply.")
            stack.append((skip, font, uc, in_fonttbl))
            started, to_skip = True, 0
        elif brace == b"}":
            if not stack:
                break  # end of the document group; anything after it is ignored like Word does
            skip, font, uc, in_fonttbl = stack.pop()
            to_skip = 0
            if not stack:
                break
        elif symbol is not None:
            char = symbol.decode("latin-1")
            if char == "'":
                raise DocumentError(_RTF_DAMAGED)  # \\' without two hex digits
            if char == "*":
                skip = True  # ignorable destination unknown to this reader
            elif char in _RTF_SYMBOLS:
                emit(_RTF_SYMBOLS[char])
        elif word is not None:
            if data[pos - 1 : pos].isalpha() and pos < end and data[pos : pos + 1].isalpha():
                raise DocumentError(_RTF_DAMAGED)  # control word longer than the RTF limit of 32 letters
            name = word.decode("ascii")
            value = int(param) if param is not None else None
            if name == "bin":
                length = value or 0
                if length < 0 or pos + length > end:
                    raise DocumentError(_RTF_DAMAGED)
                pos += length  # binary payload: never interpreted
            elif name == "fonttbl":
                skip, in_fonttbl = True, True
            elif in_fonttbl and name == "f" and value is not None:
                defining_font = value
            elif in_fonttbl and name == "fcharset" and value is not None and defining_font is not None:
                fonts[defining_font] = _RTF_CHARSETS.get(value, "cp1252")
            elif name in _RTF_SKIP_DESTINATIONS:
                skip = True
            elif name == "ansicpg" and value is not None:
                doc_codec = _rtf_codec(f"cp{value}", "cp1252")
            elif name == "deff" and value is not None:
                default_font = value
            elif name == "f" and value is not None:
                font = value
            elif name == "uc" and value is not None:
                uc = max(0, value)
            elif name == "u" and value is not None:
                emit(chr(value + 0x10000 if value < 0 else value))
                to_skip = uc
            elif name in _RTF_SPECIAL:
                emit(_RTF_SPECIAL[name])
    partial = size > max_chars and pos < end
    flush()
    if not started:
        raise DocumentError(_RTF_DAMAGED)
    text = "".join(out)
    # Combine UTF-16 surrogate pairs written as two \\uN words (characters outside the BMP).
    text = text.encode("utf-16", "surrogatepass").decode("utf-16", errors="replace")
    text = text.replace(" | \n", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip(), partial


def extract_text(path: str, data: bytes, *, max_chars: int) -> tuple[str, bool, str, str | None]:
    """Return ``(text, truncated, format, encoding)``. ``max_chars`` caps the returned text."""
    extension = PurePosixPath(path).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"File format {extension or '(no extension)'} is not supported. Supported: "
            "text formats (e.g. .txt, .md, .csv, .json), .pdf, .docx, .xlsx, .rtf."
        )
    partial = False
    encoding: str | None = None
    if extension in TEXT_EXTENSIONS:
        text, encoding = decode_text(data)
    elif extension == ".pdf":
        text, partial = _pdf_text(data, max_chars)
    elif extension == ".docx":
        text = _docx_text(data, max_chars)
    elif extension == ".rtf":
        text, partial = _rtf_text(data, max_chars)
    else:
        text, partial = _xlsx_text(data, max_chars)
    return text[:max_chars], partial or len(text) > max_chars, extension, encoding
