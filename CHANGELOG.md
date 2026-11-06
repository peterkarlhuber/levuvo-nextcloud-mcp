# Changelog

## 0.5.3 – 2026-11-06

Feature release: configurable search limits, search in a subfolder, explicit incompleteness reasons, and the running version and active limits in the tool descriptions. Same four tools, same server name and tool IDs, same read-only model (`GET`/`PROPFIND` only), same access rules. New parameters, result fields and environment variables are optional or additive. No new dependencies.

### Added

- **Configurable search limits:** `NEXTCLOUD_SEARCH_MAX_DEPTH` (default 6, 3–20), `NEXTCLOUD_SEARCH_MAX_DIRECTORIES` (default 100, 1–1000) and `NEXTCLOUD_SEARCH_MAX_RESULTS` (default 100, 25–500). They are server-side caps; the per-call defaults stay `max_depth=3` and `max_results=25`. Without the variables, the limits of 0.5.2 apply. The caps are the schema maximums of `max_depth`/`max_results` and are enforced by the server. Invalid values stop the server with `Configuration error: NEXTCLOUD_SEARCH_... must be between ... and ....` or `... must be a number ...`. They never affect which paths are released.
- **`search_files` parameter `path`** (default `""`): search only inside one shared folder (or a folder below a share). The path is checked by the central access policy; a path that is not shared or is excluded fails with `The path is not released for the MCP agent.`, a file fails with `path must be a folder; this is a file. Use get_file_info or read_file.`
- **`search_files` result fields** `path` (the searched folder, `""` for all shares) and `incomplete_reasons` (`depth_limit`, `directory_limit`, `result_limit`; only those that actually applied).
- **Version and active limits in the MCP descriptions:** every tool description starts with `Levuvo Nextcloud MCP v0.5.3 - <title>.` and the server instructions start with `Levuvo Nextcloud MCP v0.5.3.`; the version is derived from `__version__` only. `read_file` states `Configured maximum file size: N bytes.` and the default, `search_files` states the configured maximum depth, directories per search and results. Descriptions and schemas are generated at startup from the validated settings; changes to `.env` require a restart of the MCP process.
- `--check-config` prints `max_file_bytes_default` and a `search` block (`max_depth`, `max_directories`, `max_results`, `concurrency`).

### Changed

- **`complete` of `search_files` is now exact.** It is `true` only if the chosen area was searched completely. Subfolders deeper than `max_depth` now set `complete=false` with `depth_limit` (0.5.2 skipped them and still reported `complete=true`). A search that returns exactly `max_results` hits after scanning everything is now `complete=true` (0.5.2 reported `false`).
- Historical notes such as "fixed in 0.5.1" were removed from the tool descriptions; they belong in this changelog.
- Tool descriptions use a plain ASCII hyphen after the version (`v0.5.3 - Read file.`) because all descriptions are kept ASCII.

### Security

- No change to authentication, HTTPS, the allowlist/denylist or the read-only model. The new variables only bound the work of a search.
- The queue of folders waiting to be scanned is bounded by the folder budget, so a wide tree cannot grow memory without limit. Search concurrency stays at 4 requests; the WebDAV response limits (2 MB, 2000 entries per folder) are unchanged.
- A search with the maximum budget of 1000 folders sends up to 1000 `PROPFIND` requests and can take tens of seconds.
- Tool descriptions contain only the version and numeric limits, never URLs, user names, passwords or tokens.

## 0.5.2 – 2026-11-06

Feature release: RTF support and large-file support with sectioned reading. Same four tools and the same read-only model (`GET`/`PROPFIND` only); existing parameters and result fields are unchanged, new ones are optional or additive. No new dependencies; lockfiles unchanged.

### Added

