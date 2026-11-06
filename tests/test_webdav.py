"""Network-free, executable checks against a mocked Nextcloud WebDAV endpoint."""
from __future__ import annotations

from urllib.parse import unquote, urlsplit

import httpx
import pytest

from levuvo_nextcloud_mcp.policy import normalize_path as validate_path
from levuvo_nextcloud_mcp.settings import Settings
from levuvo_nextcloud_mcp.webdav import NextcloudWebDAV

BASE = "/remote.php/dav/files/agent.levuvo"


def config() -> Settings:
    return Settings(
        base_url="https://storage.levuvo.com",
        username="agent.levuvo",
        app_password="DUMMY_TEST_SECRET",
        allowed_paths=("05_Projekte", "01_Unternehmen/Strategie"),
    )


def response_xml(folder: str, entries: list[tuple[str, bool, int]], *, self_is_dir: bool = True) -> bytes:
    def element(path: str, is_dir: bool, size: int) -> str:
        href = BASE + "/" + path
        if is_dir:
            href += "/"
        resource = "<d:collection/>" if is_dir else ""
        return f"""<d:response>
          <d:href>{href}</d:href><d:propstat><d:prop>
          <d:resourcetype>{resource}</d:resourcetype>
          <d:getcontentlength>{size}</d:getcontentlength>
          <d:getcontenttype>text/plain</d:getcontenttype>
          <oc:permissions>G</oc:permissions>
          </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
          </d:response>"""
    return ("<d:multistatus xmlns:d='DAV:' xmlns:oc='http://owncloud.org/ns'>"
            + element(folder, self_is_dir, 0)
            + "".join(element(*e) for e in entries)
            + "</d:multistatus>").encode()


def mock_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "storage.levuvo.com"
    assert request.method in {"GET", "PROPFIND"}, "Read-only guarantee violated"
    # Auth remains in requests to this domain only; never in returned tool results.
    assert request.headers["authorization"].startswith("Basic ")
    path = unquote(urlsplit(str(request.url)).path)
    if request.method == "PROPFIND":
        if path.rstrip("/") == BASE + "/05_Projekte":
            return httpx.Response(207, content=response_xml("05_Projekte", [
                ("05_Projekte/Kunde A", True, 0),
                ("05_Projekte/Planung.md", False, 30),
                ("05_Projekte/Ausserhalb.txt", False, 19),
            ]))
        if path.rstrip("/") == BASE + "/05_Projekte/Kunde A":
            return httpx.Response(207, content=response_xml("05_Projekte/Kunde A", [
                ("05_Projekte/Kunde A/Projektplan.txt", False, 21),
            ]))
        if path.rstrip("/") == BASE + "/05_Projekte/Planung.md":
            return httpx.Response(207, content=response_xml("05_Projekte/Planung.md", [], self_is_dir=False))
        if path.rstrip("/") == BASE + "/01_Unternehmen/Strategie":
            return httpx.Response(207, content=response_xml("01_Unternehmen/Strategie", []))
        return httpx.Response(404)
    if path == BASE + "/05_Projekte/Planung.md":
        return httpx.Response(200, content=b"# Roadmap\nHallo Levuvo", headers={"Content-Length": "22"})
    return httpx.Response(404)


@pytest.mark.parametrize("bad", [
    "../05_Projekte", "/05_Projekte", "05_Projekte/../03_Vertraege",
    "05_Projekte//Hallo", "05_Projekte\\Hallo", "05_Projekte/./Hallo",
    "05_Projekte\nFehler", "",
])
def test_invalid_paths(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_path(bad)


def test_paths_outside_allowlist_are_rejected() -> None:
    s = config()
    for name in ["03_Vertraege", "01_Unternehmen", "05_ProjekteX", "", "06_Marketing"]:
        with pytest.raises((ValueError, PermissionError)):
            s.require_allowed(name)
    assert s.require_allowed("01_Unternehmen/Strategie/Ziele.md") == "01_Unternehmen/Strategie/Ziele.md"
    assert s.require_allowed("05_Projekte/Planung.md") == "05_Projekte/Planung.md"


@pytest.mark.asyncio
async def test_virtual_listing_is_allowlist_only() -> None:
    async with NextcloudWebDAV(config(), transport=httpx.MockTransport(mock_handler)) as dav:
        listing = await dav.list_files()
        assert [x["path"] for x in listing["items"]] == ["05_Projekte", "01_Unternehmen/Strategie"]


@pytest.mark.asyncio
async def test_list_and_read_and_metadata() -> None:
    async with NextcloudWebDAV(config(), transport=httpx.MockTransport(mock_handler)) as dav:
        entries = await dav.list_files("05_Projekte")
        assert entries["items"][0]["path"] == "05_Projekte/Kunde A"
        assert entries["items"][1]["path"] == "05_Projekte/Ausserhalb.txt"
        metadata = await dav.info("05_Projekte/Planung.md")
        assert metadata.is_dir is False
        document = await dav.read_file("05_Projekte/Planung.md")
        assert document["text"].startswith("# Roadmap")
        assert document["format"] == ".md"
        assert "DUMMY_TEST_SECRET" not in str(document)


@pytest.mark.asyncio
async def test_recursive_search_is_bounded() -> None:
    async with NextcloudWebDAV(config(), transport=httpx.MockTransport(mock_handler)) as dav:
        found = await dav.search_files("Projektplan", max_depth=2)
        assert len(found["results"]) == 1
        assert found["results"][0]["path"] == "05_Projekte/Kunde A/Projektplan.txt"
        no_folders = await dav.search_files("Projektplan", max_depth=0)
        assert no_folders["results"] == []


@pytest.mark.asyncio
async def test_no_network_request_for_forbidden_path() -> None:
    requested = []

    def track(req: httpx.Request) -> httpx.Response:
        requested.append(req.method)
        return httpx.Response(200)

    async with NextcloudWebDAV(config(), transport=httpx.MockTransport(track)) as dav:
        with pytest.raises(PermissionError):
            await dav.read_file("03_Vertraege/Vertrag.pdf")
        with pytest.raises(PermissionError):
            await dav.list_files("01_Unternehmen")
    assert requested == []


@pytest.mark.asyncio
async def test_redirect_is_never_followed() -> None:
    requested = []

    def redirect(req: httpx.Request) -> httpx.Response:
        requested.append(req.url.host)
        return httpx.Response(302, headers={"Location": "https://attacker.example/collect"})

    async with NextcloudWebDAV(config(), transport=httpx.MockTransport(redirect)) as dav:
        with pytest.raises(Exception):
            await dav.info("05_Projekte/Planung.md")
    assert requested == ["storage.levuvo.com"]


def test_credentials_are_not_part_of_url() -> None:
    dav = NextcloudWebDAV(config(), transport=httpx.MockTransport(mock_handler))
    url = dav._url("05_Projekte/Datei mit Leerzeichen.md")
    assert url == "https://storage.levuvo.com/remote.php/dav/files/agent.levuvo/05_Projekte/Datei%20mit%20Leerzeichen.md"
    assert "DUMMY_TEST_SECRET" not in url


def test_nextcloud_password_placeholder_rejected() -> None:
    from dataclasses import replace
    from levuvo_nextcloud_mcp.errors import ConfigurationError
    with pytest.raises(ConfigurationError):
        replace(config(), app_password="EIGENES_NEXTCLOUD_APP_PASSWORT")
