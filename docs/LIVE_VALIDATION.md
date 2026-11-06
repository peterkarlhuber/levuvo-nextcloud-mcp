# Live validation

This document records tests against the **real** Nextcloud instance with a **real** MCP client. It is kept separate from the automated test suite (pytest and GitHub Actions, offline against simulated WebDAV responses; see [README](../README.md#tests-and-quality)).

**Provenance:** All live results below were run and reported by the user from the client named in each section. The maintainers documented them; they did not run these tests themselves and have not independently checked the raw protocols. Statements marked as *code finding* were checked by the maintainers against the source code and the automated tests.

Earlier user-reported live tests (0.5.0 and 0.5.1, Claude Code in VS Code) are summarised in the [README status](../README.md#overview-and-status) and in the [CHANGELOG entry for 0.5.1](../CHANGELOG.md#051--2026-11-06).

## 0.5.3 - local regression test with Claude Desktop (2026-11-06)

### Result

**16 of 16 planned checks passed, 0 failed, 0 open**, in three consecutive test runs with 24 MCP tool calls in total.

Assessment: Levuvo Nextcloud MCP 0.5.3 is functionally validated for **local read access with Claude Desktop** on the tested data. This is not a release for publicly reachable remote operation (see [Not covered](#not-covered-by-these-live-tests)).

### Environment

| Item | Value |
|---|---|
| Date | 2026-11-06 |
| Version under test | 0.5.3 (merged via [PR #4](https://github.com/peterkarlhuber/levuvo-nextcloud-mcp/pull/4)) |
| MCP client | Claude Desktop on macOS |
| Transport | local `stdio` server |
| Nextcloud | `https://storage.levuvo.com` (Hetzner Storage Share), technical read-only account |
| Method | real MCP tool calls; only the four tools `list_files`, `get_file_info`, `search_files`, `read_file` |
| Test data | prepared manually in the Nextcloud web interface before each run; the MCP server created, changed, renamed or deleted nothing |
| Shares | allowed: `00_Agent Test`; for run 3 additionally denied: `dir:00_Agent Test/Regression/Sperrtest` |

Active limits as reported by Claude Desktop from the tool descriptions:

| Setting | Active value | Default |
|---|---:|---:|
| `NEXTCLOUD_MAX_FILE_BYTES` | 100000000 | 25000000 |
| `NEXTCLOUD_SEARCH_MAX_DEPTH` | 20 | 6 |
| `NEXTCLOUD_SEARCH_MAX_DIRECTORIES` | 1000 | 100 |
| `NEXTCLOUD_SEARCH_MAX_RESULTS` | 500 | 100 |

The 100 MB download limit was confirmed as configuration only; no file of that size was downloaded in these tests.

### Test runs

| Run | Focus | MCP calls | Outcome |
|---|---|---:|---|
| 1 | general regression | 13 | 12 checks PASS, 4 NOT TESTED for lack of test data (6a, 8b, 9, 10c) |
| 2 | RTF and sectioned reading | 4 | 8b and 9 PASS |
| 3 | search depth and denylist | 7 | 6a and 10c PASS |
| **Total** | | **24** | **16 PASS, 0 FAIL, 0 open** |

Calls per tool: `list_files` 3, `get_file_info` 5, `search_files` 10, `read_file` 6. Expected access denials and parameter errors are positive results of the respective checks, not failures.

Note on the call count: the calls described individually below add up to 23 (run 1: 12). The reported totals of 13 calls in run 1 and 10 `search_files` calls include one further `search_files` call in run 1 that is not described individually in the user's report. The totals are documented as reported.

### Checks

| # | Check | Run | Calls (as reported) | Observed result | Status |
|---|---|---|---|---|---|
| 1 | Version and active configuration | 1 | tool discovery | All four tool descriptions start with `Levuvo Nextcloud MCP v0.5.3`; configured and default file size and the configured search limits are shown and distinguished | PASS |
| 2 | Tool discovery | 1 | tool discovery | Exactly `list_files`, `get_file_info`, `search_files`, `read_file`; no writing tool; descriptions match the read-only model. This confirms the offered interface, not every internal safeguard | PASS |
| 3 | Released root entries | 1 | `list_files()`, `list_files("00_Agent Test")` | Only `00_Agent Test`, `truncated=false`, expected metadata fields; the folder lists only `test.txt` (64 bytes) | PASS |
| 4 | Name search over all shares | 1 | `search_files(query="agent")` | `00_Agent Test` itself is a hit (the 0.5.1 fix), no duplicates, `directories_scanned=1`, `complete=true`, `incomplete_reasons=[]` | PASS |
| 5 | Search in a folder | 1 | `search_files(query="test", path="00_Agent Test")`, `search_files(query="zzz_kein_treffer_xyz", path="00_Agent Test")` | Hit `00_Agent Test/test.txt`; the start folder is not a hit; nothing outside the folder; no-hit search returns `results=[]`, `complete=true` | PASS |
| 6a | Depth limit | 3 | see run 3 (A1-A3) | `depth_limit` reported at `max_depth=0`, file found at `max_depth=2` | PASS |
| 6b | Result limit | 1 | `search_files(query="t", max_depth=0, max_results=1)` | One hit, `complete=false`, `incomplete_reasons=["result_limit"]` (more matching entries existed) | PASS |
| 6c | Completeness flag | 1 | the searches above | Complete searches: `complete=true`, `incomplete_reasons=[]`; limited searches: `complete=false` | PASS |
| 6d | Parameter cap | 1 | `search_files(..., max_depth=21)` | Rejected by the MCP schema validation: `Input should be less than or equal to 20`. The server-side check behind the schema was not exercised live (it is covered by automated tests) | PASS |
| 7 | File metadata | 1 | `get_file_info("00_Agent Test/test.txt")` | Name, path, `text/plain`, 64 bytes, modification date, ETag, permissions `SG`; the share mount shows `SGDN`, which was not interpreted as write access to file contents | PASS |
| 8a | Read a text file | 1 | `read_file("00_Agent Test/test.txt", max_chars=1000)` | `format=".txt"`, `encoding="utf-8"`, `returned_chars=64`, `total_chars=64`, `has_more=false`, `next_offset=null`, `extraction_complete=true`, `truncated=false` | PASS |
| 8b | Read an RTF file | 2 | see run 2 | Text, umlauts and special characters extracted, no RTF control words | PASS |
| 9 | Sectioned reading | 2 | see run 2 | Four sections, gap-free, ETag passed on | PASS |
| 10a | Path not released | 1 | `get_file_info("__levuvo_regression_forbidden__/probe.txt")` and one more path outside the share | `The path is not released for the MCP agent.`, no metadata | PASS |
| 10b | Path traversal | 1 | `get_file_info("00_Agent Test/../00_Agent Test/test.txt")` | `Empty path segments as well as '.' and '..' are not allowed.` | PASS |
| 10c | Denylist | 3 | see run 3 (B1-B4) | The denied folder and its file are not exposed by listing, metadata or search | PASS |

### Run 2: RTF and sectioned reading

Test file `00_Agent Test/Regression/long.rtf`: 4046 bytes, 3431 extracted characters, several sections with headings, German umlauts, special characters, RTF formatting and the unique end marker `ENDE-DES-LEVUVO-RTF-REGRESSIONSTESTS-053`. Only `read_file` with `max_chars=1000` was used; calls 2-4 passed the `etag` of the previous response.

| Call | `offset` | `returned_chars` | `next_offset` | `has_more` | `extraction_complete` |
|---:|---:|---:|---:|---|---|
| 1 | 0 | 1000 | 1000 | true | true |
| 2 | 1000 | 1000 | 2000 | true | true |
| 3 | 2000 | 1000 | 3000 | true | true |
| 4 | 3000 | 431 | null | false | true |

Observed: `total_chars=3431` in every response; the sum of `returned_chars` equals `total_chars`; no ETag conflict; no gaps or overlaps at the checked boundaries; `ä ö ü Ä Ö Ü ß € é è „ “ – →` rendered correctly; paragraphs and the headings of sections 1-5 preserved; no visible RTF control sequences; the end marker appears only in the last section. What was checked is the extracted text, not a byte-exact reconstruction of the RTF source.

The last call returned `truncated=true` together with `has_more=false` and `extraction_complete=true`. This is the documented behaviour since 0.5.2 (`truncated` is true whenever a response does not start at offset 0, see [MCP_TOOLS.md](MCP_TOOLS.md)); the end of a document is detected with `has_more` and `extraction_complete`. Not a defect.

### Run 3: search depth and denylist

Test structure (prepared in the Nextcloud web interface):

```text
00_Agent Test/
└── Regression/
    ├── long.rtf
    ├── Ebene1/
    │   └── Ebene2/
    │       └── marker.txt
    └── Sperrtest/          (NEXTCLOUD_DENIED_PATHS=dir:00_Agent Test/Regression/Sperrtest)
        └── secret.txt
```

| # | Call | Observed result | Status |
|---|---|---|---|
| A1 | `search_files(query="marker", path="00_Agent Test/Regression", max_depth=0)` | `results=[]`, `directories_scanned=1`, `complete=false`, `incomplete_reasons=["depth_limit"]` | PASS |
| A2 | `search_files(query="marker", path="00_Agent Test/Regression", max_depth=2)` | Hit `00_Agent Test/Regression/Ebene1/Ebene2/marker.txt`, `directories_scanned=3` (Regression, Ebene1, Ebene2), `complete=true`, `incomplete_reasons=[]` | PASS |
| A3 | `read_file("00_Agent Test/Regression/Ebene1/Ebene2/marker.txt", max_chars=1000)` | 72 bytes, `total_chars=72`, `has_more=false`, `extraction_complete=true`, `encoding="utf-8"`, first line `LEVUVO-DEPTH-TEST-053` | PASS |
| B1 | `list_files("00_Agent Test/Regression")` | Only `Ebene1` and `long.rtf`; `Sperrtest` not shown; `truncated=false` | PASS |
| B2 | `get_file_info("00_Agent Test/Regression/Sperrtest/secret.txt")` | `The path is not released for the MCP agent.`, no metadata | PASS |
| B3 | `search_files(query="secret", path="00_Agent Test/Regression/Sperrtest")` | `The path is not released for the MCP agent.` | PASS |
| B4 | `search_files(query="secret", path="00_Agent Test/Regression")` | `results=[]`, `complete=true`, `directories_scanned=3`; the denied folder was neither searched nor counted | PASS |

The MCP calls alone cannot prove that `Sperrtest/secret.txt` exists in Nextcloud. For a formally complete denylist proof, its existence should be confirmed outside the MCP server (Nextcloud web interface); the user prepared the structure there, but a separate confirmation is not part of the report.

*Code finding:* a denied or unreleased path is rejected by the access policy before any request is sent to Nextcloud (covered by automated tests, e.g. `tests/test_v053_search_and_version.py`). This matches the live observation that B2 and B3 return no metadata.

### Automated quality assurance (separate from the live tests)

For 0.5.3 ([PR #4](https://github.com/peterkarlhuber/levuvo-nextcloud-mcp/pull/4)): 556 automated tests passed (49 new compared with 0.5.2), 92 % line/branch coverage, `ruff check`, `ruff format --check` and `uv lock --check` without findings, all six GitHub Actions jobs green (Python 3.11-3.13 on Ubuntu, 3.12 on macOS, lint, hash-verified pip lockfile install). These results come from the maintainers' run and CI, not from the live tests.

### Observations and findings

**1. Temporary "File or folder not found." without a path.** Around 17:37 on 2026-11-06, `list_files()` and `search_files()` without `path` returned `File or folder not found.`; around 17:39 the same calls worked again. The cause was not determined; a configured share may have been temporarily unreachable or renamed while the test structure was being prepared. This was not reproduced under controlled conditions.

*Code finding (independent of that cause):* without a path, `list_files` and `search_files` request the metadata of every configured share one after another and do not catch errors per share. If one configured share is missing (Nextcloud answers 404), the **whole** call fails with `File or folder not found.`, even if other shares exist. Reproduced by the maintainers with the simulated WebDAV server and two configured shares, one of them missing. Failing loudly avoids silently incomplete results, but it does not say which share is missing. Recommendation for a later version: name the missing share in the error, or return the reachable shares together with an explicit per-share error and `complete=false`; do not suppress the error silently. `--check-nextcloud` already reports each share separately and is the right tool to diagnose this today.

**2. Validation errors show internal details.** A call outside the schema limits (here `max_depth=21`) is rejected by the MCP SDK's argument validation before the server code runs. The returned message contains the Pydantic error text, the rejected input value, the Pydantic minor version (`2.14`) and a link to `errors.pydantic.dev`. *Code finding:* reproduced by the maintainers; the message comes from the SDK, not from this project's error handling. Low severity: no paths, credentials or Nextcloud data are disclosed, only the library version. Recommendation: map schema validation errors to a short English message such as `max_depth must be between 0 and 20.` in a later version.

**3. `truncated` in the last section.** See run 2: documented behaviour, not a regression. Any future change to the meaning of `truncated` must stay backward compatible.

### Not covered by these live tests

- Real downloads of files near the 100 MB limit through Claude Desktop (the limit was confirmed as configuration only).
- Searches that actually scan 1000 folders.
- Load tests and several concurrent users.
- Remote operation (Streamable HTTP) on a server, HTTP authentication (`static`, `oauth`) and public TLS endpoints.
- Penetration tests or an independent security audit.
- All possible Nextcloud permission combinations.
- Behaviour with a permanently missing configured share under controlled conditions (see finding 1).
- Formats other than TXT and RTF (PDF, DOCX, XLSX, HTML are covered by automated tests only).

**Remote production release: pending.** Before any publicly reachable operation, work through the checklist in [SECURITY.md](../SECURITY.md#checklist-before-any-public-operation).
