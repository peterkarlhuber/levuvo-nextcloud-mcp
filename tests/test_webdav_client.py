"""AP3/AP7: WebDAV client behaviour against the in-memory fake Nextcloud."""

from __future__ import annotations

import asyncio
import time
import unicodedata

import httpx
import pytest
from conftest import FakeNextcloud, default_tree

from levuvo_nextcloud_mcp import webdav as webdav_module
from levuvo_nextcloud_mcp.errors import (
    AccessDeniedError,
    InvalidArgumentError,
    LimitExceededError,
    NextcloudError,
    NotFoundError,
)
from levuvo_nextcloud_mcp.webdav import NextcloudWebDAV

pytestmark = pytest.mark.asyncio


def client(settings, fake: FakeNextcloud) -> NextcloudWebDAV:
    return NextcloudWebDAV(settings, transport=fake.transport())


# --------------------------------------------------------------------------- functional regression
async def test_root_listing_reports_types_of_allowed_entries(make_settings, nextcloud) -> None:
    async with client(
        make_settings("dir:05_Projekte/Offen", "file:06_Marketing/CI.md", "07_Ablage/DateiOhneEndung"), nextcloud
    ) as dav:
        listing = await dav.list_files("")
    assert [(i["path"], i["is_dir"]) for i in listing["items"]] == [
        ("05_Projekte/Offen", True),
        ("06_Marketing/CI.md", False),
        ("07_Ablage/DateiOhneEndung", False),
    ]
    assert listing["truncated"] is False


async def test_folder_listing_sorted_and_limited(make_settings, nextcloud) -> None:
    async with client(make_settings("dir:05_Projekte/Offen"), nextcloud) as dav:
        listing = await dav.list_files("05_Projekte/Offen", limit=2)
    assert [i["name"] for i in listing["items"]] == ["Kunde A", "Leerzeichen und #Raute?.txt"]
    assert listing["truncated"] is True


async def test_read_markdown_and_metadata(make_settings, nextcloud) -> None:
    async with client(make_settings("dir:05_Projekte/Offen"), nextcloud) as dav:
        info = await dav.info("05_Projekte/Offen/Plan.md")
        result = await dav.read_file("05_Projekte/Offen/Plan.md")
    assert info.is_dir is False and info.size_bytes == len(nextcloud.files["05_Projekte/Offen/Plan.md"])
    assert info.permissions == "SG"
    assert result["text"].startswith("# Freigegeben") and result["format"] == ".md"
    assert result["encoding"] == "utf-8" and result["truncated"] is False
    assert "DUMMY_TEST_SECRET" not in repr(result)


async def test_special_characters_are_encoded_once(make_settings, nextcloud) -> None:
    name = "05_Projekte/Offen/Leerzeichen und #Raute?.txt"
    async with client(make_settings("dir:05_Projekte/Offen"), nextcloud) as dav:
        assert dav._url(name).endswith("/05_Projekte/Offen/Leerzeichen%20und%20%23Raute%3F.txt")
        assert (await dav.read_file(name))["text"] == "Sonderzeichen ok"
    assert ("GET", name) in nextcloud.requests


async def test_nfd_request_reads_nfc_file(make_settings, nextcloud) -> None:
    async with client(make_settings("dir:05_Projekte/Offen"), nextcloud) as dav:
        result = await dav.read_file(unicodedata.normalize("NFD", "05_Projekte/Offen/Ümlaut Übersicht.md"))
    assert result["path"] == "05_Projekte/Offen/Ümlaut Übersicht.md"
    assert result["text"] == "Umlaute äöü"


# --------------------------------------------------------------------------- security
DENY_PROBES = [
    "05_Projekte/Vertraulich/Kundenvertrag.pdf",
    "05_Projekte/vertraulich/Kundenvertrag.pdf",
    "05_Projekte/VERTRAULICH/Intern/Kosten.xlsx",
    unicodedata.normalize("NFD", "05_Projekte/Geschäftsführung/Gehälter.txt"),
    "05_Projekte/geschäftsführung/Gehälter.txt",
    "08_Privat/Tagebuch.txt",
]


@pytest.mark.parametrize("probe", DENY_PROBES)
async def test_denied_paths_never_reach_nextcloud_even_on_case_insensitive_backend(make_settings, probe: str) -> None:
    fake = default_tree()
    fake.case_insensitive = True
    settings = make_settings("dir:05_Projekte", denied=("dir:05_Projekte/Vertraulich", "05_Projekte/Geschäftsführung"))
    async with client(settings, fake) as dav:
        for call in (dav.info, dav.read_file, dav.list_files):
            with pytest.raises(AccessDeniedError):
                await call(probe)
    assert fake.requests == []


