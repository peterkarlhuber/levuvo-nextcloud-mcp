"""0.5.2: RTF text extraction in read_file (valid, damaged, unusual encodings, limits)."""

from __future__ import annotations

import time

import pytest
from conftest import FakeNextcloud
from mcp import Client

from levuvo_nextcloud_mcp import extractors
from levuvo_nextcloud_mcp.errors import DocumentError, LimitExceededError
from levuvo_nextcloud_mcp.extractors import extract_text
from levuvo_nextcloud_mcp.server import create_mcp


def rtf(body: str, header: str = r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fswiss\fcharset0 Arial;}}") -> bytes:
    """Build an RTF document from ASCII source text (RTF itself is a 7-bit format)."""
    return (header + body + "}").encode("ascii")


def text_of(data: bytes, max_chars: int = 30000) -> str:
    return extract_text("doc.rtf", data, max_chars=max_chars)[0]


# --------------------------------------------------------------------------- valid documents
def test_plain_paragraphs_and_formatting_are_removed() -> None:
    data = rtf(r"\pard\plain\f0\fs24 Hello \b bold\b0  and \i italic\i0 .\par Second paragraph\par")
    text, truncated, fmt, encoding = extract_text("doc.rtf", data, max_chars=1000)
    assert text == "Hello bold and italic.\nSecond paragraph"
    assert (truncated, fmt, encoding) == (False, ".rtf", None)
    assert "\\" not in text and "{" not in text


def test_umlauts_via_hex_escapes_in_windows_1252() -> None:
    assert text_of(rtf(r"Gr\'fc\'dfe aus Steyr: \'c4\'d6\'dc \'e4\'f6\'fc\par")) == "Grüße aus Steyr: ÄÖÜ äöü"


def test_unicode_escapes_with_fallback_characters() -> None:
    data = rtf(r"Euro \u8364? Chinese \uc2\u20013\'3f\'3f end \uc1 negative \u-4064?\par")
    assert text_of(data) == "Euro \u20ac Chinese \u4e2d end negative \uf020"


def test_characters_outside_the_bmp_via_surrogate_pairs() -> None:
    assert text_of(rtf(r"Emoji \u-10179?\u-8704?\par")) == "Emoji \U0001f600"


def test_lone_surrogate_is_replaced_not_crashing() -> None:
    assert text_of(rtf(r"Broken \u-10179?\par")) == "Broken �"


def test_font_charset_selects_the_code_page() -> None:
    header = r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fcharset0 Arial;}{\f1\fcharset204 Times New Roman;}}"
    data = rtf(r"{\f1 \'cf\'f0\'e8\'e2\'e5\'f2}, back to \'e4\par", header=header)
    assert text_of(data) == "Привет, back to ä"


def test_ansicpg_sets_the_document_code_page() -> None:
    header = r"{\rtf1\ansi\ansicpg1250{\fonttbl{\f0 Arial;}}"
    assert text_of(rtf(r"\f0 \'b9koda\par", header=header)) == "ąkoda"


def test_unknown_code_page_falls_back_to_windows_1252() -> None:
    header = r"{\rtf1\ansi\ansicpg99999{\fonttbl{\f0 Arial;}}"
    assert text_of(rtf(r"\'e4\par", header=header)) == "ä"


def test_raw_8bit_bytes_are_decoded_with_the_code_page() -> None:
    data = b"{\\rtf1\\ansi\\ansicpg1252 Stra\xdfe\\par}"
    assert text_of(data) == "Straße"


def test_multibyte_code_page_hex_pairs() -> None:
    header = r"{\rtf1\ansi\ansicpg932\deff0{\fonttbl{\f0\fcharset128 MS Mincho;}}"
    assert text_of(rtf(r"\'93\'fa\'96\'7b\par", header=header)) == "日本"


