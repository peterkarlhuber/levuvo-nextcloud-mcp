# Local setup on macOS (Claude Code, stdio)

This guide sets up `levuvo-nextcloud-mcp` completely on a Mac: Claude Code starts the server locally via `stdio` and uses it to read explicitly released files from the Hetzner Storage Share `https://storage.levuvo.com`.

As of: version 0.5.3, 2026-11-06.

> **No SSH and no Hetzner Cloud server required.** Local stdio operation only needs the Mac, the GitHub repository and a Nextcloud app password. No port is opened and nothing is hosted. The existing SSH key `levuvo_hetzner` only matters for a later server deployment (see [Appendix: SSH key](#appendix-ssh-key-only-for-later-server-operation)).

## Overview

1. Install tools (Homebrew, uv, GitHub CLI, Claude Code)
2. Clone the repository
3. Install dependencies reproducibly
4. Create an app password in Nextcloud
5. Create `.env`
6. Run the check commands
7. Register the server in Claude Code
8. Use it in VS Code
9. Positive and negative test via MCP

## 1. Prerequisites

| Tool | Check | Install |
|---|---|---|
| Homebrew | `brew --version` | see <https://brew.sh> |
| uv | `uv --version` | `brew install uv` (uv downloads Python 3.11+ itself if needed; the macOS system Python 3.9 is not sufficient) |
| GitHub CLI | `gh --version` | `brew install gh` |
| Claude Code CLI | `claude --version` | as described in the Claude Code documentation |
| VS Code with the Claude Code extension | – | optional, see step 8 |

On the Nextcloud side, you need a dedicated technical account `agent.levuvo` without admin rights, with which the test folder is shared **read-only** (see [SECURITY.md](../SECURITY.md#nextcloud-side-minimal-permissions)).

## 2. Clone the repository

The repository is private. The GitHub CLI handles authentication via HTTPS:

```bash
gh auth status            # shows whether and as whom you are logged in
gh auth login             # only if not logged in: GitHub.com, HTTPS, confirm in the browser
```

Clone, e.g. into `~/Projekte`:

```bash
mkdir -p ~/Projekte && cd ~/Projekte
gh repo clone peterkarlhuber/levuvo-nextcloud-mcp
cd levuvo-nextcloud-mcp
pwd                       # remember this path: this is the project folder
```

All following commands run **in this project folder**.

## 3. Install dependencies

```bash
uv sync --extra dev --frozen
```

- `--frozen` installs exactly the versions from `uv.lock` and does not change the lockfile. If the command fails because the lockfile does not match, the checkout is not clean (check `git status`).
- This creates `.venv/` in the project folder with the start command `.venv/bin/levuvo-nextcloud-mcp`.
- `--extra dev` additionally installs the test tools. For operation only, `uv sync --frozen` is sufficient.

## 4. Create an app password in Nextcloud

1. Log in to `https://storage.levuvo.com` as **`agent.levuvo`** (not with your personal account).
2. Click the profile picture at the top right → **Settings** ("Einstellungen") → **Security** ("Sicherheit") → section **Devices & sessions** ("Geräte & Sitzungen").
3. Enter a name, e.g. `levuvo-mcp MacBook Peter`, and choose **Create new app password** ("Neues App-Passwort erstellen").
4. Copy the displayed password into `.env` immediately (step 5). Nextcloud shows it only once.

An app password has the **full rights** of the account and cannot be restricted to "read only". Create a separate app password per device so that each can be revoked individually (same place, entry → **Revoke** ("Widerrufen")).

## 5. Create `.env`

```bash
cp .env.example .env
chmod 600 .env
open -e .env               # or another editor
```

Set at least these values:

```dotenv
NEXTCLOUD_URL=https://storage.levuvo.com
NEXTCLOUD_USERNAME=agent.levuvo
NEXTCLOUD_APP_PASSWORD=<app password from step 4>
NEXTCLOUD_ALLOWED_PATHS=dir:00_Agent Test
```

Important:

- **The folder name must match exactly.** The Levuvo test folder is called `00_Agent Test` – with a **space**, not `00_Agent_Test`. Case matters. What counts is the name `agent.levuvo` sees in the Nextcloud web interface.
- Write spaces literally, without quotes and without `%20`.
- `.env` is listed in `.gitignore` and must never be committed, copied into chats or shown in screenshots.
- `chmod 600` ensures that only your own macOS account can read the file. Otherwise the server warns at startup.
- Optional limits (see `.env.example`): `NEXTCLOUD_MAX_FILE_BYTES` (default 25000000, max. 100000000) and, since 0.5.3, `NEXTCLOUD_SEARCH_MAX_DEPTH` (default 6, 3–20), `NEXTCLOUD_SEARCH_MAX_DIRECTORIES` (default 100, 1–1000) and `NEXTCLOUD_SEARCH_MAX_RESULTS` (default 100, 25–500). Without them the defaults apply.

## 6. Check

```bash
.venv/bin/levuvo-nextcloud-mcp --version
.venv/bin/levuvo-nextcloud-mcp --check-config
.venv/bin/levuvo-nextcloud-mcp --check-nextcloud
```

| Command | Checks | Does not check |
|---|---|---|
| `--version` | Installed version (expected: `levuvo-nextcloud-mcp 0.5.3`) | – |
| `--check-config` | Offline: required values, syntax of the released entries, contradictions, loaded file (`config_file`). Prints no secrets. | Whether the credentials are correct or the paths exist in Nextcloud |
| `--check-nextcloud` | Online, read-only (`PROPFIND`): login, existence and type of each released entry, Nextcloud permissions on the entry and on the **immediate** child entries of a folder | Deeper subfolders, excluded entries, the behavior in Claude Code, write attempts (never made) |

`--check-nextcloud` prints one JSON object per released entry. The key fields are:

- `assessment`: `read_only`, `read_only_content`, `write_possible`, `unverified` or `error`.
- `verified`: `true` only if no open points remain.
- `open_points`: what the automatic check could not settle.

On stderr you may see:

- **WARNING** for real write, delete or create rights on content (`WARNING: The technical account has write, delete or create permissions in Nextcloud on the contents of: …`). In that case, set the share to read-only.
- **NOTE "not conclusively verified"** when something remains open (`NOTE: Permissions not conclusively verified - manual check required for: …`).
- `Nextcloud check failed: …` and exit code 1 for connection or WebDAV errors.

For the Levuvo test share (root folder `SGDN`, file `test.txt` with `SG`), a NOTE is to be expected, but no WARNING, provided that Nextcloud reports the share as read-only. Meaning and limits: [SECURITY.md](../SECURITY.md#permissions-on-the-mount-point-and-on-content). The manual check: in the web interface as `agent.levuvo`, the files in the test folder must not offer the actions Edit ("Bearbeiten"), Delete ("Löschen"), Rename ("Umbenennen") or Move ("Verschieben"), and the sharing account sees only "Read" ("Lesen") for the share with `agent.levuvo`.

## 7. Register in Claude Code

Run this **in the project folder** (`cd` there first and check with `pwd`):

```bash
cd ~/Projekte/levuvo-nextcloud-mcp
claude mcp add --scope user --transport stdio levuvo-nextcloud \
  --env LEVUVO_MCP_ENV_FILE="$(pwd)/.env" \
  -- "$(pwd)/.venv/bin/levuvo-nextcloud-mcp"
claude mcp list
```

`claude mcp list` should show `levuvo-nextcloud` as connected (`✓ Connected`).

**The `$(pwd)` trap:** the shell replaces `$(pwd)` at execution time with the **current** folder, and Claude Code stores this fixed path. If you run the command in a different folder (e.g. your home folder), you register a path where neither `.venv` nor `.env` exists. The server then does not start or cannot find its configuration. The same happens after moving or renaming the project folder. The fix in both cases:

```bash
claude mcp remove levuvo-nextcloud --scope user
# change to the correct folder, then run the add command above again
```

`--scope user` makes the server available in all projects of your own macOS account. `LEVUVO_MCP_ENV_FILE` is needed because Claude Code does not start the server in the project folder.

## 8. Use in VS Code

1. Open the Claude Code extension in VS Code and use a **Local** session (runs on the Mac). Cloud or web sessions do not run on the Mac and cannot reach the local server.
2. Type `/mcp` in the chat: `levuvo-nextcloud` should appear with four tools (`list_files`, `get_file_info`, `search_files`, `read_file`). Tool reference: [docs/MCP_TOOLS.md](MCP_TOOLS.md).
3. **If a newly registered server does not appear** although `claude mcp list` shows "Connected" in the terminal: **close and reopen** the Claude Code chat window in VS Code. A chat window that is already open does not reload the MCP configuration. This fix was confirmed in the live test on 2026-11-06 (user report).

## 9. Positive and negative test via MCP

The goal is to verify that Claude, **via the MCP tools**, sees exactly the test folder and that everything else is rejected.

**Rule for this test: no shell.** Claude Code must not run any terminal commands (`Bash`, `curl`, `cat .env` …) during the test. Via the shell, Claude could read the `.env` and access Nextcloud directly with the app password. That would not test the MCP server but bypass the allowlist. Decline any shell requests from Claude during the test.

Suggested prompt:

> Use only the tools of the MCP server levuvo-nextcloud, no shell and no other tools.
> 1. Use list_files to list all released entries.
> 2. List the contents of "00_Agent Test".
> 3. Read "00_Agent Test/test.txt" with read_file.
> 4. Use search_files to search for "Agent" and for "test.txt".
> 5. Use list_files to list the folder "02_Finanzen".
> For each step, report the result or the error message verbatim.

Expected results:

| Step | Expected result |
|---|---|
| 1 | Exactly one entry: `00_Agent Test` (folder) |
| 2 | Contents of the test folder, e.g. `test.txt` |
| 3 | Text of `test.txt` |
| 4 | "Agent" finds the folder `00_Agent Test` (since 0.5.1); "test.txt" finds the file |
| 5 | Error "The path is not released for the MCP agent." |

Optional long-document test (since 0.5.2): put a long PDF or text file into `00_Agent Test` and ask: "Read the whole file with read_file and keep calling it with offset=next_offset and the returned etag until has_more is false. Report total_chars, the number of calls and extraction_complete." The sections together should cover the whole file; `extraction_complete: false` explains in `extraction_notes` what could not be read.

Step 5 is the negative test: `02_Finanzen` is not released and is rejected **before** any request is sent to Nextcloud – even if `agent.levuvo` could see the folder in Nextcloud.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `uv sync … --frozen` fails | The lockfile does not match the checkout. Check `git status`/`git pull`; do not edit `uv.lock` by hand. |
| `Configuration error: … is missing` in Claude Code, but fine in the terminal | `LEVUVO_MCP_ENV_FILE` is missing or points to a wrong path (`$(pwd)` trap). Register again, see step 7. |
| `--check-nextcloud`: 404 / "not found" | The folder name does not match exactly (`00_Agent Test` vs. `00_Agent_Test`), or the share is located in a subfolder for `agent.levuvo`. |
| `--check-nextcloud`: 401 | Username or app password wrong or revoked. Create a new app password (step 4). |
| `--check-nextcloud`: WARNING | Real write rights. Change the share with `agent.levuvo` to read-only and check again. |
| `--check-nextcloud`: NOTE | Not everything could be settled automatically. Read `open_points` and check manually (step 6). |
| Server missing in `/mcp` | Use a Local session; close and reopen the chat window (step 8); check `claude mcp list`. |
| Search does not find something | `search_files` only compares file and folder names, not content. `complete: false` means hits may be missing; `incomplete_reasons` names the limit (`depth_limit`, `directory_limit`, `result_limit`). Search a subfolder with `path` or raise the limits. |
| Claude reports an old version or old limits | The MCP process still runs the old code or `.env`. Restart Claude Code / the chat window; the tool descriptions must start with `Levuvo Nextcloud MCP v0.5.3`. |

More cases: [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Updating

```bash
cd ~/Projekte/levuvo-nextcloud-mcp
git pull
uv sync --extra dev --frozen
.venv/bin/levuvo-nextcloud-mcp --version
.venv/bin/levuvo-nextcloud-mcp --check-config
```

Afterwards, close and reopen the Claude Code chat window or restart Claude Code. The registration from step 7 remains valid as long as the project folder is not moved. `git pull` does not change `.env`. New variables, if any, are listed in `CHANGELOG.md` and `.env.example`.

### Updating to 0.5.3

1. Run the commands above; `--version` must print `levuvo-nextcloud-mcp 0.5.3`.
2. Optional: add the new search limits to `.env` (without them the 0.5.2 limits apply). Example for a larger structure:

   ```dotenv
   NEXTCLOUD_MAX_FILE_BYTES=100000000
   NEXTCLOUD_SEARCH_MAX_DEPTH=20
   NEXTCLOUD_SEARCH_MAX_DIRECTORIES=1000
   NEXTCLOUD_SEARCH_MAX_RESULTS=500
   ```

3. Run `--check-config`: it prints `max_file_bytes` and a `search` block with the effective limits.
4. Restart Claude (Claude Code: close and reopen the chat window; Claude Desktop: quit and reopen the app). Changes to `.env` are only picked up by a new MCP process.
5. Ask Claude: "Which version does the connected Levuvo Nextcloud server report, and which file size and search limits are configured?" The answer should be taken from the tool descriptions, e.g. `Levuvo Nextcloud MCP v0.5.3`, `Configured maximum file size: 100000000 bytes.` and `Configured maximum depth: 20.`

## Security in brief

- The MCP server never writes (only `GET`/`PROPFIND`, no write tools). The app password, however, could do more: this is why the shares in Nextcloud must be read-only. Details: [SECURITY.md](../SECURITY.md#two-separate-layers).
- The allowlist only protects the route **via MCP**. Whoever or whatever can read the `.env` on the Mac (including an AI agent with shell access) has the full account rights.
- Start by releasing only the test folder without confidential data. Add further releases selectively with `dir:`/`file:` and, if needed, `NEXTCLOUD_DENIED_PATHS`.
- Revoke the app password in Nextcloud immediately if the Mac is lost or compromise is suspected.

## Local or remote?

| | Local (`stdio`, this guide) | Remote (`--transport http`, optional) |
|---|---|---|
| Runs on | the Mac, started by Claude Code | a server behind a TLS reverse proxy |
| Network port | none | `127.0.0.1:8765` plus a public proxy |
| Clients | Claude Code on this Mac (CLI, VS Code Local) | Claude Code with header, possibly Claude Web / ChatGPT later |
| SSH / Hetzner Cloud | not required | required if operated on a Hetzner server |
| Status | usable day to day; live tests on 2026-11-06 successful according to the user report | not production-ready; checklist in [SECURITY.md](../SECURITY.md#checklist-before-any-public-operation) and [docs/REMOTE.md](REMOTE.md) |

## Appendix: SSH key (only for later server operation)

**Not** required for local operation. Only relevant if the server is later to run on a Linux server of your own (e.g. Hetzner Cloud).

Generate the key (only if none exists yet; do not overwrite an existing one):

```bash
ls -l ~/.ssh/levuvo_hetzner ~/.ssh/levuvo_hetzner.pub   # does it already exist?
ssh-keygen -t ed25519 -f ~/.ssh/levuvo_hetzner -C "levuvo-hetzner"
```

- Set a **passphrase** when prompted. It protects the private key if the file falls into the wrong hands.
- Check that key and passphrase match without printing anything:

  ```bash
  ssh-keygen -y -f ~/.ssh/levuvo_hetzner > /dev/null && echo "key ok"
  ```

- Store the passphrase in the **macOS keychain** so that it is not requested on every connection:

  ```bash
  ssh-add --apple-use-keychain ~/.ssh/levuvo_hetzner
  ```

  and in `~/.ssh/config` for the server host:

  ```
  Host levuvo-hetzner
      HostName <IP address or name of the server>
      User <user>
      IdentityFile ~/.ssh/levuvo_hetzner
      AddKeysToAgent yes
      UseKeychain yes
  ```

**Public or private?**

| File | Kind | Handling |
|---|---|---|
| `~/.ssh/levuvo_hetzner.pub` | public key | May be added to the server or to the Hetzner Cloud Console. |
| `~/.ssh/levuvo_hetzner` | **private** key | Stays on this Mac. Never copy, send, or put it in Git, chats, tickets or cloud folders. Permissions `600` (set by `ssh-keygen` itself). |

Generate a separate key for each additional device instead of copying the private key.