async def test_denied_entries_are_filtered_from_listing_and_search(make_settings, nextcloud) -> None:
    settings = make_settings("dir:05_Projekte", denied=("05_Projekte/Vertraulich", "05_Projekte/Geschäftsführung"))
    async with client(settings, nextcloud) as dav:
        listing = await dav.list_files("05_Projekte")
        found_secret = await dav.search_files("Kosten")
        found_folder = await dav.search_files("vertraulich")
        found_umlaut = await dav.search_files("Gehälter")
        found_plan = await dav.search_files("plan")
    assert [i["name"] for i in listing["items"]] == ["Offen"]
    assert found_secret["results"] == found_folder["results"] == found_umlaut["results"] == []
    assert {r["path"] for r in found_plan["results"]} == {
        "05_Projekte/Offen/Plan.md",
        "05_Projekte/Offen/Kunde A/Projektplan.txt",
    }
    assert not any("Vertraulich" in p or "Geschäftsführung" in p for p in nextcloud.paths_requested())


async def test_untyped_file_entry_cannot_authorise_children(make_settings, nextcloud) -> None:
    async with client(make_settings("07_Ablage/DateiOhneEndung"), nextcloud) as dav:
        with pytest.raises(AccessDeniedError):
            await dav.info("07_Ablage/DateiOhneEndung/kind")
    assert "07_Ablage/DateiOhneEndung/kind" not in nextcloud.paths_requested()


@pytest.mark.parametrize("entry, actual", [("file:05_Projekte", "folder"), ("dir:06_Marketing/CI.md", "file")])
async def test_prefix_type_mismatch_is_reported(make_settings, nextcloud, entry: str, actual: str) -> None:
    async with client(make_settings(entry), nextcloud) as dav:
        with pytest.raises(NextcloudError, match=f"entry type contradicts.*is actually a {actual}"):
            await dav.list_files("")


async def test_deny_prefix_type_mismatch_is_reported(make_settings, nextcloud) -> None:
    async with client(make_settings("dir:05_Projekte", denied=("file:05_Projekte/Vertraulich",)), nextcloud) as dav:
        with pytest.raises(NextcloudError, match="entry type contradicts"):
            await dav.list_files("05_Projekte")


async def test_foreign_and_malicious_hrefs_are_ignored(make_settings) -> None:
    fake = FakeNextcloud(folders={"A"})
    base = "/remote.php/dav/files/agent.levuvo"
    hostile = [
        f"{base}/A/",
        "https://attacker.example/remote.php/dav/files/agent.levuvo/A/evil.txt",
        "/remote.php/dav/files/other.user/A/foreign.txt",
        f"{base}/A/sub%2Fescape.txt",
        f"{base}/A/../B/up.txt",
        f"{base}/A/x.txt?query=1",
        f"{base}/B/outside.txt",
        f"{base}/A/deep/grandchild.txt",
        f"{base}/A/ok.txt",
        f"{base}/A/ok.txt",
    ]
    body = "".join(
        f"<d:response><d:href>{h}</d:href><d:propstat><d:prop><d:resourcetype>{'<d:collection/>' if h.endswith('/') else ''}"
        "</d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        for h in hostile
    )
    fake.raw_override["A"] = f"<d:multistatus xmlns:d='DAV:'>{body}</d:multistatus>".encode()
    async with client(make_settings("dir:A"), fake) as dav:
        listing = await dav._propfind("A", depth=1)
    names = [entry.path for entry in listing]
    # Foreign host/user, traversal, query, outside, grandchildren, duplicates and an encoded
    # slash (which would create a new path level) are all dropped.
    assert names == ["A", "A/ok.txt"]


# --------------------------------------------------------------------------- invalid responses
@pytest.mark.parametrize(
    "payload",
    [
        b"not xml at all",
        b"<?xml version='1.0'?><d:other xmlns:d='DAV:'/>",
        b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'aaaa'><!ENTITY b '&a;&a;&a;'>]><d:multistatus xmlns:d='DAV:'>&b;</d:multistatus>",
        b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><d:multistatus xmlns:d='DAV:'>&e;</d:multistatus>",
        b"<d:multistatus xmlns:d='DAV:'><d:response>",
    ],
)
async def test_invalid_or_hostile_xml_is_rejected(make_settings, payload: bytes) -> None:
    fake = FakeNextcloud(folders={"A"})
    fake.raw_override["A"] = payload
    async with client(make_settings("dir:A"), fake) as dav:
        with pytest.raises(NextcloudError, match="WebDAV"):
            await dav.info("A")


