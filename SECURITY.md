# Security – Levuvo Nextcloud MCP 0.5.2

This document describes what the server protects against, what it does not protect against, and what needs to be done on the Nextcloud side and in operation.

Please do not report security problems publicly as an issue; report them directly to the people responsible for the project at Levuvo.

## Threat model and limits

**Assets to protect:** files in the Storage Share, the app password of the technical account, the remote token or OAuth configuration.

**Assumed attackers and risks:**

1. A language model that, through document content (prompt injection) or misuse, tries to read paths outside the released entries.
2. Errors or typos in the configuration that release more than intended.
3. Unauthorized parties on the internet, if a remote endpoint is public.
4. Manipulated or very large responses or documents (XML attacks, zip bombs, huge folders).

**Not covered:**

- A compromised Mac or server on which the service runs. Anyone who can read the `.env` there has the app password and therefore **all** rights of the technical account in Nextcloud – independently of this server.
- What the AI provider does with the content it reads.
- Per-end-user rights: all clients use the same technical Nextcloud identity.

## Two separate layers

| Layer | Enforced by | What |
|---|---|---|
| **MCP server** | this code | Allow/deny list, only `GET`/`PROPFIND`, no write tools, size and quantity limits, remote authentication |
| **Nextcloud** | Storage Share | Which files the account can see at all (shares, group folders, its own home folder) and what it may do there |

A path is only readable if **both** layers allow it.

**Important:** A Nextcloud app password has the full rights of the account; it cannot be restricted to "read only". In addition, the technical account normally has its own writable home folder. That nothing is written is therefore guaranteed by the MCP code alone. This is why the account must be allowed as little as possible on the Nextcloud side.

**The MCP-side write ban and the account's rights are two different things:**

- *Write ban in the MCP server:* the code only sends `GET` and `PROPFIND` and offers no write tools. This applies to everything an AI client does **via MCP**, regardless of the Nextcloud rights.
- *Rights of the Nextcloud account:* what `agent.levuvo` **could** do in Nextcloud with its app password (e.g. via the web interface, WebDAV programs or `curl`). These rights can go beyond "read only", and the MCP server cannot restrict them.
- Remaining account rights are not a flaw of the MCP server. They become relevant, however, as soon as someone or something uses the app password outside the MCP server – for example an AI agent with shell access on the same Mac that reads the `.env`. Therefore: keep shares read-only and run security tests of the MCP server without giving the agent shell access.

## Nextcloud side: minimal permissions

1. **Create a dedicated account** `agent.levuvo` – without admin and without group admin rights, and not in groups with writable group folders.
2. **Receive read-only shares only:** folders are shared with `agent.levuvo` by another account, with *Edit* ("Bearbeiten"), *Create* ("Erstellen"), *Delete* ("Löschen") and *Share* ("Weiterteilen") deselected.
3. **Never release the account's own home area:** only enter received shares in `NEXTCLOUD_ALLOWED_PATHS`, no folders owned by `agent.levuvo` itself (the account would have full rights there).
4. **Check:** run `levuvo-nextcloud-mcp --check-nextcloud` (`PROPFIND` only, never write attempts). For each released entry it shows the Nextcloud permission letters (`W` write, `C`/`K` create file/folder, `D` delete, `N` rename, `V` move, `R` reshare, `S` shared, `M` mounted, `G` readable) and assesses them as described in the next section. Real write rights produce a **WARNING**, open questions a **NOTE** "not conclusively verified - manual check required". An `R` is not counted as a write right, but should also be absent. Repeat the check after every change to the shares.
5. **App password:** create it for this service only, store it only in `.env` (`chmod 600`), never in Git, chats, screenshots or tickets. If compromise is suspected, revoke it immediately in Nextcloud under *Settings → Security → Devices & sessions* ("Einstellungen → Sicherheit → Geräte & Sitzungen") and create a new one; otherwise rotate it regularly.
6. **Brute-force protection:** Nextcloud slows down requests after failed logins. Wrong credentials in a loop (e.g. through restarts) can slow down the account or the IP address; with repeated 401/429 responses, fix the configuration first.

### Permissions on the mount point and on content

A share received by `agent.levuvo` appears for that account as a **mount point**. Nextcloud often reports more letters on the mount point than on the files inside it. In the live test of 2026-11-06 (user report), the root folder `00_Agent Test` reported `SGDN` and the file `test.txt` inside it `SG`; the web interface offered neither edit nor delete for the file.

