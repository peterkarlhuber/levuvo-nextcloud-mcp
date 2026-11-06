"""Version 0.4: individual files, folder/file mixtures and deny-wins rules."""
from __future__ import annotations

from dataclasses import replace
from urllib.parse import unquote
from xml.sax.saxutils import escape

import httpx
import pytest

from levuvo_nextcloud_mcp.settings import ConfigurationError, Settings, parse_allowed_path, validate_path
from levuvo_nextcloud_mcp.webdav import NextcloudWebDAV, WebDAVError

BASE = "/remote.php/dav/files/agent.levuvo"

FOLDERS = {
    "05_Projekte", "05_Projekte/Offen", "05_Projekte/Vertraulich",
    "05_Projekte/Vertraulich/Intern", "06_Marketing", "07_Ablage",
}
FILES = {
    "05_Projekte/Offen/Plan.md": b"# Freigegeben\nHier ist ein Plan.",
    "05_Projekte/Vertraulich/Kundenvertrag.pdf": b"SENSITIVE",
    "05_Projekte/Vertraulich/Intern/Kosten.xlsx": b"PRIVATE",
    "06_Marketing/CI.pdf": b"PDF BYTES",
    "07_Ablage/DateiOhneEndung": b"Geheime Info",
}


def cfg(*allowed: str, denied: tuple[str, ...] = ()) -> Settings:
    return Settings(
        base_url="https://storage.levuvo.com", username="agent.levuvo",
        app_password="DUMMY_TEST_SECRET", allowed_paths=allowed, denied_paths=denied,
    )


def xml_response(nodes: list[str]) -> bytes:
    parts = []
    for path in nodes:
        is_dir = path in FOLDERS
        href = f"{BASE}/{path}{'/' if is_dir else ''}"
        resource = "<d:collection/>" if is_dir else ""
        size = len(FILES.get(path, b""))
        parts.append(f"""
        <d:response><d:href>{escape(href)}</d:href><d:propstat>
          <d:prop><d:resourcetype>{resource}</d:resourcetype>
          <d:getcontentlength>{size}</d:getcontentlength>
          <d:getcontenttype>text/plain</d:getcontenttype>
          </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>""")
    return ("<d:multistatus xmlns:d='DAV:'>" + "".join(parts) + "</d:multistatus>").encode()


def make_handler(log: list[tuple[str, str]]):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method in {"GET", "PROPFIND"}
        assert request.url.host == "storage.levuvo.com"
        relative = unquote(str(request.url.path)).removeprefix(BASE + "/").rstrip("/")
        log.append((request.method, relative))
        if request.method == "GET":
            if relative in FILES:
                return httpx.Response(200, content=FILES[relative])
            return httpx.Response(404)
        if relative not in FOLDERS and relative not in FILES:
            return httpx.Response(404)
        nodes = [relative]
        if request.headers["Depth"] == "1" and relative in FOLDERS:
            nodes += [p for p in FOLDERS | FILES.keys() if p.rsplit("/", 1)[0] == relative]
        return httpx.Response(207, content=xml_response(nodes))
    return handler


def test_policy_multiple_allowed_paths_and_denied_subtree() -> None:
    s = cfg("05_Projekte", "06_Marketing/CI.pdf", denied=("05_Projekte/Vertraulich",))
    assert s.require_allowed("05_Projekte/Offen/Plan.md") == "05_Projekte/Offen/Plan.md"
    assert s.require_allowed("06_Marketing/CI.pdf") == "06_Marketing/CI.pdf"
    for path in (
        "05_Projekte/Vertraulich", "05_Projekte/Vertraulich/Kundenvertrag.pdf",
        "05_Projekte/Vertraulich/Intern/Kosten.xlsx", "06_Marketing", "06_Marketing2/CI.pdf",
    ):
        with pytest.raises(PermissionError):
            s.require_allowed(path)


def test_explicit_file_path_is_exact_match() -> None:
    s = cfg("file:06_Marketing/CI.pdf")
    assert s.require_allowed("06_Marketing/CI.pdf") == "06_Marketing/CI.pdf"
    with pytest.raises(PermissionError):
        s.require_allowed("06_Marketing/CI.pdf/child")
    assert parse_allowed_path("dir:05_Projekte").kind == "dir"
    assert parse_allowed_path("07_Ablage/DateiOhneEndung").kind == "auto"


def test_denial_always_wins_even_if_explicit_allow_file() -> None:
    s = cfg("05_Projekte", "file:05_Projekte/Vertraulich/Kundenvertrag.pdf", denied=("05_Projekte/Vertraulich",))
    with pytest.raises(PermissionError):
        s.require_allowed("05_Projekte/Vertraulich/Kundenvertrag.pdf")


def test_reject_duplicate_and_unset_allowed_paths() -> None:
    with pytest.raises(ConfigurationError):
        cfg()
    with pytest.raises(ConfigurationError):
        cfg("dir:05_Projekte", "file:05_Projekte")
    with pytest.raises(ValueError):
        validate_path("05_Projekte///")
    with pytest.raises(ValueError):
        cfg("05_Projekte", denied=("/05_Projekte",))


@pytest.mark.asyncio
async def test_virtual_listing_file_and_folder_are_reported_correctly() -> None:
    calls = []
    async with NextcloudWebDAV(cfg("05_Projekte", "06_Marketing/CI.pdf"), transport=httpx.MockTransport(make_handler(calls))) as dav:
        listing = await dav.list_files("")
        assert [(x["path"], x["is_dir"]) for x in listing["items"]] == [
            ("05_Projekte", True), ("06_Marketing/CI.pdf", False),
        ]
        with pytest.raises(ValueError, match="Datei"):
            await dav.list_files("06_Marketing/CI.pdf")
        assert (await dav.info("06_Marketing/CI.pdf")).is_dir is False
    assert all(method == "PROPFIND" for method, _ in calls)