async def test_response_without_requested_path_hints_at_user_id(make_settings) -> None:
    fake = FakeNextcloud(folders={"A"}, href_user="7f3a-uid")
    async with client(make_settings("dir:A"), fake) as dav:
        with pytest.raises(NextcloudError, match="NEXTCLOUD_USER_ID"):
            await dav.info("A")
    fixed = FakeNextcloud(folders={"A"}, user="7f3a-uid")
    async with client(make_settings("dir:A", username="agent@levuvo.com", user_id="7f3a-uid"), fixed) as dav:
        assert (await dav.info("A")).is_dir is True


async def test_oversized_propfind_is_aborted_while_streaming(make_settings, monkeypatch) -> None:
    fake = FakeNextcloud(folders={"A"})
    fake.raw_override["A"] = b"<d:multistatus xmlns:d='DAV:'>" + b" " * 5000 + b"</d:multistatus>"
    monkeypatch.setattr(webdav_module, "MAX_XML_BYTES", 1000)
    async with client(make_settings("dir:A"), fake) as dav:
        with pytest.raises(LimitExceededError, match="too large"):
            await dav.info("A")


async def test_too_many_directory_entries(make_settings, monkeypatch) -> None:
    fake = FakeNextcloud(files={f"A/f{i}.txt": b"x" for i in range(30)})
    monkeypatch.setattr(webdav_module, "MAX_DIRECTORY_ITEMS", 10)
    async with client(make_settings("dir:A"), fake) as dav:
        with pytest.raises(LimitExceededError, match="Too many"):
            await dav.list_files("A")


# --------------------------------------------------------------------------- HTTP errors
@pytest.mark.parametrize(
    "status, headers, error, message",
    [
        (401, {}, NextcloudError, "authentication failed"),
        (403, {}, NextcloudError, "denied access"),
        (404, {}, NotFoundError, "not found"),
        (429, {"Retry-After": "30"}, NextcloudError, "HTTP 429.*30 s"),
        (302, {"Location": "https://attacker.example/"}, NextcloudError, "redirect"),
        (500, {}, NextcloudError, "unavailable"),
        (418, {}, NextcloudError, "HTTP 418"),
    ],
)
async def test_http_status_mapping(make_settings, status, headers, error, message) -> None:
    fake = FakeNextcloud(folders={"A"})
    fake.status_override["A"] = status
    fake.headers_override["A"] = headers
    async with client(make_settings("dir:A"), fake) as dav:
        with pytest.raises(error, match=message) as info:
            await dav.info("A")
    assert "DUMMY_TEST_SECRET" not in str(info.value)
    assert [host for host in (r for r in fake.requests)] == [("PROPFIND", "A")]  # no redirect followed


@pytest.mark.parametrize(
    "exc, message",
    [
        (httpx.ConnectTimeout("t"), "Timeout"),
        (httpx.ReadTimeout("t"), "Timeout"),
        (httpx.ConnectError("x"), "Connection to Nextcloud failed"),
    ],
)
async def test_network_errors_are_mapped(make_settings, exc, message) -> None:
    def raise_error(request: httpx.Request) -> httpx.Response:
        raise exc

    async with NextcloudWebDAV(make_settings("dir:A"), transport=httpx.MockTransport(raise_error)) as dav:
        with pytest.raises(NextcloudError, match=message):
            await dav.info("A")


async def test_real_timeout_is_enforced(make_settings) -> None:
    fake = FakeNextcloud(folders={"A"}, delay=3)
    settings = make_settings("dir:A", timeout_seconds=1)

    async def slow(request: httpx.Request) -> httpx.Response:
        timeout = request.extensions["timeout"]["read"]
        try:
            return await asyncio.wait_for(fake.handle(request), timeout)
        except TimeoutError:
            raise httpx.ReadTimeout("read timeout", request=request) from None

    async with NextcloudWebDAV(settings, transport=httpx.MockTransport(slow)) as dav:
        started = time.perf_counter()
        with pytest.raises(NextcloudError, match="Timeout"):
            await dav.info("A")
    assert time.perf_counter() - started < 2.5


