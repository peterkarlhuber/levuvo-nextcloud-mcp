# Changelog

## 0.5.2 – 2026-11-06

Feature release. Backward compatible: same four tools, same parameters, same environment variables, same read-only model (`GET`/`PROPFIND` only). No new dependencies; lockfiles unchanged.

### Added

- **`read_file` reads `.rtf` (Rich Text Format).** Paragraphs, line breaks, tabs and table rows (cells separated by ` | `) are extracted; formatting commands are removed. Umlauts and other characters are decoded from `\'hh` escapes using the document code page (`\ansicpg`) or the font charset (`\fcharset`), Unicode from `\uN` (including `\ucN` fallback skipping and surrogate pairs for characters outside the BMP) and raw 8-bit bytes.
- Fonts, colours, styles, document metadata, headers, footers, footnotes, comments, field instructions (the visible field result is kept), embedded objects, pictures and `\binN` binary data are skipped and never interpreted or executed.

### Security

- The RTF reader is built into the project instead of using a third-party library. Every token pattern is bounded or a plain character class, so scanning is linear in the input size even for crafted files; binary payloads are skipped by their declared length; nesting deeper than 256 groups is rejected (`The RTF file is nested too deeply.`). The reviewed library candidate (`striprtf`) applies regular expressions with unbounded `.*` to whole lines of the document and does not handle `\bin` outside pictures, which was not acceptable for untrusted input.
- All existing limits apply unchanged: download limit `NEXTCLOUD_MAX_FILE_BYTES`, `max_chars` (scanning stops early once the limit is reached), at most 2 parallel extraction threads.
- Damaged or invalid files (no `{\rtf` header, invalid `\'` escape, truncated control sequence, overlong control word, `\bin` beyond the end of the file) are rejected with `The RTF file is damaged or not a valid RTF document.` A document that only lacks closing braces is read as far as it goes, like word processors do.

### Documentation and tests

- `read_file` tool description, README, `docs/MCP_TOOLS.md`, `docs/TROUBLESHOOTING.md` and SECURITY.md updated.
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
