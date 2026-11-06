# Levuvo Nextcloud MCP

Read-only MCP server (Model Context Protocol) for Levuvo's Hetzner Storage Share at `https://storage.levuvo.com`. It gives an AI client (e.g. Claude Code) read access to explicitly released files and folders – and to nothing else.

**Documentation:**

- **[docs/LOCAL_SETUP_MACOS.md](docs/LOCAL_SETUP_MACOS.md) – complete step-by-step setup on macOS** (Claude Code, VS Code, positive and negative test)
- [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) – reference for the four MCP tools
- [SECURITY.md](SECURITY.md) – security model, Nextcloud permissions, checklist
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) – troubleshooting
- [docs/REMOTE.md](docs/REMOTE.md) – optional remote operation

## Overview and status

- **Version:** 0.5.2 (Python 3.11+, MIT license).
- **Local (default):** Claude Code starts the server via `stdio` on the Mac. No open port, no hosting.
- **Remote (optional):** Streamable HTTP on `127.0.0.1` behind a TLS reverse proxy, with a static bearer token or OAuth (external identity provider required).
- **Read only:** The server sends only `GET` and `PROPFIND` to Nextcloud. There are no tools for writing, deleting, moving or sharing.

> **Status:** Local operation is implemented and covered by automated tests. **User-reported** live tests on 2026-11-06 (macOS, Claude Code in VS Code, the real Storage Share `storage.levuvo.com`): the first test passed 5/5; the second test made 43 MCP calls, 41 PASS and 2 functional search failures (the root folder `00_Agent Test` was not found by the queries "Agent" and "Agent Test"). These failures are fixed in 0.5.1. No access bypass was observed. These results were reported by the user; they are not tests run by the maintainers or by CI. Until the user re-tests live, the 0.5.1 fix is verified by automated tests only.
>
> A publicly reachable remote endpoint is **not production-ready** and has not been proven in practice: first work through the checklist in [SECURITY.md](SECURITY.md#checklist-before-any-public-operation) and pass tests with the real client. Start by releasing only a test folder without confidential data.

## Tools

Full reference: [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md).

| Tool | Parameters (limits) | Result |
|---|---|---|
| `list_files` | `path` (empty = all released entries), `limit` 1–250, default 100 | Released entries, or the immediate contents of a released folder (`folder`, `items`, `truncated`) |
| `get_file_info` | `path` | Metadata without content: type, size, content type, modification date, ETag, Nextcloud permissions |
| `search_files` | `query` 1–120 characters, `max_depth` 0–6 (default 3), `max_results` 1–100 (default 25) | Matches in the **file or folder name** (no full-text search); since 0.5.1 the name search also matches the explicitly released root folders and files themselves; `complete` shows whether the search was exhaustive |
| `read_file` | `path`, `max_chars` 100–30000 (default 16000), since 0.5.2 optional `offset` (default 0), `etag`, `html_visible_text` | One section of the extracted text (`format`, `size_bytes`, `text`, `truncated`, `encoding` for text files; since 0.5.2 `offset`, `returned_chars`, `next_offset`, `has_more`, `total_chars`, `extraction_complete`, `etag`, `sections`). Long documents are read in several calls with `offset=next_offset` |

All four tools carry the MCP annotations `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true` and `openWorldHint=false` (one fixed Nextcloud, closed scope). The annotations only describe the behavior; it is enforced in the code.

Expected errors (path not released, file too large, Nextcloud unreachable …) are returned as MCP tool errors with a clear message. On unexpected crashes the client receives only a generic message (`Error executing tool <name>`); details go to the server log on stderr.

**Formats supported by `read_file`:** text formats (`.txt .md .markdown .csv .tsv .json .jsonl .yaml .yml .xml .html .htm .log .toml .ini .cfg .py .js .ts .css .sql .rst`), `.pdf`, `.docx`, `.xlsx`, `.rtf`.

- Text: UTF-8 (with or without BOM), UTF-16 with BOM, otherwise Windows-1252 (`encoding: "cp1252"`, typical for Excel CSV). Binary content is rejected.
- PDF: up to 5000 pages with `[Page N]` markers, no OCR; scanned PDFs produce a note. Encrypted PDFs are rejected.
- DOCX: paragraphs and tables of the main body in document order (no headers/footers, text boxes, comments).
- XLSX: up to 200 sheets and 200 columns, all rows (`[Sheet: name]` markers, rows as `12: a | b` with the Excel row number); stored values only, formulas are not evaluated.
- HTML: raw source by default; `html_visible_text=true` returns only the visible text (scripts, styles and markup removed).
- RTF (since 0.5.2): paragraphs, table rows (cells separated by ` | `), umlauts and Unicode; formatting is removed. Embedded objects, pictures, headers, footers and footnotes are skipped, never executed. Damaged RTF files produce a clear error message.
- Office files are checked for zip bombs before extraction; damaged documents produce a clear error message.
- Download limit: `NEXTCLOUD_MAX_FILE_BYTES` (default 25 MB, configurable up to 100 MB), streamed into a temporary file that is deleted after extraction.
- Long documents (since 0.5.2): each call returns at most `max_chars` characters; `has_more`/`next_offset` tell the agent how to continue. Up to 25,000,000 extracted characters per file (90 s extraction time); beyond that `extraction_complete` is `false` and `extraction_notes` explains why. See [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md#reading-long-documents-in-sections) and the measurements in [docs/PERFORMANCE_0.5.2.md](docs/PERFORMANCE_0.5.2.md).

## Quick start: macOS with Claude Code

Short version. The complete walkthrough (cloning, app password, VS Code, positive and negative test) is in **[docs/LOCAL_SETUP_MACOS.md](docs/LOCAL_SETUP_MACOS.md)**.

### 1. Prerequisites

- **Python 3.11 or newer.** The macOS system Python is often 3.9 and does not work. Check with `python3 --version`; otherwise `brew install python@3.12` or [uv](https://docs.astral.sh/uv/) (`brew install uv`; uv downloads a suitable Python itself if needed).
- Claude Code CLI (`claude`).
- A dedicated technical Nextcloud account (e.g. `agent.levuvo`) with an app password and a test folder shared with it **read-only** – setup see [SECURITY.md](SECURITY.md#nextcloud-side-minimal-permissions).

### 2. Install (reproducible via lockfiles)

With uv (recommended):

```bash
cd levuvo-nextcloud-mcp
uv sync --extra dev          # uses uv.lock, creates .venv
```

Alternatively with pip and the hash-checked lockfile:

```bash
cd levuvo-nextcloud-mcp
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
```

`requirements.lock` contains only the runtime dependencies (without test tools).

### 3. Configure

```bash
cp .env.example .env
chmod 600 .env
```

Set at least the following in `.env`:

```dotenv
NEXTCLOUD_URL=https://storage.levuvo.com
NEXTCLOUD_USERNAME=agent.levuvo
NEXTCLOUD_APP_PASSWORD=<app password from Nextcloud>
NEXTCLOUD_ALLOWED_PATHS=dir:00_Agent Test
```

The name must **exactly** match the folder name as `agent.levuvo` sees it in Nextcloud: the Levuvo test folder is `00_Agent Test` with a space, not `00_Agent_Test`. Write spaces literally – no quotes, no `%20`.

Check:

```bash
.venv/bin/levuvo-nextcloud-mcp --check-config      # offline, shows no secrets
.venv/bin/levuvo-nextcloud-mcp --check-nextcloud   # reads metadata of the released entries from Nextcloud
```

### 4. Register in Claude Code

In the project folder:

```bash
claude mcp add --scope user --transport stdio levuvo-nextcloud \
  --env LEVUVO_MCP_ENV_FILE="$(pwd)/.env" \
  -- "$(pwd)/.venv/bin/levuvo-nextcloud-mcp"
claude mcp list
```

An older entry (e.g. from v0.4) must be removed first:

```bash
claude mcp remove levuvo-nextcloud --scope user
```

Then, in Claude Code, for example: "Use levuvo-nextcloud to list the released folders."

`LEVUVO_MCP_ENV_FILE` is needed because Claude Code does not necessarily start the server in the project folder. Without the variable, the server only looks for `.env` next to `pyproject.toml` of a source installation.

## Permissions

Access is controlled exclusively by two variables with identical syntax:

- `NEXTCLOUD_ALLOWED_PATHS` – released entries (required, at least one entry).
- `NEXTCLOUD_DENIED_PATHS` – exceptions within the released entries (optional).

Other or older variables (e.g. `NEXTCLOUD_ALLOWED_ROOTS`) are unknown to v0.5; they are ignored, and the server then refuses to start with "NEXTCLOUD_ALLOWED_PATHS is empty".

### Syntax

Entries are separated by commas. Paths are relative to the technical account's file area (as `agent.levuvo` sees the files in Nextcloud) and separated by `/`.

| Form | Meaning |
|---|---|
| `dir:path` | Folder including all subfolders. If the path is a file in Nextcloud, an error occurs at runtime. |
| `file:path` | Exactly this one file. If the path is a folder, an error occurs at runtime. |
| `path` | The type is detected via Nextcloud. For confidential areas, prefer specifying `dir:`/`file:`. |

```dotenv
NEXTCLOUD_ALLOWED_PATHS=dir:00_Agent Test,dir:01_Unternehmen/Strategie,file:02_Finanzen/Budget_2027.xlsx,dir:05_Projekte/SaaS-Produkte
NEXTCLOUD_DENIED_PATHS=dir:05_Projekte/SaaS-Produkte/Intern,file:01_Unternehmen/Strategie/Personalplanung.docx
```

Names must match the folder and file names exactly as `agent.levuvo` sees them; spaces are written literally (`dir:00_Agent Test`), without quotes and without `%20`.

### Rules

- **Path form:** no leading `/`, no backslash, no `.`/`..` segments, no control or invisible format characters. A trailing `/` is removed. Paths are Unicode NFC-normalized.
- **No URL encoding:** `%20` and similar sequences are rejected. Specify paths unencoded (`Projekt Alpha`, not `Projekt%20Alpha`).
- **Prefixes:** only `dir:` and `file:`, lowercase. `DIR:`, `folder:` etc. are a startup error. If a folder name itself starts with `word:` (e.g. `Projekt:Alpha`), always specify it with a prefix: `dir:Projekt:Alpha`.
- **Released entries are exact:** comparison happens after NFC normalization; case matters. Normalisation can therefore never widen access.
- **Exclusions are cautious:** they also apply to different spellings (case, Unicode variants, trailing dots/spaces in a segment) and **always block the whole subtree**, regardless of `dir:`/`file:`. Exclusion always takes precedence. A prefix on an exclusion is checked as soon as the entry appears in a folder listing; if it contradicts the real type, an error occurs.
- **Same answer:** an excluded path and a never-released path produce the same message ("The path is not released for the MCP agent.").
- **Startup errors** (server does not start, exit code 2):
  - empty list of released entries,
  - duplicate entries, also in different spelling (`dir:Test` and `test`),
  - an exclusion that is not under any released entry (no effect, usually a typo),
  - a released entry that is completely blocked by an exclusion,
  - entries below a `file:` entry,
  - unknown prefixes, invalid paths.

### Pitfalls

- Broad folder releases also release files created **in the future**. Small, targeted releases are safer than broad releases with many exceptions.
- The Nextcloud share and the MCP release are two separate layers: the path must be readable for `agent.levuvo` in Nextcloud **and** released here.
- Commas in file or folder names cannot be specified (comma is the separator).
- Shared folders normally appear in the recipient's root folder, or, depending on the Nextcloud configuration, in a subfolder. What counts is the path `agent.levuvo` sees in the web interface.

## Configuration reference

Values come from real environment variables or a `.env` file. Real environment variables take precedence over the file. File lookup order: `LEVUVO_MCP_ENV_FILE` (must exist if set) → `.env` next to `pyproject.toml` (only in a source installation) → no file. If the file is readable by group or others, the server warns (recommendation: `chmod 600`).

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `NEXTCLOUD_URL` | yes | – | HTTPS address without path and without credentials, e.g. `https://storage.levuvo.com` |
| `NEXTCLOUD_USERNAME` | yes | – | Login name of the technical account |
| `NEXTCLOUD_APP_PASSWORD` | yes | – | App password (not the login password); placeholders are rejected |
| `NEXTCLOUD_USER_ID` | no | = login name | WebDAV user ID, if it differs from the login name (e.g. login by email address) |
| `NEXTCLOUD_ALLOWED_PATHS` | yes | – | Released entries, see [Permissions](#permissions) |
| `NEXTCLOUD_DENIED_PATHS` | no | empty | Exceptions |
| `NEXTCLOUD_MAX_FILE_BYTES` | no | `25000000` | Download limit for `read_file`, 1–100000000 |
| `NEXTCLOUD_TIMEOUT_SECONDS` | no | `20` | Timeout for Nextcloud requests, 1–120 |
| `LEVUVO_MCP_ENV_FILE` | no | – | Explicit path to the `.env` |
| `MCP_PUBLIC_URL` | HTTP only | `https://mcp.levuvo.com/mcp` | Public HTTPS address, must end in `/mcp`, port 443 only |
| `MCP_HTTP_PORT` | HTTP only | `8765` | Local port (1024–65535), always `127.0.0.1` only |
| `MCP_AUTH_MODE` | HTTP only | `static` | `static` or `oauth` |
| `MCP_STATIC_TOKEN` | with `static` | – | Random token, 32–512 characters, no whitespace |
| `MCP_OAUTH_ISSUER` | with `oauth` | – | Issuer of the identity provider (HTTPS, exactly as in the token) |
| `MCP_OAUTH_JWKS_URL` | with `oauth` | – | JWKS address of the identity provider (HTTPS) |
| `MCP_OAUTH_AUDIENCE` | with `oauth` | – | Expected `aud` value of the access token |
| `MCP_OAUTH_SCOPE` | with `oauth` | `files:read` | Required scope |

The `MCP_*` variables are only read and checked with `--transport http`.

## Check commands

Invoke as `levuvo-nextcloud-mcp` or `python -m levuvo_nextcloud_mcp`:

| Command | Effect |
|---|---|
| `--transport stdio` | Default; for local clients such as Claude Code |
| `--transport http` | Streamable HTTP on `127.0.0.1:MCP_HTTP_PORT` |
| `--check-config` | Checks the configuration offline and prints a summary without password/token. With `--transport http`, the remote settings are checked as well. |
| `--check-nextcloud` | Reads each released entry via `PROPFIND` only (never writes), shows its type and Nextcloud permission letters, and distinguishes rights on a share's mount point from rights on its content (`nc:is-mount-root`, `ocs:share-permissions`, immediate children). Prints a WARNING for real write, delete or create rights on content, and a NOTE "not conclusively verified" when points remain open. Exit code 1 on errors. Details: [SECURITY.md](SECURITY.md#permissions-on-the-mount-point-and-on-content). |
| `--version` | Print the version |

Configuration errors terminate the server with exit code 2 and the message `Configuration error: …` on stderr.

## Tests and quality

```bash
uv run --extra dev pytest                 # or: .venv/bin/pytest
uv run --extra dev pytest --cov           # with coverage
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
```

The GitHub Actions pipeline `.github/workflows/ci.yml` checks `uv lock --check`, `ruff check` and `ruff format --check` and runs `pytest` on Python 3.11, 3.12 and 3.13 (Ubuntu) and 3.12 on macOS. Another job installs from `requirements-dev.lock` with `--require-hashes` (the documented pip route). Note: `uv run` without `--extra dev` removes the development tools from `.venv` again.

**Local test run for 0.5.2 (2026-11-06, Python 3.13, maintainer environment):** 478 tests passed, 0 failed; line/branch coverage 92 %. `ruff check`, `ruff format --check` and `uv lock --check` without findings. CI results for 3.11–3.13, macOS and the lockfile install are shown on the pull request.

The automated tests run offline against simulated WebDAV responses. Tests against the real Storage Share with the real client have so far only been reported by the user (see [Overview and status](#overview-and-status) and [Compatibility](#compatibility)).

## Remote operation

Remote is optional and not needed for local operation. Summary:

- The server binds **only `127.0.0.1`**. TLS and public reachability are handled by a reverse proxy or tunnel.
- Transport: Streamable HTTP, stateless, JSON responses, endpoint `/mcp`.
- Protection: host header allowlist (public host from `MCP_PUBLIC_URL` and localhost), no browser origins, request body max. 128 KiB, max. 32 concurrent connections, no server header, no access log.
- Authentication: `MCP_AUTH_MODE=static` (fixed bearer token, protects all routes) or `oauth` (resource server only; login and token issuance are done by an external identity provider).
- The Hetzner Storage Share **cannot** host the Python service.

Options without mandatory hosting costs (local only, own Linux server, Tailscale Funnel, router port forwarding) and all details: [docs/REMOTE.md](docs/REMOTE.md). Example configurations: [deploy/](deploy/).

## Compatibility

| Client | Technically implemented | Automatically tested | Tested with real client | Not verified |
|---|---|---|---|---|
| Claude Code local (`stdio`) | yes | yes, incl. a real stdio subprocess with MCP handshake | yes, user-reported (2026-11-06) | The 0.5.1 search fix with the real client (automated tests only so far) |
| Claude Code CLI remote (`--transport http --header`) | yes (`static` mode) | yes: local Uvicorn server on 127.0.0.1 with a real MCP HTTP client, plus negative tests for token, host, origin and body limit | no | End-to-end against a real deployment |
| Claude Web, custom connector | yes (server side) | server side yes | no | The overall interaction. Requires public HTTPS. According to Claude's help, the connector offers OAuth, "no login" and fixed request headers; whether `static` works with it is unchecked. `oauth` needs an identity provider that works with Claude's flow (automatic registration or a dedicated OAuth client). |
| ChatGPT (Developer Mode / custom MCP connectors) | yes (server side, `oauth`) | server side yes | no | The overall interaction. Requires a suitable plan (according to OpenAI, Developer Mode is available for Plus, Pro, Business, Enterprise, Education on the web; workspace policies can restrict it), public HTTPS and OAuth. OpenAI lists only OAuth, "no authentication" and mixed as authentication – no fixed headers, so `static` cannot be used there. |
| Claude Code on the web (cloud sessions) | – | – | no | Runs in the Anthropic cloud and can only reach a public HTTPS endpoint, not a server on the Mac. |

Sources (as of 2026-11-06): [Claude – Custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp), [OpenAI – ChatGPT Developer Mode](https://developers.openai.com/api/docs/guides/developer-mode), [OpenAI Help – Developer mode and MCP connectors](https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt). Plans and interfaces change; check the current state before setting up.

## Troubleshooting

Common cases (details in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)):

- Python too old (`requires-python >=3.11`) → Homebrew `python@3.12` or uv.
- `.env` not found → set `LEVUVO_MCP_ENV_FILE` with an absolute path.
- 401 → username or app password wrong; 403 → check the account's share permissions.
- 404 for the test folder → the folder name does not match exactly (`00_Agent Test` vs. `00_Agent_Test`).
- Empty listings or "The WebDAV response does not contain the requested path" → set `NEXTCLOUD_USER_ID`.
- "Configured entry type contradicts Nextcloud" → correct `file:`/`dir:`.
- "URL-encoded characters" → enter the path unencoded.
- Startup error with exclusions → an exclusion must lie under a released entry and must not block it completely.
- Newly registered server does not show up in `/mcp` in VS Code → use a Local session and close and reopen the Claude Code chat window (confirmed in the live test).
- Umlauts in CSV → check the `encoding` field.
- Scanned PDF → no OCR; generate the text beforehand.

## Project structure

```
levuvo-nextcloud-mcp/
├── .env.example                 # all variables with placeholders
├── pyproject.toml
├── uv.lock, requirements.lock, requirements-dev.lock
├── src/levuvo_nextcloud_mcp/
│   ├── __main__.py              # python -m levuvo_nextcloud_mcp
│   ├── server.py                # MCP tools, CLI, stdio/HTTP
│   ├── policy.py                # path normalization, allow/deny logic
│   ├── settings.py              # Nextcloud configuration, .env lookup
│   ├── webdav.py                # Nextcloud client (GET/PROPFIND only)
│   ├── extractors.py            # text from TXT/CSV/PDF/DOCX/XLSX/RTF
│   ├── errors.py                # expected errors with user-facing messages
│   ├── remote_settings.py       # remote configuration
│   ├── static_bearer.py         # static bearer token
│   └── jwt_tokens.py            # verification of OAuth JWT access tokens
├── tests/
├── deploy/                      # Caddy and systemd examples
├── docs/LOCAL_SETUP_MACOS.md, docs/MCP_TOOLS.md, docs/REMOTE.md, docs/TROUBLESHOOTING.md
├── .github/workflows/ci.yml
├── SECURITY.md
└── CHANGELOG.md
```

## License

MIT, see [LICENSE](LICENSE).