# --------------------------------------------------------------------------- limits
async def test_download_limit_by_metadata_and_by_stream(make_settings) -> None:
    fake = FakeNextcloud(files={"A/big.txt": b"x" * 2000})
    async with client(make_settings("dir:A", max_file_bytes=1000), fake) as dav:
        with pytest.raises(LimitExceededError, match="download limit"):
            await dav.read_file("A/big.txt")
    assert ("GET", "A/big.txt") not in fake.requests  # rejected from PROPFIND size already

    lying = FakeNextcloud(files={"A/big.txt": b"x" * 2000})
    original = lying.multistatus
    lying.multistatus = lambda paths: original(paths).replace(b">2000<", b">10<")  # type: ignore[method-assign]
    async with client(make_settings("dir:A", max_file_bytes=1000), lying) as dav:
        with pytest.raises(LimitExceededError, match="download limit"):
            await dav.read_file("A/big.txt")
    assert ("GET", "A/big.txt") in lying.requests


@pytest.mark.parametrize("bad", [0, 99, 30001, "100"])
async def test_max_chars_bounds(make_settings, nextcloud, bad) -> None:
    async with client(make_settings("dir:05_Projekte/Offen"), nextcloud) as dav:
        with pytest.raises(InvalidArgumentError):
            await dav.read_file("05_Projekte/Offen/Plan.md", max_chars=bad)


async def test_output_limit_truncates(make_settings) -> None:
    fake = FakeNextcloud(files={"A/long.md": b"y" * 500})
    async with client(make_settings("dir:A"), fake) as dav:
        result = await dav.read_file("A/long.md", max_chars=100)
    assert len(result["text"]) == 100 and result["truncated"] is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": ""},
        {"query": "x" * 121},
        {"query": "a", "max_depth": 7},
        {"query": "a", "max_results": 0},
        {"query": "a", "max_results": 101},
    ],
)
async def test_search_argument_bounds(make_settings, nextcloud, kwargs) -> None:
    async with client(make_settings("dir:05_Projekte"), nextcloud) as dav:
        with pytest.raises(InvalidArgumentError):
            await dav.search_files(**kwargs)


@pytest.mark.parametrize("limit", [0, 251])
async def test_list_limit_bounds(make_settings, nextcloud, limit) -> None:
    async with client(make_settings("dir:05_Projekte"), nextcloud) as dav:
        with pytest.raises(InvalidArgumentError):
            await dav.list_files("05_Projekte", limit=limit)


async def test_list_on_file_and_read_on_folder_give_clear_errors(make_settings, nextcloud) -> None:
    async with client(make_settings("dir:05_Projekte/Offen"), nextcloud) as dav:
        with pytest.raises(InvalidArgumentError, match="This is a file"):
            await dav.list_files("05_Projekte/Offen/Plan.md")
        with pytest.raises(InvalidArgumentError, match="This is a folder"):
            await dav.read_file("05_Projekte/Offen/Kunde A")
        with pytest.raises(NotFoundError):
            await dav.read_file("05_Projekte/Offen/gibt-es-nicht.md")


# --------------------------------------------------------------------------- performance / concurrency
def wide_tree(folders: int, files_per_folder: int = 3) -> FakeNextcloud:
    files = {f"R/d{i:03d}/f{j}.txt": b"x" for i in range(folders) for j in range(files_per_folder)}
    files["R/d050/treffer.md"] = b"hit"
    return FakeNextcloud(files=files)


async def test_search_is_parallel_but_bounded(make_settings) -> None:
    fake = wide_tree(60)
    fake.delay = 0.02
    async with client(make_settings("dir:R"), fake) as dav:
        started = time.perf_counter()
        result = await dav.search_files("treffer", max_depth=2)
        elapsed = time.perf_counter() - started
    assert [r["path"] for r in result["results"]] == ["R/d050/treffer.md"]
    assert result["complete"] is True and result["directories_scanned"] == 61
    assert fake.max_concurrent <= webdav_module.SEARCH_CONCURRENCY
    assert fake.max_concurrent > 1
    # Sequential would be >= 61 * 0.02 s = 1.22 s; bounded parallelism (4) needs ~0.35 s.
    assert elapsed < 0.9, elapsed