@pytest.mark.asyncio
async def test_deny_filters_listing_search_and_blocks_get_without_network() -> None:
    calls = []
    config = cfg("05_Projekte", denied=("05_Projekte/Vertraulich",))
    async with NextcloudWebDAV(config, transport=httpx.MockTransport(make_handler(calls))) as dav:
        listing = await dav.list_files("05_Projekte")
        assert [x["name"] for x in listing["items"]] == ["Offen"]
        found = await dav.search_files("Vertraulich", max_depth=3)
        assert found["results"] == []
        found = await dav.search_files("Plan", max_depth=3)
        assert [x["path"] for x in found["results"]] == ["05_Projekte/Offen/Plan.md"]
        assert (await dav.read_file("05_Projekte/Offen/Plan.md"))["text"].startswith("# Freigegeben")
        n = len(calls)
        for forbidden in ("05_Projekte/Vertraulich/Kundenvertrag.pdf", "05_Projekte/Vertraulich"):
            with pytest.raises(PermissionError):
                await dav.info(forbidden)
            with pytest.raises(PermissionError):
                await dav.read_file(forbidden)
        assert len(calls) == n
        assert not any("Vertraulich" in path for _, path in calls)


@pytest.mark.asyncio
async def test_single_file_path_is_searchable_and_readable() -> None:
    calls = []
    config = cfg("file:06_Marketing/CI.pdf")
    async with NextcloudWebDAV(config, transport=httpx.MockTransport(make_handler(calls))) as dav:
        result = await dav.search_files("CI")
        assert len(result["results"]) == 1
        assert result["results"][0]["is_dir"] is False
        assert result["directories_scanned"] == 0
        assert result["complete"] is True
        with pytest.raises(PermissionError):
            await dav.read_file("06_Marketing/CI.pdf/foo")
        # PDF parser should reject fake bytes; even so policy/GET are enforced.
        with pytest.raises(Exception):
            await dav.read_file("06_Marketing/CI.pdf")
    assert not any(path.endswith("/foo") for _, path in calls)


@pytest.mark.asyncio
async def test_untyped_file_path_is_detected_from_webdav_not_extension() -> None:
    calls = []
    async with NextcloudWebDAV(cfg("07_Ablage/DateiOhneEndung"), transport=httpx.MockTransport(make_handler(calls))) as dav:
        results = await dav.list_files()
        assert results["items"][0]["is_dir"] is False
        assert (await dav.search_files("ohne"))["results"][0]["name"] == "DateiOhneEndung"
        with pytest.raises(PermissionError):
            await dav.info("07_Ablage/DateiOhneEndung/subfile")
    assert not any("subfile" in path for _, path in calls)


@pytest.mark.asyncio
async def test_explicit_type_mismatch_is_error() -> None:
    for entry in ("file:05_Projekte", "dir:06_Marketing/CI.pdf"):
        async with NextcloudWebDAV(cfg(entry), transport=httpx.MockTransport(make_handler([]))) as dav:
            with pytest.raises(WebDAVError, match="Freigabe-Typ"):
                await dav.list_files()


@pytest.mark.asyncio
async def test_nested_file_path_under_directory_has_no_duplicates_in_search() -> None:
    calls = []
    async with NextcloudWebDAV(cfg("05_Projekte", "file:05_Projekte/Offen/Plan.md"), transport=httpx.MockTransport(make_handler(calls))) as dav:
        result = await dav.search_files("Plan", max_depth=3)
        assert [x["path"] for x in result["results"]] == ["05_Projekte/Offen/Plan.md"]


def test_environment_uses_allowed_paths_and_denied_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXTCLOUD_URL", "https://storage.levuvo.com")
    monkeypatch.setenv("NEXTCLOUD_USERNAME", "agent.levuvo")
    monkeypatch.setenv("NEXTCLOUD_APP_PASSWORD", "DUMMY_TEST_SECRET")
    monkeypatch.setenv(
        "NEXTCLOUD_ALLOWED_PATHS", "dir:01_Unternehmen,file:06_Marketing/CI.pdf"
    )
    monkeypatch.setenv("NEXTCLOUD_DENIED_PATHS", "01_Unternehmen/Privat")
    settings = Settings.from_env()
    assert settings.allowed_paths == ("dir:01_Unternehmen", "file:06_Marketing/CI.pdf")
    assert settings.denied_paths == ("01_Unternehmen/Privat",)
    assert settings.require_allowed("01_Unternehmen/Allgemein.md") == "01_Unternehmen/Allgemein.md"
    with pytest.raises(PermissionError):
        settings.require_allowed("01_Unternehmen/Privat/Notiz.txt")


def test_environment_requires_allowed_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXTCLOUD_URL", "https://storage.levuvo.com")
    monkeypatch.setenv("NEXTCLOUD_USERNAME", "agent.levuvo")
    monkeypatch.setenv("NEXTCLOUD_APP_PASSWORD", "DUMMY_TEST_SECRET")
    monkeypatch.delenv("NEXTCLOUD_ALLOWED_PATHS", raising=False)
    with pytest.raises(ConfigurationError, match="Mindestens eine erlaubte Datei"):
        Settings.from_env()