def test_table_cells_and_rows() -> None:
    data = rtf(
        r"\trowd\cellx1000\cellx2000 Name\cell Ort\cell\row"
        r"\trowd\cellx1000\cellx2000 Peter\cell Steyr\cell\row"
    )
    assert text_of(data) == "Name | Ort\nPeter | Steyr"


def test_special_characters_and_symbols() -> None:
    data = rtf(
        r"A\tab B \emdash  C \endash  \lquote x\rquote  \ldblquote y\rdblquote  \bullet  \{\}\\ a\~b soft\-hyphen\par"
    )
    assert text_of(data) == "A\tB — C – ‘x’ “y” • {}\\ a\xa0b softhyphen"


def test_metadata_fonts_styles_and_hidden_destinations_are_dropped() -> None:
    data = rtf(
        r"{\colortbl;\red255\green0\blue0;}{\stylesheet{\s0 Normal;}}{\*\generator Riched20;}"
        r"{\info{\title Secret title}{\author Someone}}{\*\unknowndestination hidden}"
        r"{\header Page header}{\footer Page footer}{\footnote A footnote}Body text\par"
    )
    assert text_of(data) == "Body text"


def test_embedded_objects_pictures_and_field_instructions_are_not_interpreted() -> None:
    data = rtf(
        r'{\field{\*\fldinst HYPERLINK "https://example.invalid/x"}{\fldrslt Link text}}\par'
        r"{\object\objemb{\*\objclass Word.Document.8}{\*\objdata 01050000020000000b000000}{\result Fallback}}"
        r"{\pict\pngblip\picw10\pich10 89504e470d0a1a0a}"
        r"{\*\shppict{\pict\emfblip 0100}}{\nonshppict{\pict\wmetafile8 0100}}After\par"
    )
    assert text_of(data) == "Link text\nAfter"


def test_binary_payload_is_skipped_by_length() -> None:
    payload = b"{}\\par\\\x00\xff"  # braces and control words inside binary data must not be parsed
    data = b"{\\rtf1\\ansi Before {\\pict\\bin" + str(len(payload)).encode() + b" " + payload + b"}After\\par}"
    assert text_of(data) == "Before After"


def test_content_after_the_document_group_is_ignored() -> None:
    assert text_of(rtf(r"Inside\par") + b" trailing garbage {\\b x}") == "Inside"


def test_truncated_document_without_closing_brace_is_still_read() -> None:
    assert text_of(rtf(r"Partial content\par")[:-1]) == "Partial content"


def test_bom_and_leading_whitespace_are_accepted() -> None:
    assert text_of(b"\xef\xbb\xbf\r\n " + rtf(r"Hi\par")) == "Hi"


def test_empty_document() -> None:
    assert text_of(rtf("")) == ""


def test_excess_blank_lines_are_collapsed() -> None:
    assert text_of(rtf(r"A\par\par\par\par B\par")) == "A\n\nB"


# --------------------------------------------------------------------------- damaged or invalid documents
@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"plain text, not RTF",
        b"\x00\x01\x02 binary",
        b"PK\x03\x04 a zip file renamed to .rtf",
        b"{\\rtf1 bad hex \\'zz}",
        b"{\\rtf1 lone backslash at the end \\",
        b"{\\rtf1 \\bin999999 short}",
        b"{\\rtf1 \\" + b"a" * 40 + b" overlong control word}",
    ],
)
def test_damaged_rtf_is_rejected_with_english_message(data: bytes) -> None:
    with pytest.raises(DocumentError, match=r"The RTF file is damaged or not a valid RTF document\."):
        text_of(data)


def test_bare_header_is_an_empty_document() -> None:
    assert text_of(b"{\\rtf") == ""


def test_excessive_nesting_is_rejected() -> None:
    data = b"{\\rtf1 " + b"{" * (extractors.MAX_RTF_DEPTH + 5) + b"x" + b"}" * (extractors.MAX_RTF_DEPTH + 6)
    with pytest.raises(LimitExceededError, match="nested too deeply"):
        text_of(data)