async def test_search_reports_incomplete_when_directory_budget_is_exhausted(make_settings, monkeypatch) -> None:
    fake = wide_tree(20)
    monkeypatch.setattr(webdav_module, "MAX_SEARCH_DIRECTORIES", 5)
    async with client(make_settings("dir:R"), fake) as dav:
        result = await dav.search_files("treffer", max_depth=3)
    assert result["directories_scanned"] == 5 and result["complete"] is False


async def test_search_respects_depth_and_result_limit(make_settings, nextcloud) -> None:
    async with client(make_settings("dir:05_Projekte/Offen"), nextcloud) as dav:
        shallow = await dav.search_files("Projektplan", max_depth=0)
        deep = await dav.search_files("Projektplan", max_depth=1)
        limited = await dav.search_files("e", max_results=1)
    assert shallow["results"] == []
    assert [r["path"] for r in deep["results"]] == ["05_Projekte/Offen/Kunde A/Projektplan.txt"]
    assert len(limited["results"]) == 1 and limited["complete"] is False


async def test_single_http_client_and_type_cache_reduce_requests(make_settings, nextcloud) -> None:
    created = []
    original = httpx.AsyncClient.__init__

    def tracking_init(self, *args, **kwargs):
        created.append(self)
        original(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = tracking_init  # type: ignore[method-assign]
    try:
        async with client(make_settings("05_Projekte/Offen"), nextcloud) as dav:
            for _ in range(3):
                await dav.read_file("05_Projekte/Offen/Plan.md")
    finally:
        httpx.AsyncClient.__init__ = original  # type: ignore[method-assign]
    assert len(created) == 1
    root_checks = [r for r in nextcloud.requests if r == ("PROPFIND", "05_Projekte/Offen")]
    assert len(root_checks) == 1  # the untyped root is verified once, then cached
    # 0.5.2: the extracted text is cached by ETag, so the file is downloaded once; each call still
    # re-checks the ETag with one PROPFIND.
    assert nextcloud.requests.count(("GET", "05_Projekte/Offen/Plan.md")) == 1
    assert nextcloud.requests.count(("PROPFIND", "05_Projekte/Offen/Plan.md")) == 3


async def test_concurrent_reads_are_consistent(make_settings) -> None:
    fake = FakeNextcloud(files={f"A/f{i}.md": f"Inhalt {i}".encode() for i in range(12)}, delay=0.01)
    async with client(make_settings("dir:A"), fake) as dav:
        results = await asyncio.gather(*(dav.read_file(f"A/f{i}.md") for i in range(12)))
    assert [r["text"] for r in results] == [f"Inhalt {i}" for i in range(12)]


async def test_extraction_does_not_block_event_loop(make_settings, monkeypatch) -> None:
    fake = FakeNextcloud(files={"A/slow.md": b"x"})

    def slow_extract(path, source, **kwargs):
        time.sleep(0.3)
        return webdav_module.Extraction(text="x", format=".md", encoding="utf-8")

    monkeypatch.setattr(webdav_module, "extract_document", slow_extract)
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        for _ in range(10):
            await asyncio.sleep(0.02)
            ticks += 1

    async with client(make_settings("dir:A"), fake) as dav:
        await asyncio.gather(dav.read_file("A/slow.md"), ticker())
    assert ticks == 10


async def test_check_access_reports_write_permissions(make_settings, nextcloud) -> None:
    nextcloud.permissions = "RGDNVCK"
    async with client(make_settings("dir:05_Projekte/Offen"), nextcloud) as dav:
        report = await dav.check_access()
    # 0.5.0 keys keep their values; 0.5.1 only adds fields (see test_v051_check_access.py).
    [entry] = report
    assert {key: entry[key] for key in ("entry", "is_dir", "permissions", "writable_in_nextcloud")} == {
        "entry": "dir:05_Projekte/Offen",
        "is_dir": True,
        "permissions": "RGDNVCK",
        "writable_in_nextcloud": True,
    }
    assert entry["assessment"] == "write_possible" and entry["content_writable"] is True


async def test_only_get_and_propfind_are_possible(make_settings, nextcloud) -> None:
    async with client(make_settings("dir:05_Projekte"), nextcloud) as dav:
        for method in ("PUT", "DELETE", "MOVE", "COPY", "MKCOL", "PROPPATCH", "POST", "LOCK"):
            with pytest.raises(RuntimeError, match="not allowed"):
                async with dav._request(method, dav._url("05_Projekte/x")):
                    pass
    assert nextcloud.requests == []