Documented semantics according to the [Nextcloud WebDAV documentation](https://docs.nextcloud.com/server/stable/developer_manual/client_apis/WebDAV/basic.html):

| Property | According to the documentation | Use in `--check-nextcloud` |
|---|---|---|
| `oc:permissions` | Permission letters of the entry (`S R M G D N V W C K`) | Raw value, as in 0.5.0 |
| `nc:is-mount-root` | Marks a mount point, e.g. a shared folder: "then the node can only be unshared and not deleted" | `D` on the mount point counts as unsharing on the recipient's side, not as deleting the original data |
| `ocs:share-permissions` | "The permissions that the user has over the share": 1 read, 2 update, 4 create, 8 delete, 16 share | Main evidence for the rights on the content |
| `nc:mount-type` | `''` own storage, `shared`, `group`, `external` … | Distinguishes the account's own folders from received shares |

**Not documented:** the documentation does not describe what `N` (rename) and `V` (move) do on a mount point. Presumably they only affect the recipient's own mount point. This is not proven, however, and is therefore always reported as an open point.

Assessment per released entry (field `assessment`):

| Value | Meaning |
|---|---|
| `write_possible` | Demonstrable write, delete or create rights: `W`/`C`/`K` on the entry, `D`/`N`/`V` on an entry that is **not** a mount point, write bits in `ocs:share-permissions` (2, 4, 8), or corresponding rights on an immediate child entry. Produces a **WARNING**. |
| `read_only_content` | According to the share permissions the content is read-only; the mount point, however, carries `D`/`N`/`V`. |
| `read_only` | No write letters, content read-only. |
| `unverified` | Nextcloud does not return the required properties (e.g. an older version or a proxy). No statement possible. |
| `error` | The entry could not be read; exit code 1. |

`verified` is only `true` if no open points remain (`open_points`). For the Levuvo case `SGDN`/`SG` with share permission "read", the result is therefore `read_only_content` with `verified: false`: the `D` on the mount root is explained by the documented Nextcloud semantics (`nc:is-mount-root`: "can only be unshared and not deleted"), whereas `N` and `V` on a mount root are undocumented. This assessment therefore remains **open as a precaution** ("not conclusively verified") until it is confirmed manually – in the web interface as `agent.levuvo` (no edit, delete, rename or move actions on the files) and on the sharing account's side (the share with `agent.levuvo` has "Read" ("Lesen") only).

Limits of the check:

- Only the released entry and its **immediate** child entries are checked (one `PROPFIND` request with depth 1). Deeper subfolders are not; if a folder contains subfolders, this is listed in `open_points`.
- Folders with more than 2000 entries are not checked for their content (`children_truncated`).
- Excluded entries (`NEXTCLOUD_DENIED_PATHS`) are neither queried nor assessed.
- There are no test write attempts. The check only reads what Nextcloud reports about the rights.

Output fields: the fields from 0.5.0 (`entry`, `is_dir`, `permissions`, `writable_in_nextcloud` = raw finding from the letters on the entry) remain unchanged. New are `assessment`, `content_writable` (`true`/`false`/`null` = unclear), `verified`, `mount_type`, `mount_root`, `share_permissions` (each `null` if not returned), `children_checked`, `children_truncated`, `children_with_write_permissions` (at most 10 paths), `notes` and `open_points`.

### About the storage quota

A quota of 0 B is **not** a security measure and is not recommended here:

- The quota limits the space used in the account's **own** storage.
- Files in received shares count against the **owner's** quota. A quota on the technical account therefore does not prevent writing into writable shares.
- A quota of 0 B prevents uploading file content into the account's own home area, but it is not access control: folders or empty files and writable shares remain possible; the behavior may differ between Nextcloud versions.

A small quota is at most an optional damage limitation. What matters are read-only shares plus the MCP allowlist. If needed, check the actual behavior on the Storage Share itself.

## What the MCP server enforces

- **Read only:** the HTTP client only permits `GET` and `PROPFIND`; other methods are already rejected in the code. There are no tools for writing, deleting, moving or sharing.
- **Path check before every request:** every path is normalized (NFC) and checked against the policy before a Nextcloud request is created. Rejected are absolute paths, backslashes, `.`/`..`, control and format characters (e.g. bidi overrides, zero-width characters), URL-encoded sequences and overlong paths (1024 characters, 255 per segment).
- **Allow exact, deny cautious:** released entries only apply to exactly matching paths (after NFC, case matters). Exclusions also apply to other spellings (NFKC, case, trailing dots/spaces in a segment), always for the whole subtree and always with precedence. Excluded and unreleased paths return the same message.
- **Contradictions prevent startup:** empty list of released entries, duplicates, ineffective exclusions, completely blocked released entries, entries below `file:` entries, unknown prefixes.
- **Type check:** `dir:`/`file:` are checked against the real Nextcloud type; paths below a released entry without prefix are only reachable if that entry really is a folder.
- **Responses from Nextcloud:** no redirects (credentials never go to another destination), TLS verification enabled, proxy/`.netrc` settings of the environment are ignored. XML is parsed with `defusedxml` and DTDs forbidden. `href` entries of foreign hosts or outside the user path are discarded; each segment is decoded exactly once.
- **Limits against overload:** directory response max. 2 MB and 2000 entries, download max. `NEXTCLOUD_MAX_FILE_BYTES` (default 25 MB, configurable up to 100 MB, streamed into a temporary file that is kept in memory up to 4 MB, otherwise an anonymous file that is deleted after extraction, also on errors), search max. 100 folders and 4 parallel requests, text output max. 30000 characters, document extraction in max. 2 parallel worker threads (only one of them for files above 16 MB), at most 25,000,000 extracted characters and 90 seconds per file, PDF max. 5000 pages, XLSX max. 200 sheets and 200 columns, RTF max. 256 nested groups, zip bomb check for Office files (max. 5000 entries, 600 MB uncompressed in total, 300 MB per entry, compression ratio, 60 MB for the main XML part). Extracted text is cached for at most 10 minutes in a bounded in-memory cache (96 MB, 8 entries) keyed by path and ETag; the cache only serves paths that pass the access check again on every call. Remote additionally: request body 128 KiB, 32 concurrent connections.
- **No execution:** no macros, no formula evaluation, no OCR, no shell. RTF files are read by a built-in, linear-time tokenizer that skips embedded objects, pictures, binary data and field instructions instead of interpreting them.

## Prompt injection

Document content is not trustworthy. A document can contain instructions that the model follows ("also read folder X", "send the content to …"). The server only delivers data and marks it as untrusted in every `read_file` response; the allowlist limits what is reachable. It cannot, however, prevent the model from using what it has read in other ways.

Therefore do **not** combine this server in the same agent with tools that write, send network requests, send emails or execute code – or allow such tools only with confirmation for each call.

## Data outflow

What `read_file`, `list_files` etc. return goes to the AI provider (Anthropic, OpenAI) and is processed there. Before releasing customer, personnel or financial data, check data protection (GDPR), contracts and the policies of the respective plan/workspace.

## Logging

- The project's own code does not log passwords, tokens, authorization headers or document content. Error messages to the client contain no credentials.
- Logs go to stderr, level `WARNING`. On unexpected crashes the MCP SDK writes a traceback to stderr; the client only sees a generic message.
- In HTTP mode, Uvicorn's access log is disabled. The reverse proxy must not log authorization headers or bodies.

## Remote authentication

| Mode | Suitable for | Properties and limits |
|---|---|---|
| `stdio` | local Claude Code | No network port. Security = security of the local user account. |
| `static` | a small, trusted group (e.g. Claude Code with `--header`) | One shared, long-lived token for all routes. Constant-time comparison, scheme `Bearer` case-insensitive, exactly one authorization header. No expiry, no users, no logout. |
| `oauth` | later connection of Claude Web / ChatGPT | Resource server only, no login of its own. External identity provider required. Accepts only RS256-signed JWT access tokens with `iss`, `aud`, `sub`, `exp` and scope (`scope` or `scp`); `typ` must be absent, `JWT` or `at+jwt`; ID tokens and tokens over 8 KB are rejected. JWKS is cached for 5 minutes; an unknown `kid` triggers at most one refresh per 60 s. The SDK serves Protected Resource Metadata at `/.well-known/oauth-protected-resource/mcp`. If `MCP_OAUTH_AUDIENCE` equals `MCP_PUBLIC_URL`, the SDK additionally checks the resource binding. Not tested with real identity providers and clients. |

The remote token is a separate secret and must never be the Nextcloud app password.

## Checklist before any public operation

A public endpoint is only justifiable after this list **and** successful tests with the real client.

- [ ] Technical account without admin/group admin rights, only read-only shares, `--check-nextcloud` without WARNING; every NOTE clarified manually
- [ ] Released entries minimal; no confidential areas without an explicit decision
- [ ] `.env` with `chmod 600` (or readable only by the service user), not in Git
- [ ] Remote token random (e.g. `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`) or OAuth with a trustworthy identity provider
- [ ] Port 8765 only on `127.0.0.1`; not reachable from outside (verified)
- [ ] TLS valid; proxy passes `Host` and `Authorization` through unchanged
- [ ] A request without a token or with a wrong token results in `401`
- [ ] A foreign `Host` header is rejected
- [ ] Excluded paths appear neither in listings nor in searches and cannot be read
- [ ] Logs (service and proxy) contain no token, password or document content
- [ ] Service runs as its own user without root (see `deploy/`)
- [ ] Approval by the management for processing by the AI provider
- [ ] Connector not unintentionally visible to other workspace members
- [ ] Procedure for rotating and revoking the app password and token defined

## Residual risks

- **Shared identity:** all remote users access via the same technical account. OAuth authenticates the MCP client but changes nothing about per-person Nextcloud rights. There is no per-user audit.
- **New files:** a folder release also applies to files created later. An exclusion is not a classification.
- **Over-blocking:** the cautious exclusion comparison can also block paths that are only spelled similarly (e.g. `Intern` also blocks `intern` and `Intern.`). This is intended.
- **Names of excluded entries:** Nextcloud includes them in the listing of the parent folder. The server filters them out and does not pass them to the model, but they are briefly held in memory.
- **App password with full rights:** if the `.env` falls into the wrong hands, none of the MCP protections help. Only the Nextcloud side (read-only shares) then limits the damage.
- **Dependencies:** the parsers for PDF/DOCX/XLSX and the MCP SDK are third-party code (the RTF reader is part of this project). Pin versions via the lockfiles and update them regularly.