def test_nesting_up_to_the_limit_is_accepted() -> None:
    depth = extractors.MAX_RTF_DEPTH - 1
    data = b"{\\rtf1 " + b"{" * depth + b"deep" + b"}" * depth + b"}"
    assert text_of(data) == "deep"


# --------------------------------------------------------------------------- limits
def test_max_chars_truncates_and_stops_scanning_early() -> None:
    data = rtf(r"0123456789\par " * 5000)
    text, truncated, _, _ = extract_text("doc.rtf", data, max_chars=100)
    assert len(text) == 100 and truncated is True


def test_text_exactly_at_the_limit_is_not_truncated() -> None:
    text, truncated, _, _ = extract_text("doc.rtf", rtf("x" * 100), max_chars=100)
    assert text == "x" * 100 and truncated is False


def test_large_documents_are_processed_in_linear_time() -> None:
    """Crafted input that makes backtracking regex parsers super-linear must stay fast here."""
    hostile = ("{\\field{\\*\\fldinst{HYPERLINK " * 20000 + "}" * 60000).encode()
    started = time.perf_counter()
    with pytest.raises((DocumentError, LimitExceededError)):
        text_of(b"{\\rtf1 " + hostile)
    big = rtf(r"Lorem ipsum dolor sit amet, \'e4\'f6\'fc \u8364? \b bold\b0 \par" * 60000)  # ~4 MB
    text, truncated, _, _ = extract_text("doc.rtf", big, max_chars=30000)
    assert truncated is True and len(text) == 30000
    # Full scan: ~8 MB of skipped picture data and control words before the only visible text.
    skipped = b"{\\rtf1 {\\pict\\pngblip " + b"0f" * 2_000_000 + b"}" + b"{\\*\\x \\b\\i\\ul}" * 200_000 + b" End}"
    assert text_of(skipped) == "End"
    assert time.perf_counter() - started < 10


def test_uppercase_extension_is_supported() -> None:
    assert extract_text("DOC.RTF", rtf(r"Hi\par"), max_chars=100)[0] == "Hi"


# --------------------------------------------------------------------------- through the MCP tool
async def test_read_file_tool_reads_rtf(make_settings) -> None:
    fake = FakeNextcloud(files={"00_Agent Test/Brief.rtf": rtf(r"Sehr geehrte Damen und Herren, Gr\'fc\'dfe\par")})
    server = create_mcp(make_settings("dir:00_Agent Test"), transport=fake.transport())
    async with Client(server) as client:
        result = await client.call_tool("read_file", {"path": "00_Agent Test/Brief.rtf"})
        damaged = FakeNextcloud(files={"00_Agent Test/kaputt.rtf": b"not rtf at all"})
        server2 = create_mcp(make_settings("dir:00_Agent Test"), transport=damaged.transport())
    assert not result.is_error
    assert result.structured_content["format"] == ".rtf"
    assert result.structured_content["text"] == "Sehr geehrte Damen und Herren, Grüße"
    assert "encoding" not in result.structured_content or result.structured_content["encoding"] is None
    async with Client(server2) as client2:
        bad = await client2.call_tool("read_file", {"path": "00_Agent Test/kaputt.rtf"})
    assert bad.is_error and "The RTF file is damaged or not a valid RTF document." in bad.content[0].text
    assert all(method in {"GET", "PROPFIND"} for method, _ in fake.requests + damaged.requests)


async def test_read_file_respects_download_limit_for_rtf(make_settings) -> None:
    fake = FakeNextcloud(files={"A/big.rtf": rtf("x" * 5000)})
    server = create_mcp(make_settings("dir:A", max_file_bytes=1000), transport=fake.transport())
    async with Client(server) as client:
        result = await client.call_tool("read_file", {"path": "A/big.rtf"})
    assert result.is_error and "download limit" in result.content[0].text
