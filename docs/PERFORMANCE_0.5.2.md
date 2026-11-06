# Performance and memory measurements (0.5.2)

As of: version 0.5.2, 2026-11-06.

These measurements justify the `NEXTCLOUD_MAX_FILE_BYTES` default of 25,000,000 bytes and the maximum of 100,000,000 bytes for a small server with about 1 GB of RAM.

## Environment and method

- Measured by the maintainers in a Linux container (4 vCPU, Python 3.13, the locked dependencies of this repository). **Not measured on the Hetzner server itself**; a server with fewer or slower cores will be slower, memory use is comparable.
- Test files were generated synthetically (PDF with text on every page, DOCX/XLSX via python-docx/openpyxl, RTF with umlauts, `\uN` escapes and formatting, HTML with scripts and styles, CSV).
- **Per format:** `extract_document` in a fresh Python process reading from a file object, like the download spool. Peak RSS is `ru_maxrss` of the whole process, including about 35 MB for the interpreter and libraries.
- **End to end:** `read_file` through the real MCP server and an in-memory fake Nextcloud. That process also holds the test files in memory, so only the increase over that baseline is reported.

## Per format

| File | Size | Extracted characters | Time | Peak RSS | Result |
|---|---|---|---|---|---|
| PDF, 1000 pages | 1.4 MB | 4,854,185 | 3.6 s | 56 MB | complete |
| PDF, 300 pages with large embedded data | 91.6 MB | 1,453,083 | 4.2 s | 127 MB | complete |
| DOCX, long body | 2.1 MB | 12.6 M | 1.5 s | 98 MB | complete |
| DOCX, 58 MB `document.xml` | 8.5 MB | 25,000,000 | 3.4 s | 263 MB | stopped at the character limit |
| XLSX, 200,000 rows × 20 columns | 24.8 MB | 25,000,000 | 21.8 s | 85 MB | stopped at the character limit |
| RTF | 35.2 MB | 25,000,000 | 1.7 s | 199 MB | stopped at the character limit |
| RTF | 100.5 MB | 25,000,000 | 1.7 s | 261 MB | stopped at the character limit |
| HTML, raw | 20.6 MB | 20,550,231 | < 0.1 s | 56 MB | complete |
| HTML, raw | 102.5 MB | 25,000,000 | 0.1 s | 68 MB | stopped at the character limit |
| HTML, `html_visible_text=true` | 102.5 MB | 25,000,000 | 1.4 s | 68 MB | stopped at the character limit |
| CSV | 107.6 MB | 25,000,000 | 0.4 s | 67 MB | stopped at the character limit |

For comparison, the 0.5.1 approach (whole download in memory, whole text decoded at once) peaked at 283 MB for the 35 MB RTF file and 217 MB for a 100 MB CSV file.

## End to end through the MCP server

| Scenario | First call | Follow-up section | New downloads for the follow-up | Memory increase |
|---|---|---|---|---|
| 35 MB RTF, one document | 2.1 s | < 0.01 s | 0 (cache hit) | 183 MB |
| 91.6 MB PDF, one document | 4.3 s | < 0.01 s | 0 (cache hit) | 102 MB |
| 5 large files at once (91.6 MB PDF, 35 MB RTF, 24.8 MB XLSX, 1000-page PDF, 20.6 MB HTML) | 32.9 s for all five | 32.7 s for all five | 5 (cache full, entries evicted) | 432 MB |

Notes:

- A follow-up section of the same document costs one `PROPFIND` and no download while the extracted text is in the cache (10 minutes, 96 MB, 8 entries). Python stores text with umlauts at 2 bytes per character, so a 25-million-character RTF text takes about 50 MB of cache.
- When several large documents are read at the same time, the cache cannot hold all of them, and later sections are downloaded and extracted again. Results stay correct (the ETag is checked every time), only slower.
- Extraction runs in at most 2 threads, and only one of them for files above 16 MB, so two very large files are never parsed at the same time.

## Estimate for a 1 GB server

| Part | Approximate memory |
|---|---|
| Server process (Python, MCP, httpx, parsers) | 60 MB |
| Extraction cache, full | 96 MB |
| One large extraction (worst measured case: 58 MB DOCX XML) | up to 300 MB |
| One parallel small extraction (< 16 MB file) | up to 100 MB |
| **Total** | **about 560 MB** |

The measured worst case with five large files requested at once stayed at about 490 MB (432 MB increase plus the base process). This leaves room for the operating system on a 1 GB server, but not for other memory-hungry services on the same machine.

**Conclusion:** the default of 25,000,000 bytes is safe. Values up to 100,000,000 bytes are possible on a 1 GB server if this is the only larger service; set a lower value if the server also runs other applications. Downloads above 4 MB go to a temporary file on disk, so the temporary directory needs free space of up to `NEXTCLOUD_MAX_FILE_BYTES` per parallel read (at most 2).

## Remaining limitations

- At most 25,000,000 characters are extracted per file, within 90 seconds. Longer documents (for example a 100 MB RTF or CSV file) are only reachable up to that point; `extraction_complete` is then `false` and `extraction_notes` says so.
- PDF: at most 5000 pages, no OCR. XLSX: at most 200 sheets and 200 columns, stored values only. DOCX: main body only.
- Large XLSX files are the slowest format (about 22 s for 200,000 rows); a very large workbook can hit the 90-second time limit on a slower server.
- The DOCX parser builds the whole document tree in memory; the 60 MB limit for `word/document.xml` bounds this.
- The `etag` check detects changes between calls only when the agent passes the `etag` back; without it, a changed file is simply read again in its new version.
- Numbers on the Hetzner server itself have not been measured yet.
