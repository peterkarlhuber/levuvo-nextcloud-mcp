"""Shared test fixtures: an in-memory fake Nextcloud WebDAV server (no network)."""

from __future__ import annotations

import asyncio
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import formatdate
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape

import httpx
import pytest

from levuvo_nextcloud_mcp.settings import Settings

HOST = "storage.levuvo.com"
USER = "agent.levuvo"
SECRET = "DUMMY_TEST_SECRET"


@dataclass
class FakeNextcloud:
    """Minimal WebDAV server for ``httpx.MockTransport``.

    * Folders and files are keyed by their NFC relative path.
    * ``case_insensitive`` emulates a backend that resolves names case-insensitively.
    * Every request is recorded in ``requests`` as ``(method, relative_path)``; any
      method other than GET/PROPFIND fails the test immediately.
    """

    folders: set[str] = field(default_factory=set)
    files: dict[str, bytes] = field(default_factory=dict)
    user: str = USER
    host: str = HOST
    case_insensitive: bool = False
    permissions: str = "SG"
    delay: float = 0.0
    status_override: dict[str, int] = field(default_factory=dict)
    raw_override: dict[str, bytes] = field(default_factory=dict)
    headers_override: dict[str, dict[str, str]] = field(default_factory=dict)
    href_user: str | None = None
    requests: list[tuple[str, str]] = field(default_factory=list)
    concurrent: int = 0
    max_concurrent: int = 0

    def __post_init__(self) -> None:
        for path in list(self.files):
            parent = path.rpartition("/")[0]
            while parent:
                self.folders.add(parent)
                parent = parent.rpartition("/")[0]

    @property
    def base(self) -> str:
        return f"/remote.php/dav/files/{quote(self.user, safe='')}"

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _resolve(self, relative: str) -> str | None:
        if relative in self.folders or relative in self.files:
            return relative
        if self.case_insensitive:
            for candidate in [*self.folders, *self.files]:
                if candidate.casefold() == relative.casefold():
                    return candidate
        return None

    def href(self, path: str) -> str:
        user = quote(self.href_user or self.user, safe="")
        encoded = "/".join(quote(segment, safe="") for segment in path.split("/"))
        return f"/remote.php/dav/files/{user}/{encoded}" + ("/" if path in self.folders else "")

    def multistatus(self, paths: list[str]) -> bytes:
        parts = []
        for path in paths:
            is_dir = path in self.folders
            size = len(self.files.get(path, b""))
            resource = "<d:collection/>" if is_dir else ""
            parts.append(
                f"<d:response><d:href>{escape(self.href(path))}</d:href><d:propstat><d:prop>"
                f"<d:resourcetype>{resource}</d:resourcetype>"
                f"<d:getcontentlength>{size}</d:getcontentlength>"
                f"<d:getcontenttype>{'httpd/unix-directory' if is_dir else 'application/octet-stream'}</d:getcontenttype>"
                f"<d:getlastmodified>{formatdate(0, usegmt=True)}</d:getlastmodified>"
                f'<d:getetag>"etag-{abs(hash(path))}"</d:getetag>'
                f"<oc:permissions>{self.permissions}</oc:permissions>"
                "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
            )
        return (
            "<?xml version='1.0'?><d:multistatus xmlns:d='DAV:' xmlns:oc='http://owncloud.org/ns'>"
            + "".join(parts)
            + "</d:multistatus>"
        ).encode()

    async def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.method in {"GET", "PROPFIND"}, f"read-only guarantee violated: {request.method}"
        assert request.url.host == self.host
        assert request.headers["authorization"].startswith("Basic ")
        raw = request.url.raw_path.decode("ascii").split("?", 1)[0]
        assert raw.startswith(self.base + "/"), raw
        segments = raw[len(self.base) + 1 :].rstrip("/").split("/")
        # Nextcloud decodes once and normalises to NFC.
        relative = "/".join(unicodedata.normalize("NFC", unquote(segment)) for segment in segments)
        self.requests.append((request.method, relative))
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            headers = self.headers_override.get(relative, {})
            if relative in self.status_override:
                return httpx.Response(self.status_override[relative], headers=headers)
            if relative in self.raw_override:
                return httpx.Response(207, content=self.raw_override[relative], headers=headers)
            resolved = self._resolve(relative)
            if resolved is None:
                return httpx.Response(404)
            if request.method == "GET":
                if resolved not in self.files:
                    return httpx.Response(404)
                return httpx.Response(200, content=self.files[resolved], headers=headers)
            nodes = [resolved]
            if request.headers.get("Depth") == "1" and resolved in self.folders:
                nodes += sorted(p for p in [*self.folders, *self.files] if p.rpartition("/")[0] == resolved)
            return httpx.Response(207, content=self.multistatus(nodes), headers=headers)
        finally:
            self.concurrent -= 1

    def paths_requested(self) -> list[str]:
        return [path for _, path in self.requests]


def default_tree() -> FakeNextcloud:
    return FakeNextcloud(
        files={
            "05_Projekte/Offen/Plan.md": b"# Freigegeben\nHier ist ein Plan.",
            "05_Projekte/Offen/Kunde A/Projektplan.txt": b"Projektplan Kunde A",
            "05_Projekte/Offen/Leerzeichen und #Raute?.txt": b"Sonderzeichen ok",
            "05_Projekte/Offen/Ümlaut Übersicht.md": "Umlaute äöü".encode(),
            "05_Projekte/Vertraulich/Kundenvertrag.pdf": b"SENSITIVE",
            "05_Projekte/Vertraulich/Intern/Kosten.xlsx": b"PRIVATE",
            "05_Projekte/Geschäftsführung/Gehälter.txt": b"SECRET SALARY",
            "06_Marketing/CI.md": b"Corporate Identity",
            "06_Marketing/Intern.md": b"Marketing intern",
            "07_Ablage/DateiOhneEndung": b"Info",
            "08_Privat/Tagebuch.txt": b"PRIVATE DIARY",
        }
    )


@pytest.fixture
def nextcloud() -> FakeNextcloud:
    return default_tree()


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def factory(*allowed: str, denied: tuple[str, ...] = (), **overrides: object) -> Settings:
        values: dict[str, object] = {
            "base_url": f"https://{HOST}",
            "username": USER,
            "app_password": SECRET,
            "allowed_paths": allowed,
            "denied_paths": denied,
        }
        values.update(overrides)
        return Settings(**values)  # type: ignore[arg-type]

    return factory


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    """Remove all configuration variables for config tests and drop any that a test loaded."""
    import os

    prefixes = ("NEXTCLOUD_", "MCP_", "LEVUVO_")
    for name in list(os.environ):
        if name.startswith(prefixes):
            monkeypatch.delenv(name, raising=False)
    yield monkeypatch
    for name in list(os.environ):
        if name.startswith(prefixes):
            del os.environ[name]