- **Sectioned reading in `read_file`.** New optional parameters `offset` (default 0), `etag` and `html_visible_text`. New result fields `offset`, `returned_chars`, `next_offset`, `has_more`, `total_chars`, `extraction_complete`, `etag`, plus `extraction_notes` and, for PDF pages and XLSX sheets, `sections` (title and offset). `max_chars` stays the per-call limit (100–30000), so a long document is read in several calls with `offset=next_offset`; concatenating the sections reproduces the extracted text without gaps.
- **Change detection between calls.** Passing the `etag` of a previous response makes the call fail with `The file has changed since the previous read_file call (ETag mismatch). …` instead of mixing two versions of a file.
- **Bounded extraction cache.** Extracted text is kept for up to 10 minutes (max. 96 MB and 8 entries, LRU, keyed by path and ETag), so follow-up sections need one `PROPFIND` and no new download. Access checks still run on every call.
- **Optional visible text for HTML** (`html_visible_text=true`): scripts, styles and markup are removed with the standard library HTML parser.
- Server instructions tell the agent to continue reading when the task requires it, never to treat a partial extraction as the complete document, and to stop early for simple questions.

- **`read_file` reads `.rtf` (Rich Text Format).** Paragraphs, line breaks, tabs and table rows (cells separated by ` | `) are extracted; formatting commands are removed. Umlauts and other characters are decoded from `\'hh` escapes using the document code page (`\ansicpg`) or the font charset (`\fcharset`), Unicode from `\uN` (including `\ucN` fallback skipping and surrogate pairs for characters outside the BMP) and raw 8-bit bytes.
- Fonts, colours, styles, document metadata, headers, footers, footnotes, comments, field instructions (the visible field result is kept), embedded objects, pictures and `\binN` binary data are skipped and never interpreted or executed.

### Changed

- **Larger files.** `NEXTCLOUD_MAX_FILE_BYTES` default raised from 8,000,000 to 25,000,000 bytes; the allowed range is now 1–100,000,000 (was 1–30,000,000). Both values were checked with measurements, see `docs/PERFORMANCE_0.5.2.md`.
- **Streaming downloads.** Files are streamed into a spooled temporary file (memory up to 4 MB, then an anonymous file on disk that is deleted after extraction, also on errors) instead of being held in memory. Text formats are decoded incrementally.
- **Higher format limits.** PDF up to 5000 pages (was 40) with `[Page N]` markers; XLSX up to 200 sheets and 200 columns with all rows (was 10 sheets, 1000 rows, 60 columns); long DOCX, RTF, HTML, TXT, MD, CSV and JSON files are fully reachable. Per file at most 25,000,000 characters are extracted within 90 seconds; when a limit stops extraction, `extraction_complete` is `false` and `extraction_notes` says why.
- XLSX rows now carry their Excel row number (`12: a | b`); empty rows are skipped.
- `truncated` is now `true` whenever the response does not contain the complete document (`has_more`, `offset > 0` or incomplete extraction). Limit notes that 0.5.1 appended to `text` are now in `extraction_notes`; the scanned-PDF note stays in the text.
- Concurrency: at most 2 extraction threads as before, and only one of them for files above 16 MB or of unknown size.

### Security

- Office zip-bomb check extended: at most 5000 entries, 600 MB uncompressed in total, 300 MB per entry, a compression-ratio limit for large archives, and 60 MB for the main XML part (`word/document.xml`, `xl/sharedStrings.xml`).
- The RTF reader is built into the project instead of using a third-party library. Every token pattern is bounded or a plain character class, so scanning is linear in the input size even for crafted files; binary payloads are skipped by their declared length; nesting deeper than 256 groups is rejected (`The RTF file is nested too deeply.`). The reviewed library candidate (`striprtf`) applies regular expressions with unbounded `.*` to whole lines of the document and does not handle `\bin` outside pictures, which was not acceptable for untrusted input.
- The RTF reader is bound by the same limits as the other formats: download limit, character and time budget, at most 2 parallel extraction threads.
- Damaged or invalid files (no `{\rtf` header, invalid `\'` escape, truncated control sequence, overlong control word, `\bin` beyond the end of the file) are rejected with `The RTF file is damaged or not a valid RTF document.` A document that only lacks closing braces is read as far as it goes, like word processors do.

### Documentation and tests

