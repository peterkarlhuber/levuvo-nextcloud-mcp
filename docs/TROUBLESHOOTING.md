# Troubleshooting

First steps for any problem:

```bash
.venv/bin/levuvo-nextcloud-mcp --version
.venv/bin/levuvo-nextcloud-mcp --check-config
.venv/bin/levuvo-nextcloud-mcp --check-nextcloud
claude mcp list
```

`--check-config` also shows which configuration file was loaded (`config_file`).

## Installation

**`requires a different Python` / `Package requires Python >=3.11`**
The macOS system Python is often 3.9. Fix: `brew install python@3.12` and create the venv with `python3.12 -m venv .venv`, or use `uv sync --extra dev` (uv fetches a suitable Python).

**`--require-hashes` error with pip**
The lockfile does not match the platform or has been modified. Install with `uv sync --extra dev` or have the lockfile re-exported.

## Configuration

**`Configuration error: NEXTCLOUD_URL must … / NEXTCLOUD_USERNAME is missing` although `.env` is filled in**
The file was not found. Claude Code does not necessarily start the server in the project folder. Fix: set `LEVUVO_MCP_ENV_FILE` with an absolute path (see README, `claude mcp add --env …`). Without the variable, only `.env` next to `pyproject.toml` of a source installation is read. Real environment variables override values from the file.

**`LEVUVO_MCP_ENV_FILE does not point to an existing file`**
Check the path; `~` is expanded, relative paths are relative to the process's working directory.

**Warning "The configuration file … is readable by other users"**
`chmod 600 .env`.

**`NEXTCLOUD_ALLOWED_PATHS is empty`**
The variable is missing or has a different name. v0.5 only knows `NEXTCLOUD_ALLOWED_PATHS` and `NEXTCLOUD_DENIED_PATHS`; older names such as `NEXTCLOUD_ALLOWED_ROOTS` are ignored.

**`NEXTCLOUD_APP_PASSWORD is missing or still contains a placeholder`**
Values starting with `EIGENES_`, `HIER_`, `CHANGE_ME` or `<` are treated as placeholders.

**`unknown prefix 'DIR:'` (or `folder:`, `Projekt:` …)**
Only `dir:` and `file:` in lowercase are valid. If a folder name starts with `word:`, write the entry with a prefix: `dir:Projekt:Alpha`.

**`… refer to the same path`**
Two entries differ only in spelling or prefix (`dir:Test`, `test`). Remove one of them.

**`NEXTCLOUD_DENIED_PATHS: '…' does not lie below any share from NEXTCLOUD_ALLOWED_PATHS`**
An exclusion must lie within a released entry, otherwise it has no effect – usually a typo in the path. Nothing can be excluded below a `file:` entry.

**`Contradictory configuration: the share … is completely blocked by the exclusion …`**
An exclusion covers an entire released entry (also in different spelling). Remove one of the two entries.

**`… lies below the single file …`**
There can be no further entries below a `file:` entry.

**`The path contains URL-encoded characters (e.g. %20)`**
Enter paths as they are displayed in Nextcloud: `dir:05_Projekte/Projekt Alpha`, not `Projekt%20Alpha`. This applies in `.env` and in tool calls.

## Nextcloud

**`Nextcloud authentication failed` (HTTP 401)**
Login name or app password wrong, or the app password has been revoked. Create a new app password under *Settings → Security → Devices & sessions* ("Einstellungen → Sicherheit → Geräte & Sitzungen"). Repeated failed attempts can trigger Nextcloud's brute-force protection.

**`Nextcloud denied access` (HTTP 403)**
The account has no read rights on this path in Nextcloud. Check the share.

**`File or folder not found` (HTTP 404)**
Check the path from the perspective of `agent.levuvo`: received shares normally appear in its root folder (depending on the Nextcloud configuration also in a subfolder) and may have been renamed there. Case matters.

