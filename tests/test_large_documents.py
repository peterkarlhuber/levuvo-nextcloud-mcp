"""0.5.2: large files and sectioned reading with read_file(offset, max_chars, etag)."""

from __future__ import annotations

import io
import tempfile
import tracemalloc

import pytest
from conftest import FakeNextcloud
from docx import Document
from mcp import Client
from test_document_extraction import make_pdf, xlsx_bytes

from levuvo_nextcloud_mcp import doc_cache, extractors
from levuvo_nextcloud_mcp import webdav as webdav_module
from levuvo_nextcloud_mcp.errors import AccessDeniedError, FileChangedError, InvalidArgumentError, LimitExceededError
from levuvo_nextcloud_mcp.extractors import extract_document
from levuvo_nextcloud_mcp.server import create_mcp
from levuvo_nextcloud_mcp.webdav import NextcloudWebDAV


def client(settings, fake: FakeNextcloud) -> NextcloudWebDAV:
    return NextcloudWebDAV(settings, transport=fake.transport())


def long_text(lines: int) -> str:
    return "".join(f"Line {i:06d}: Grüße aus Steyr, chapter {i // 100}.\n" for i in range(lines))


async def read_all(dav: NextcloudWebDAV, path: str, max_chars: int = 30000, **kwargs) -> tuple[str, list[dict]]:
    """Follow next_offset until has_more is false; return the joined text and all responses."""
    parts, responses, offset, etag = [], [], 0, None
    while True:
        result = await dav.read_file(path, offset=offset, max_chars=max_chars, etag=etag, **kwargs)
        responses.append(result)
        parts.append(result["text"])
        assert result["offset"] == offset and result["returned_chars"] == len(result["text"])
        etag = result["etag"]
        if not result["has_more"]:
            assert result["next_offset"] is None
            break
        assert result["next_offset"] == offset + result["returned_chars"]
        offset = result["next_offset"]
    return "".join(parts), responses


def docx_bytes(paragraphs: int) -> bytes:
    doc = Document()
    for i in range(paragraphs):
        doc.add_paragraph(f"Paragraph {i}: " + "Lorem ipsum dolor sit amet " * 3)
        if i % 500 == 0:
            table = doc.add_table(rows=2, cols=2)
            table.cell(0, 0).text, table.cell(0, 1).text = f"T{i}", "Wert"
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def rtf_bytes(paragraphs: int) -> bytes:
    body = "".join(f"\\pard Paragraph {i}: Gr\\'fc\\'dfe aus Steyr \\u8364?\\par\n" for i in range(paragraphs))
    return ("{\\rtf1\\ansi\\ansicpg1252{\\fonttbl{\\f0 Arial;}}" + body + "}").encode()


def html_bytes(sections: int) -> bytes:
    head = "<html><head><title>Archiv</title><style>body{color:red}</style><script>var secret = 1;</script></head>"
    body = "".join(f"<div><h2>Section {i}</h2><p>Text &amp; more text {i}.</p></div>\n" for i in range(sections))
    return (head + "<body>" + body + "<script>alert('x')</script></body></html>").encode()