- `read_file` tool description, server instructions, README, `docs/MCP_TOOLS.md` (with a multi-call example), `docs/TROUBLESHOOTING.md`, `docs/LOCAL_SETUP_MACOS.md`, SECURITY.md and `.env.example` updated. New `docs/PERFORMANCE_0.5.2.md` with the measurements behind the limits.
- New `tests/test_large_documents.py`: gap-free reconstruction over many offset calls, end boundary, invalid and negative offsets, PDF with 120 pages, large DOCX and RTF, XLSX with many sheets and rows, raw and visible HTML, character and time budgets, PDF page limit, sizes just below, at and above the download limit, a file changed between calls, temporary files closed on success and failure, memory peak for a 21 MB CSV, cache bounds and TTL, unchanged access controls.
- New `tests/test_rtf_extraction.py`: valid documents, umlauts, Unicode and surrogates, Cyrillic, Central European and Japanese code pages, tables, special characters, skipped destinations, objects/pictures/binary data, damaged files, nesting and `max_chars` limits, a linear-time check with large crafted input, and `read_file` through the real MCP tool including the download limit.

## 0.5.1 – 2026-11-06

Patch release. Backward compatible: same four tools, same parameters, same environment variables, same read-only model (`GET`/`PROPFIND` only).

### Background: live tests reported by the user on 2026-11-06

These results were reported by the user (macOS, Claude Code in VS Code, real Storage Share `storage.levuvo.com`). The maintainers and CI did not run them:

- First test: 5 of 5 checks passed.
- Second test: 43 MCP calls, 41 passed, 2 functional search failures (see the search fix below). No access bypass was observed.
- `--check-nextcloud` reported the released root folder `00_Agent Test` as `SGDN` and its file `test.txt` as `SG`, and therefore warned about write permissions. The web UI offered no edit or delete actions for the file.

### Fixed

- **`search_files` finds explicitly released root entries.** In 0.5.0 released folders from `NEXTCLOUD_ALLOWED_PATHS` were only used as starting points and never compared with the search term, so `search_files("Agent")` and `search_files("Agent Test")` did not find `00_Agent Test`. Root folders are now candidates like every other entry. The metadata was already loaded, so this adds no WebDAV request. Directly released files behave as before. Deduplication, `max_results`, `max_depth` and `complete` are unchanged.
- **`--check-nextcloud` separates the share's mount point from its content.** In addition to `oc:permissions`, the check now requests `nc:mount-type`, `nc:is-mount-root` and `ocs:share-permissions` and inspects the immediate entries of each released folder (one depth-1 `PROPFIND`, never write attempts). `D` on a mount root is documented by Nextcloud as "unshare"; `N`/`V` on a mount root are undocumented and are reported as an open point ("not conclusively verified - manual check required"). Real write, delete or create permissions still produce a WARNING. Unclear cases produce a NOTE. WebDAV errors exit with code 1. See SECURITY.md.

### Changed

- `--check-nextcloud` output: the 0.5.0 keys `entry`, `is_dir`, `permissions` and `writable_in_nextcloud` are unchanged. New, additive keys: `assessment`, `content_writable`, `verified`, `mount_type`, `mount_root`, `share_permissions`, `children_checked`, `children_truncated`, `children_with_write_permissions`, `notes`, `open_points`.
- **English throughout:** server instructions, tool titles and descriptions, parameter descriptions, error messages, CLI output, code comments, tests and documentation are now in English. Tool IDs, parameter names, environment variables and JSON keys are unchanged. Clients or scripts that matched German message texts must be adjusted.
- More precise tool descriptions for MCP tool discovery (purpose, parameters, defaults, limits, result structure, errors) and new server instructions for the model.
- Examples use the real test folder name `dir:00_Agent Test` (with a space).

### Documentation

- New `docs/LOCAL_SETUP_MACOS.md`: complete local setup on macOS (no SSH or Hetzner server needed for stdio; GitHub CLI; `uv sync --extra dev --frozen`; `.env`; app password; checks; `claude mcp add` and the `$(pwd)` pitfall; VS Code Local session and reopening the chat window; MCP-only positive/negative test; optional SSH appendix).
- New `docs/MCP_TOOLS.md`: reference for the four tools.
- SECURITY.md explains the difference between the MCP server's write ban and the Nextcloud account's broader permissions, and the semantics used by `--check-nextcloud`.
- README status updated with the user-reported live tests. A public remote endpoint is still not production-ready.
- The historical report `docs/ABSCHLUSSBERICHT_v0.5.0.md` is kept unchanged (German).