If `list_files` or `search_files` **without a path** fail with this message, Nextcloud answered 404 for at least one entry of `NEXTCLOUD_ALLOWED_PATHS`: these calls request every configured entry first and stop at the first error instead of returning a partial result, and the message does not name the entry (confirmed code behaviour). A common cause is an entry that no longer exists for `agent.levuvo` (deleted, renamed, moved or unshared), but a 404 can also have other causes. Run `--check-nextcloud` to see which entry fails. A short-lived occurrence with an undetermined cause was observed during the 0.5.3 live test (see [LIVE_VALIDATION.md](LIVE_VALIDATION.md#observations-and-findings)).

**404 for the test folder: `00_Agent Test` vs. `00_Agent_Test`**
The name in `NEXTCLOUD_ALLOWED_PATHS` must match the folder name exactly as `agent.levuvo` sees it. The Levuvo test folder is `00_Agent Test` with a **space**; `dir:00_Agent_Test` (underscore) points to a non-existent path and results in a 404. Write the space literally, without quotes and without `%20`: `NEXTCLOUD_ALLOWED_PATHS=dir:00_Agent Test`.

**Empty listings or `The WebDAV response does not contain the requested path`**
The WebDAV user ID differs from the login name (common when logging in with an email address). Set `NEXTCLOUD_USER_ID`. The ID is shown in the Nextcloud web interface under *Files → Settings → WebDAV* ("Dateien → Einstellungen → WebDAV") in the displayed address (`…/remote.php/dav/files/<ID>/`).

**`Configured entry type contradicts Nextcloud: '…' is actually a folder/file`**
`file:` is in front of a folder or `dir:` in front of a file – in released entries or exclusions. Correct the prefix.

**`Nextcloud is currently rate-limiting requests (HTTP 429)`**
Nextcloud is throttling. Wait (for the indicated number of seconds, if given) and run searches with a smaller `max_depth`.

**`Timeout while connecting to Nextcloud.` / `Connection to Nextcloud failed (network or TLS)`**
Check the network. Proxy settings of the environment are deliberately ignored. For slow responses, increase `NEXTCLOUD_TIMEOUT_SECONDS` (max. 120).

**`Nextcloud responded with a redirect`**
`NEXTCLOUD_URL` is wrong (e.g. `http` instead of `https`, wrong hostname). Redirects are not followed for security reasons.

**`The Nextcloud directory response is too large` / `Too many directory entries`**
Folder with more than 2000 entries or a response over 2 MB. Release or list a subfolder instead.

**`--check-nextcloud` warns about write/delete rights (WARNING)**
`WARNING: The technical account has write, delete or create permissions in Nextcloud on the contents of: …` – the share with `agent.levuvo` is not read-only, or it is a folder owned by the account itself. Change the share to read-only (see [SECURITY.md](../SECURITY.md#nextcloud-side-minimal-permissions)).

**`--check-nextcloud` prints a NOTE "not conclusively verified"**
`NOTE: Permissions not conclusively verified - manual check required for: …` – this is not an error, but the automatic check could not settle everything (typically `N`/`V` on the mount point of a received share, or subfolders that were not checked). Read the `open_points` field of the entry in the JSON output and check manually as described in [SECURITY.md](../SECURITY.md#permissions-on-the-mount-point-and-on-content): in the web interface as `agent.levuvo`, no edit, delete, rename or move actions may be offered on the files, and the sharing account sees only "Read" ("Lesen") for the share with `agent.levuvo`.

**`Nextcloud check failed: …` / `Nextcloud check failed for …: …` (exit code 1)**
The check could not run at all, or an entry could not be read (connection, login or WebDAV error). See the corresponding entries above.

## Reading files

**Umlauts in CSV are wrong**
The `encoding` field in the response shows the detected encoding. `cp1252` is typical for Excel exports on Windows and is decoded correctly. If the text still looks wrong, the file has a different encoding (e.g. UTF-16 without BOM); save the file as UTF-8.

**`The file appears to be binary`**
The file extension is a text format, but the content is not. Check the file.

**PDF returns no text / note "possibly a scanned PDF (no OCR)"**
There is no OCR. Run text recognition on the PDF beforehand. Encrypted PDFs are not read. At most 5000 pages are processed; `extraction_notes` says when pages were skipped.

**Text from DOCX is missing**
Only paragraphs and tables of the main body are read – no headers/footers, text boxes or comments.

**XLSX shows no formula results or is incomplete**
Only values stored in the file are read; formulas are not evaluated (save the file in Excel so that values are present). Limits: 200 sheets and 200 columns; skipped sheets or columns are listed in `extraction_notes` and `extraction_complete` is `false`.

**`The file exceeds the download limit`**
Increase `NEXTCLOUD_MAX_FILE_BYTES` (default 25000000, max. 100000000; see docs/PERFORMANCE_0.5.2.md for the memory needed) or use a smaller file.

**Only part of a long document is returned**
This is expected: each call returns at most `max_chars` characters. If `has_more` is `true`, call `read_file` again with `offset` set to `next_offset` and the returned `etag`. `extraction_complete: false` means that a limit (25,000,000 characters, 90 seconds, 5000 PDF pages, 200 sheets/columns) stopped extraction; the reason is in `extraction_notes`.

**`The file has changed since the previous read_file call (ETag mismatch)`**
The file was modified between two section calls. Read it again from `offset` 0 without `etag`; earlier sections may no longer match.

**`offset … is beyond the end of the extracted text`**
Use `next_offset` from the previous response; `total_chars` is the length of the extracted text.

**`File format … is not supported`**
Supported: text formats (see README), `.pdf`, `.docx`, `.xlsx`, `.rtf` (since 0.5.2). Convert old formats (`.doc`, `.xls`) beforehand.

**`The RTF file is damaged or not a valid RTF document.`**
The file does not start with `{\rtf`, is cut off inside a control sequence or contains an invalid escape. Often the file is a different format with an `.rtf` extension (e.g. a renamed `.doc` or `.docx`). Open and save it again as RTF, or convert it to `.docx`/`.pdf`.

**RTF text is missing headers, footers, footnotes or images**
Intended: only the main body text is extracted; embedded objects and pictures are skipped and never executed.

**`search_files` does not find content**
The search only checks file and folder names. `complete: false` means that the depth, the number of results or the limit of 100 folders was reached.

**`search_files` did not find a released root folder (0.5.0)**
In 0.5.0, the name search only looked inside the released folders, not at the released entries themselves: the queries "Agent" and "Agent Test" did not find the root folder `00_Agent Test` (live test of 2026-11-06, user report). Fixed in 0.5.1: the search also matches explicitly released root folders and files. Update (`git pull`, `uv sync --extra dev --frozen`), then close and reopen the Claude Code chat window.

## Claude Code

**Server does not appear or shows "failed" in `claude mcp list`**
Check the absolute path to `.venv/bin/levuvo-nextcloud-mcp` and run the command once directly in the terminal with `--check-config`. Remove the old entry with `claude mcp remove levuvo-nextcloud --scope user` and add it again.

**Newly registered server does not show up in `/mcp` in VS Code**
`claude mcp list` in the terminal shows "Connected", but the server is missing in `/mcp` in the Claude Code extension in VS Code. Fix: use a **Local** session (cloud/web sessions do not run on the Mac and cannot reach the local server), then **close and reopen the Claude Code chat window**. A chat window that is already open does not reload the MCP configuration. Confirmed in the live test of 2026-11-06 (user report).

**Tool only reports `Error executing tool …` without details**
An unexpected error. Details are in the server's stderr log (in Claude Code via the MCP logs, or by starting the server directly in the terminal).

## Remote

**401 despite token**
The header must be `Authorization: Bearer <token>` (exactly one header, no extra whitespace in the token). The proxy must pass the header through.

**421 `Invalid Host header`**
The host of the request does not match `MCP_PUBLIC_URL`. The proxy must pass the original `Host` through; set `MCP_PUBLIC_URL` to the actual domain.

**403 `Invalid Origin header`**
Browser requests (with an `Origin` header) are not permitted.

**413 `Request body too large`**
Requests over 128 KiB are rejected.

## Version, limits and search (since 0.5.3)

**Claude reports an old version or old limits**
Tool descriptions and schemas are generated when the MCP process starts. After `git pull`/`uv sync` or a change to the `.env`, restart the MCP process (quit and reopen Claude Desktop, or reconnect the server via `/mcp` in Claude Code). Check with `.venv/bin/levuvo-nextcloud-mcp --version` and `.venv/bin/levuvo-nextcloud-mcp --check-config`; every tool description starts with `Levuvo Nextcloud MCP v<version> - ...`, and `read_file` shows `Configured maximum file size: N bytes.`

**`search_files` returns `complete: false`**
`incomplete_reasons` says why: `depth_limit` - subfolders deeper than `max_depth` were not searched (raise `max_depth` or search a subfolder with `path`); `directory_limit` - the folder budget `NEXTCLOUD_SEARCH_MAX_DIRECTORIES` was used up (search a subfolder with `path` or raise the budget); `result_limit` - more hits exist than `max_results` (narrow the query or raise `max_results`).

**`max_depth must be between 0 and N` / `max_results must be between 1 and N`**
N is the server-side cap from `NEXTCLOUD_SEARCH_MAX_DEPTH` / `NEXTCLOUD_SEARCH_MAX_RESULTS`. Use a smaller value or raise the cap in the `.env` (max. 20 / 500) and restart the MCP process.

**`Configuration error: NEXTCLOUD_SEARCH_MAX_DEPTH must be between 3 and 20.`**
Allowed ranges: `NEXTCLOUD_SEARCH_MAX_DEPTH` 3–20, `NEXTCLOUD_SEARCH_MAX_DIRECTORIES` 1–1000, `NEXTCLOUD_SEARCH_MAX_RESULTS` 25–500; whole numbers only.

**`path must be a folder; this is a file`**
`search_files` with `path` searches inside a folder. For a single file use `get_file_info` or `read_file`.

**A large search is slow**
With `NEXTCLOUD_SEARCH_MAX_DIRECTORIES=1000` a search sends up to 1000 `PROPFIND` requests (4 in parallel), which can take tens of seconds. Use `path` to start in the relevant subfolder.