# --------------------------------------------------------------------------- complete reconstruction
@pytest.mark.parametrize("max_chars", [100, 7777, 30000])
async def test_long_text_is_reconstructed_without_gaps_or_overlaps(make_settings, max_chars: int) -> None:
    content = long_text(4000)  # ~200,000 characters, far beyond one call
    fake = FakeNextcloud(files={"A/manual.md": content.encode()})
    async with client(make_settings("dir:A"), fake) as dav:
        text, responses = await read_all(dav, "A/manual.md", max_chars=max_chars)
    assert text == content
    assert len(responses) == -(-len(content) // max_chars)
    assert all(r["total_chars"] == len(content) and r["extraction_complete"] for r in responses)
    assert responses[0]["truncated"] is True and responses[-1]["truncated"] is True  # offset > 0
    assert fake.requests.count(("GET", "A/manual.md")) == 1  # later sections come from the cache


async def test_short_file_in_one_call_is_complete_and_not_truncated(make_settings) -> None:
    fake = FakeNextcloud(files={"A/short.txt": b"Hello"})
    async with client(make_settings("dir:A"), fake) as dav:
        result = await dav.read_file("A/short.txt")
    assert (result["text"], result["truncated"], result["has_more"], result["next_offset"]) == (
        "Hello",
        False,
        False,
        None,
    )
    assert result["total_chars"] == 5 and result["extraction_complete"] is True and result["etag"]
    # Fields of 0.5.1 are unchanged.
    assert {"path", "format", "size_bytes", "text", "truncated", "note", "encoding"} <= result.keys()


async def test_offset_at_the_end_and_beyond(make_settings) -> None:
    fake = FakeNextcloud(files={"A/f.txt": b"x" * 500})
    async with client(make_settings("dir:A"), fake) as dav:
        at_end = await dav.read_file("A/f.txt", offset=500)
        with pytest.raises(InvalidArgumentError, match="beyond the end"):
            await dav.read_file("A/f.txt", offset=501)
        for bad in (-1, True, "10", 25_000_001):
            with pytest.raises(InvalidArgumentError, match="offset"):
                await dav.read_file("A/f.txt", offset=bad)  # type: ignore[arg-type]
    assert at_end["text"] == "" and at_end["has_more"] is False and at_end["returned_chars"] == 0


async def test_large_html_raw_and_visible_text(make_settings) -> None:
    data = html_bytes(3000)
    fake = FakeNextcloud(files={"A/archiv.html": data})
    async with client(make_settings("dir:A"), fake) as dav:
        raw, _ = await read_all(dav, "A/archiv.html")
        visible, responses = await read_all(dav, "A/archiv.html", html_visible_text=True)
    assert raw == data.decode() and len(raw) > 150_000  # raw source is fully reachable, not cut at 30,000
    assert "Section 2999" in visible and "Text & more text 2999." in visible
    assert "secret" not in visible and "alert" not in visible and "color:red" not in visible and "<" not in visible
    assert visible.startswith("Archiv\n")
    assert responses[0]["html_visible_text"] is True
    assert fake.requests.count(("GET", "A/archiv.html")) == 2  # raw and visible text are cached separately


async def test_pdf_with_more_than_40_pages(make_settings) -> None:
    pages = [f"Seite {i} Inhalt" for i in range(1, 121)]
    fake = FakeNextcloud(files={"A/handbuch.pdf": make_pdf(pages)})
    async with client(make_settings("dir:A"), fake) as dav:
        text, responses = await read_all(dav, "A/handbuch.pdf", max_chars=500)
    for i in (1, 40, 41, 120):
        assert f"[Page {i}]\nSeite {i} Inhalt" in text
    sections = responses[0]["sections"]
    assert len(sections) == 120 and sections[40]["title"] == "Page 41"
    assert text[sections[40]["offset"] :].startswith("[Page 41]")
    assert responses[-1]["extraction_complete"] is True and "sections" not in responses[1]


async def test_large_docx_and_rtf_are_fully_reachable(make_settings) -> None:
    fake = FakeNextcloud(files={"A/lang.docx": docx_bytes(3000), "A/lang.rtf": rtf_bytes(5000)})
    async with client(make_settings("dir:A"), fake) as dav:
        docx_text, _ = await read_all(dav, "A/lang.docx")
        rtf_text, _ = await read_all(dav, "A/lang.rtf")
    assert len(docx_text) > 200_000 and "Paragraph 2999:" in docx_text and "T2500 | Wert" in docx_text
    assert len(rtf_text) > 150_000 and rtf_text.splitlines()[-1] == "Paragraph 4999: Grüße aus Steyr €"


async def test_xlsx_with_many_sheets_and_rows(make_settings) -> None:
    sheets = {f"Blatt{s}": [[f"r{r}", r * 10, None, "x"] for r in range(1, 2001)] for s in range(1, 13)}
    sheets["Lücken"] = [[None]] * 4 + [["erst in Zeile 5"]]
    fake = FakeNextcloud(files={"A/gross.xlsx": xlsx_bytes(sheets)})
    async with client(make_settings("dir:A"), fake) as dav:
        text, responses = await read_all(dav, "A/gross.xlsx")
    assert "[Sheet: Blatt12]" in text and "2000: r2000 | 20000 |  | x" in text  # beyond 10 sheets/1000 rows
    assert "[Sheet: Lücken]\n5: erst in Zeile 5" in text  # row numbers keep the real position
    titles = [s["title"] for s in responses[0]["sections"]]
    assert titles[:2] == ["Sheet: Blatt1", "Sheet: Blatt2"] and titles[-1] == "Sheet: Lücken"
    assert responses[-1]["extraction_complete"] is True


def test_xlsx_wide_sheets_are_reported_incomplete(monkeypatch) -> None:
    monkeypatch.setattr(extractors, "MAX_SHEET_COLUMNS", 3)
    result = extract_document("w.xlsx", io.BytesIO(xlsx_bytes({"S": [[1, 2, 3, 4, 5]]})))
    assert result.complete is False and "Columns after column 3" in result.notes[0]


# --------------------------------------------------------------------------- incomplete extraction is never "complete"
async def test_character_budget_marks_extraction_incomplete(make_settings, monkeypatch) -> None:
    monkeypatch.setattr(extractors, "MAX_EXTRACTED_CHARS", 1000)
    fake = FakeNextcloud(files={"A/big.txt": b"y" * 5000})
    async with client(make_settings("dir:A"), fake) as dav:
        result = await dav.read_file("A/big.txt", max_chars=30000)
    assert result["total_chars"] == 1000 and result["has_more"] is False
    assert result["extraction_complete"] is False and result["truncated"] is True
    assert "limit of 1000 characters" in result["extraction_notes"][0]


@pytest.mark.parametrize("name", ["a.txt", "a.pdf", "a.docx", "a.xlsx", "a.rtf", "a.html"])
def test_time_budget_marks_extraction_incomplete(monkeypatch, name: str) -> None:
    data = {
        "a.txt": b"z" * (3 * extractors.TEXT_CHUNK_BYTES),
        "a.pdf": make_pdf(["p"] * 3),
        "a.docx": docx_bytes(600),
        "a.xlsx": xlsx_bytes({"S": [[i] for i in range(3000)]}),
        "a.rtf": rtf_bytes(3000),
        "a.html": html_bytes(30000),
    }[name]
    result = extract_document(name, io.BytesIO(data), html_visible_text=True, time_limit=-1)
    assert result.complete is False and "time limit" in result.notes[-1]


def test_pdf_page_limit_is_reported(monkeypatch) -> None:
    monkeypatch.setattr(extractors, "MAX_PDF_PAGES", 2)
    result = extract_document("a.pdf", io.BytesIO(make_pdf(["eins", "zwei", "drei"])))
    assert result.complete is False and "first 2 PDF pages" in result.notes[0] and "drei" not in result.text


def test_scanned_pdf_note_is_kept() -> None:
    result = extract_document("scan.pdf", io.BytesIO(make_pdf([""] * 50)))
    assert "no OCR" in result.text and result.text.count("[Page") == 50


# --------------------------------------------------------------------------- consistency between calls
async def test_file_changed_between_calls_is_detected(make_settings) -> None:
    fake = FakeNextcloud(files={"A/doc.md": long_text(2000).encode()})
    async with client(make_settings("dir:A"), fake) as dav:
        first = await dav.read_file("A/doc.md", max_chars=1000)
        fake.files["A/doc.md"] = b"completely new content"
        with pytest.raises(FileChangedError, match="ETag mismatch"):
            await dav.read_file("A/doc.md", offset=first["next_offset"], etag=first["etag"])
        fresh = await dav.read_file("A/doc.md")  # restarting without etag reads the new version
    assert fresh["text"] == "completely new content" and fresh["etag"] != first["etag"]
    assert fake.requests.count(("GET", "A/doc.md")) == 2


async def test_unchanged_etag_is_accepted(make_settings) -> None:
    fake = FakeNextcloud(files={"A/doc.md": b"stable" * 1000})
    async with client(make_settings("dir:A"), fake) as dav:
        first = await dav.read_file("A/doc.md", max_chars=100)
        second = await dav.read_file("A/doc.md", offset=100, max_chars=100, etag=first["etag"])
    assert second["etag"] == first["etag"] and second["offset"] == 100


# --------------------------------------------------------------------------- download limits and resources
async def test_file_size_below_at_and_above_the_limit(make_settings) -> None:
    fake = FakeNextcloud(files={"A/ok.txt": b"a" * 999, "A/edge.txt": b"b" * 1000, "A/big.txt": b"c" * 1001})
    async with client(make_settings("dir:A", max_file_bytes=1000), fake) as dav:
        assert (await dav.read_file("A/ok.txt"))["size_bytes"] == 999
        assert (await dav.read_file("A/edge.txt"))["size_bytes"] == 1000
        with pytest.raises(LimitExceededError, match="download limit of 1000 bytes"):
            await dav.read_file("A/big.txt")
    assert ("GET", "A/big.txt") not in fake.requests  # rejected from the PROPFIND size, before downloading


def test_configurable_limit_range(make_settings) -> None:
    assert make_settings("dir:A").max_file_bytes == 25_000_000
    assert make_settings("dir:A", max_file_bytes=100_000_000).max_file_bytes == 100_000_000


async def test_large_download_is_spooled_to_a_temporary_file_and_deleted(make_settings, monkeypatch) -> None:
    created = []
    original = tempfile.SpooledTemporaryFile

    def tracking(*args, **kwargs):
        spool = original(*args, **kwargs)
        created.append(spool)
        return spool

    monkeypatch.setattr(webdav_module.tempfile, "SpooledTemporaryFile", tracking)
    monkeypatch.setattr(webdav_module, "SPOOL_MEMORY_BYTES", 10_000)
    fake = FakeNextcloud(files={"A/big.csv": ("a;b;Grüße\n" * 20_000).encode()})
    async with client(make_settings("dir:A"), fake) as dav:
        result = await dav.read_file("A/big.csv")
    assert result["total_chars"] == 200_000
    assert len(created) == 1 and created[0]._rolled is True  # went to disk (anonymous, mode 0600)
    assert created[0].closed is True  # and was closed, i.e. deleted, right after extraction


async def test_spool_is_deleted_when_the_download_fails(make_settings, monkeypatch) -> None:
    created = []
    original = tempfile.SpooledTemporaryFile
    monkeypatch.setattr(
        webdav_module.tempfile, "SpooledTemporaryFile", lambda *a, **k: created.append(original(*a, **k)) or created[-1]
    )
    fake = FakeNextcloud(files={"A/x.pdf": b"%PDF-1.4 broken"})
    async with client(make_settings("dir:A"), fake) as dav:
        with pytest.raises(Exception, match="PDF"):
            await dav.read_file("A/x.pdf")
    assert created and all(spool.closed for spool in created)


def test_memory_stays_bounded_for_a_large_text_file() -> None:
    """A 20 MB CSV is decoded in chunks: peak Python memory stays a small multiple of the text."""
    data = ("1234;Lorem ipsum dolor sit amet;Grüße\n" * 550_000).encode()  # ~21 MB
    source = io.BytesIO(data)
    tracemalloc.start()
    try:
        result = extract_document("big.csv", source)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.complete and len(result.text) == 550_000 * 38
    assert peak < 3 * len(data), peak  # text (~21 MB) + one chunk + StringIO copy, no full extra copies


# --------------------------------------------------------------------------- cache bounds
def test_cache_is_bounded_by_size_entries_and_age(monkeypatch) -> None:
    def doc(chars: int) -> extractors.Extraction:
        return extractors.Extraction(text="x" * chars, format=".txt")

    cache = doc_cache.ExtractionCache(max_bytes=50_000, max_entries=3, ttl_seconds=60)
    assert cache.put(("a", "1", False), doc(20_000)) and cache.put(("b", "1", False), doc(20_000))
    assert cache.put(("c", "1", False), doc(20_000))  # evicts the least recently used entry
    assert cache.get(("a", "1", False)) is None and cache.size <= 50_000
    assert cache.put(("huge", "1", False), doc(60_000)) is False  # larger than the cache: not stored
    cache.put(("b", "2", False), doc(10))  # a new ETag replaces the old version of the same file
    assert cache.get(("b", "1", False)) is None and cache.get(("b", "2", False)) is not None
    clock = [1000.0]
    monkeypatch.setattr(doc_cache.time, "monotonic", lambda: clock[0])
    fresh = doc_cache.ExtractionCache(ttl_seconds=60)
    fresh.put(("k", "1", False), doc(10))
    clock[0] += 61
    assert fresh.get(("k", "1", False)) is None and len(fresh) == 0


# --------------------------------------------------------------------------- access control and MCP level
async def test_access_controls_are_unchanged(make_settings) -> None:
    fake = FakeNextcloud(files={"A/ok.txt": b"ok", "A/Intern/secret.txt": b"SECRET", "B/other.txt": b"x"})
    async with client(make_settings("dir:A", denied=("dir:A/Intern",)), fake) as dav:
        for path in ("A/Intern/secret.txt", "B/other.txt"):
            for kwargs in ({}, {"offset": 0}, {"offset": 1, "etag": '"x"'}, {"html_visible_text": True}):
                with pytest.raises(AccessDeniedError):
                    await dav.read_file(path, **kwargs)
    assert fake.requests == []
    assert all(method in {"GET", "PROPFIND"} for method, _ in fake.requests)


async def test_sectioned_reading_through_the_mcp_tool(make_settings) -> None:
    content = long_text(1500)
    fake = FakeNextcloud(files={"00_Agent Test/strategie.md": content.encode()})
    server = create_mcp(make_settings("dir:00_Agent Test"), transport=fake.transport())
    async with Client(server) as mcp_client:
        legacy = await mcp_client.call_tool("read_file", {"path": "00_Agent Test/strategie.md"})
        parts, offset, etag = [], 0, None
        while True:
            args = {"path": "00_Agent Test/strategie.md", "offset": offset, "max_chars": 15000}
            if etag:
                args["etag"] = etag
            result = await mcp_client.call_tool("read_file", args)
            assert not result.is_error
            data = result.structured_content
            parts.append(data["text"])
            etag = data["etag"]
            if not data["has_more"]:
                break
            offset = data["next_offset"]
        negative = await mcp_client.call_tool("read_file", {"path": "00_Agent Test/strategie.md", "offset": -5})
    assert not legacy.is_error and len(legacy.structured_content["text"]) == 16000
    assert legacy.structured_content["truncated"] is True and legacy.structured_content["next_offset"] == 16000
    assert "".join(parts) == content
    assert negative.is_error