### Tests

- Regression tests for the search fix (root names with spaces, case-insensitive terms, multiple and overlapping roots, `file:` shares, subfolders, empty results, `max_results`, depth 0, denylist, nothing outside the policy, no duplicates, request count, real MCP tool call).
- Tests for the permission diagnostics (share root `SGDN` with child `SG`, real write permissions on children, write share bits, empty folder, `file:` share, missing properties, own storage, truncated listings, denied children, WebDAV errors, CLI wording and exit codes).
- Tool discovery tests (exactly four tools, compatible schemas, English texts, read-only annotations).

## 0.5.0 – 2026-11-06

### Breaking changes

- Prefixed entries in `NEXTCLOUD_DENIED_PATHS` (`dir:`, `file:`) are now evaluated like allowed entries instead of being read as part of the path.
- Stricter startup validation: duplicates (also in different spelling), ineffective exclusions, fully blocked shares, entries below `file:` shares and unknown prefixes (`DIR:`, `folder:` …) are startup errors (exit code 2).
- URL-encoded paths (e.g. `%20`) are rejected; paths must be given unencoded.
- `read_file` additionally returns the field `encoding` for text files.
- `create_mcp(settings, …)` and `build_http_app(settings, remote, …)` now expect a `Settings` object.

### Security

- SEC-01: Exclusions understand the same prefixes `dir:`/`file:` as allowed entries (in v0.4 `dir:X` was read as a literal path and had no effect); unknown prefixes are startup errors.
- SEC-02: Central path policy (`policy.py`) with Unicode NFC normalisation of all paths (configuration, request, Nextcloud `href`). Allowed entries match exactly; normalisation never widens access.
- SEC-03: Exclusions are compared conservatively (NFKC, case, trailing dots/spaces per segment) and always block the whole subtree; they take precedence over allowed entries.
- SEC-04: SECURITY.md describes the minimal permissions of the technical Nextcloud account (read-only shares, no own home folder in the allowlist, app password rotation, quota is no access control); `--check-nextcloud` reports write permissions of the account.
- SEC-05: Ineffective (outside every share), duplicate or contradictory entries prevent startup (fail closed).
- SEC-06: `PROPFIND` responses are streamed and aborted at 2 MB; DTDs/entities in XML are forbidden.
- SEC-07: JWKS keys are cached for 5 min; an unknown `kid` triggers at most one refresh per 60 s process-wide. RS256 only, `typ` checked, ID tokens and tokens over 8 KB rejected.
- SEC-08: OAuth: `AccessToken` carries the real audience and `client_id`/`azp`; the SDK resource check applies when `MCP_OAUTH_AUDIENCE` = `MCP_PUBLIC_URL`.
- SEC-09: Expected errors are no longer logged as crashes with tracebacks; error messages contain no credentials; `Settings`/`RemoteSettings` hide secrets in `repr`.
- Additionally: control/format characters and URL-encoded sequences in paths are rejected; `href` values are decoded exactly once per segment (an encoded `/` does not create a new level), foreign hosts/users are discarded; excluded and never-released paths return the same message; warning for a `.env` readable by others; static token with case-insensitive `Bearer` scheme.

### MCP

- MCP-01: Expected errors (not released, not found, format, limits, Nextcloud errors) reach the client as MCP tool errors (`ToolError`) with a German message (English since 0.5.1); unexpected crashes only with a generic message.
- MCP-02: All tools with `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false` and a title.
- MCP-03: Parameter limits in the JSON schema (pydantic `Field`); tools additionally return structured results.
- MCP-04: Client compatibility documented honestly (README, docs/REMOTE.md), including a correction: according to the help center, Claude's connector UI offers fixed request headers (not verified with this server).
- MCP-05: Dependencies pinned (`mcp>=2.3,<2.4`) and reproducible via lockfiles; SDK API tested against MCP SDK 2.3.0.

### WebDAV and documents

- WD-01: New variable `NEXTCLOUD_USER_ID`; if the requested path is missing from the WebDAV response, the error message explains the likely cause.
- WD-02: One pooled HTTPS client per process (keep-alive, max. 8 connections) instead of one per call; type check of released entries cached for 5 min.
- WD-03: File name search as breadth-first search with at most 4 parallel requests (measured: 61 folders at 20 ms latency well below 0.9 s instead of ≥ 1.2 s sequentially).
- WD-04: Text files: UTF-8 (with/without BOM), UTF-16 with BOM, fallback Windows-1252 (field `encoding`); binary content rejected.
- WD-05: Document extraction in a worker thread (max. 2 in parallel), does not block the event loop.
- WD-06: DOCX with paragraphs and tables in document order; clear messages for damaged DOCX/XLSX/PDF; hint for PDFs without text (no OCR).
- Additionally: messages for 401, 403, 404, 429 (with `Retry-After`), 3xx, 5xx and timeouts.

### Configuration

- CFG-01: New variable `LEVUVO_MCP_ENV_FILE`; otherwise `.env` next to `pyproject.toml` of a source installation, otherwise environment variables only. Environment variables take precedence.
- CFG-02: macOS installation guide with Python version check, uv and the pip lockfile route.
- CFG-03: Prefixes lowercase only; other spellings are startup errors instead of silently becoming part of the path.
- New CLI options `--check-config`, `--check-nextcloud` and `--version`; configuration errors exit with code 2 without a traceback.

### Quality

- QA-01: Tests through a real MCP client (in-process, stdio subprocess and Streamable HTTP via Uvicorn) for all four tools.
- QA-02: Targeted security and edge-case tests (Unicode NFC/NFD, case, prefixes, traversal, URL encoding, special characters, XML attacks, HTTP errors, timeouts, limits, concurrency); unspecific `pytest.raises(Exception)` replaced.
- QA-03: GitHub Actions CI (lockfile check, `ruff`, `pytest` with coverage on Python 3.11–3.13 and macOS, pip installation from the hashed lockfile); `uv.lock`, `requirements.lock`, `requirements-dev.lock`.
- A single version source (`__init__.py`, dynamic in `pyproject.toml`), with a consistency test.

### Remote

- OPS-02: Hardened examples for systemd and Caddy; Uvicorn without server header and access log, `limit_concurrency=32`.

### Documentation

- README, SECURITY.md and `.env.example` revised; new `docs/REMOTE.md` (remote options without mandatory hosting costs) and `docs/TROUBLESHOOTING.md`; honest compatibility table.

## 0.4.0 – 2026-11-05

- Consistent configuration names: `NEXTCLOUD_ALLOWED_PATHS` and `NEXTCLOUD_DENIED_PATHS`; no alias for old names.
- `NEXTCLOUD_ALLOWED_PATHS`: any mix of several files and folders, comma-separated.
- Explicit `file:` (exactly one file) and `dir:` type prefixes; unprefixed paths are detected automatically via WebDAV.
- `NEXTCLOUD_DENIED_PATHS`: optional, comma-separated exclusions; excluded subtrees; deny before allow.
- `list_files("")` lists allowed files and folders with real metadata; individually released files are found by name in `search_files`.
- Excluded paths are rejected before the network request or filtered from directory listings and search results.
- Type check: `file:` must not point to a folder and `dir:` must not point to a file.
- Local offline tests, including new permission, metadata, listing and search tests.
- No additional write tool; local/remote architecture from v0.2 unchanged.

## 0.2.0 – 2026-11-05

- Kept the local Claude Code mode (`stdio`).
- Added remote MCP via Streamable HTTP (`--transport http`).
- Remote HTTP binds to `127.0.0.1` only.
- Two authentication options: fixed bearer token for small, limited tests; OAuth resource server with an external RS256 JWT IdP.
- Host/Origin allowlist, stateless HTTP, JSON responses and request body limit.
- Caddy and systemd examples plus complete setup and security notes.
- Existing document/folder functions unchanged; only four read tools.
- 31 offline tests passed; real MCP SDK and online integration still pending.
