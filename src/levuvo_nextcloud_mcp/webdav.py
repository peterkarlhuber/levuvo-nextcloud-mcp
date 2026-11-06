"""Read-only Nextcloud WebDAV client with central policy checks and strict response bounds.

Only two HTTP methods are ever sent: ``PROPFIND`` (metadata) and ``GET`` (download).
Every method of :class:`NextcloudWebDAV` validates the requested path with the
:class:`~.policy.AccessPolicy` *before* any network request is made.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from urllib.parse import quote, unquote, urlsplit

import httpx
from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET

from . import __version__
from .doc_cache import ExtractionCache
from .errors import (
    AccessDeniedError,
    FileChangedError,
    InvalidArgumentError,
    LevuvoError,
    LimitExceededError,
    NextcloudError,
    NotFoundError,
)
from .extractors import HTML_EXTENSIONS, MAX_EXTRACTED_CHARS, UNTRUSTED, Extraction, extract_document
from .policy import ACCESS_DENIED_MESSAGE, PathRule, fold_key
from .settings import Settings

DAV = "{DAV:}"
OC = "{http://owncloud.org/ns}"
NC = "{http://nextcloud.org/ns}"
OCS = "{http://open-collaboration-services.org/ns}"
PROPFIND_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:prop>
    <d:resourcetype/><d:getcontentlength/><d:getcontenttype/>
    <d:getlastmodified/><d:getetag/><oc:permissions/>
  </d:prop>
</d:propfind>"""
# Only used by --check-nextcloud: additionally asks for share/mount metadata documented in the
# Nextcloud WebDAV API (nc:mount-type, nc:is-mount-root, ocs:share-permissions).
PROPFIND_DIAGNOSTIC_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns" xmlns:nc="http://nextcloud.org/ns"
            xmlns:ocs="http://open-collaboration-services.org/ns">
  <d:prop>
    <d:resourcetype/><d:getcontentlength/><d:getcontenttype/>
    <d:getlastmodified/><d:getetag/><oc:permissions/>
    <nc:mount-type/><nc:is-mount-root/><ocs:share-permissions/>
  </d:prop>
</d:propfind>"""
ALLOWED_METHODS = frozenset({"GET", "PROPFIND"})
MAX_XML_BYTES = 2_000_000
MAX_DIRECTORY_ITEMS = 2000
SEARCH_CONCURRENCY = 4
# Why search_files may report complete=false, in the order they are listed.
INCOMPLETE_REASONS = ("depth_limit", "directory_limit", "result_limit")
EXTRACTION_CONCURRENCY = 2
# Files above this size are downloaded and extracted one at a time (RAM on small servers).
LARGE_FILE_BYTES = 16_000_000
# Downloads are spooled: kept in memory up to this size, beyond it in an anonymous temporary file
# (created with mode 0600 and already unlinked, so it disappears even if the process crashes).
SPOOL_MEMORY_BYTES = 4_000_000
MAX_SECTIONS_RETURNED = 200
TYPE_CACHE_SECONDS = 300.0
# Nextcloud permission letters that mean the technical account could modify something.
WRITE_PERMISSION_LETTERS = frozenset("WCKDNV")
# Letters that also appear on the mount point of a received share (unshare/rename the mount).
MOUNT_POINT_LETTERS = frozenset("DNV")
# ocs:share-permissions bits: 1 read, 2 update, 4 create, 8 delete, 16 share.
SHARE_PERMISSION_NAMES = {1: "read", 2: "update", 4: "create", 8: "delete", 16: "share"}
SHARE_WRITE_BITS = 2 | 4 | 8


@dataclass(frozen=True)
class FileInfo:
    path: str
    name: str
    is_dir: bool
    size_bytes: int | None = None
    content_type: str | None = None
    modified: str | None = None
    etag: str | None = None
    permissions: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class NextcloudWebDAV:
    """One instance per process; reuses a pooled HTTPS connection to Nextcloud."""

    def __init__(self, config: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self.policy = config.policy
        self._base_path = "/remote.php/dav/files/" + quote(config.dav_user, safe="")
        self._base_url = config.base_url.rstrip("/") + self._base_path
        self._base_parts = ["remote.php", "dav", "files", config.dav_user]
        origin = urlsplit(config.base_url)
        self._origin = (origin.scheme, origin.netloc)
        self._types: dict[str, tuple[bool, float]] = {}
        self._extract_slots = asyncio.Semaphore(EXTRACTION_CONCURRENCY)
        self._large_slot = asyncio.Semaphore(1)
        self.cache = ExtractionCache()
        self._http = httpx.AsyncClient(
            auth=httpx.BasicAuth(config.username, config.app_password),
            timeout=httpx.Timeout(config.timeout_seconds, connect=min(10.0, config.timeout_seconds)),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=30),
            follow_redirects=False,  # Never forward credentials to a redirect target.
            trust_env=False,  # Ignore proxy/.netrc settings from the environment.
            verify=True,
            transport=transport,
            headers={"User-Agent": f"Levuvo-Nextcloud-MCP/{__version__}", "OCS-APIRequest": "true"},
        )

    async def __aenter__(self) -> NextcloudWebDAV:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ HTTP layer
    def _url(self, path: str, *, folder: bool = False) -> str:
        normalized = self.policy.check(path)
        encoded = "/".join(quote(segment, safe="") for segment in normalized.split("/"))
        return self._base_url + "/" + encoded + ("/" if folder else "")

    @staticmethod
    def _status_error(response: httpx.Response) -> NextcloudError | NotFoundError:
        status = response.status_code
        if status == 404:
            return NotFoundError("File or folder not found.")
        if status == 401:
            return NextcloudError("Nextcloud authentication failed: check the username and app password.")
        if status == 403:
            return NextcloudError("Nextcloud denied access: check the share permissions of the technical account.")
        if status == 429:
            retry = response.headers.get("Retry-After", "").strip()
            hint = f" Retry in {retry} s." if retry.isdigit() else ""
            return NextcloudError("Nextcloud is currently rate-limiting requests (HTTP 429)." + hint)
        if 300 <= status < 400:
            return NextcloudError(f"Nextcloud responded with a redirect (HTTP {status}); check NEXTCLOUD_URL.")
        if status >= 500:
            return NextcloudError(f"Nextcloud is currently unavailable (HTTP {status}).")
        return NextcloudError(f"Nextcloud returned HTTP {status}.")

    @asynccontextmanager
    async def _request(self, method: str, url: str, **kwargs: object) -> AsyncIterator[httpx.Response]:
        if method not in ALLOWED_METHODS:  # Defence in depth: this client is read-only by construction.
            raise RuntimeError(f"HTTP method {method} is not allowed")
        try:
            async with self._http.stream(method, url, **kwargs) as response:  # type: ignore[arg-type]
                yield response
        except httpx.TimeoutException:
            raise NextcloudError("Timeout while connecting to Nextcloud.") from None
        except httpx.RequestError:
            raise NextcloudError("Connection to Nextcloud failed (network or TLS).") from None

    @staticmethod
    async def _read_limited(response: httpx.Response, limit: int, message: str) -> bytes:
        length = response.headers.get("Content-Length", "").strip()
        if length.isdigit() and int(length) > limit:
            raise LimitExceededError(message)
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise LimitExceededError(message)
        return bytes(data)

    # ------------------------------------------------------------------ PROPFIND
    async def _propfind(self, path: str, depth: int, *, diagnostics: dict | None = None) -> list[FileInfo]:
        path = self.policy.check(path)
        await self._check_containment(path)
        async with self._request(
            "PROPFIND",
            self._url(path, folder=(depth == 1)),
            headers={"Depth": str(depth), "Content-Type": "application/xml; charset=utf-8"},
            content=PROPFIND_XML if diagnostics is None else PROPFIND_DIAGNOSTIC_XML,
        ) as response:
            if response.status_code != 207:
                raise self._status_error(response)
            payload = await self._read_limited(
                response, MAX_XML_BYTES, "The Nextcloud directory response is too large; choose a smaller folder."
            )
        infos = self._parse_multistatus(payload, requested=path, depth=depth, diagnostics=diagnostics)
        own = next((info for info in infos if info.path == path), None)
        if own is None:
            raise NextcloudError(
                "The WebDAV response does not contain the requested path. If the Nextcloud user ID differs "
                "from the login name, set NEXTCLOUD_USER_ID."
            )
        for rule in self.policy.allowed:
            if rule.path == path:
                self._verify_kind(rule, own.is_dir)
                self._types[path] = (own.is_dir, time.monotonic())
        return infos

    @staticmethod
    def _verify_kind(rule: PathRule, is_dir: bool) -> None:
        if rule.kind != "auto" and (rule.kind == "dir") != is_dir:
            actual = "folder" if is_dir else "file"
            raise NextcloudError(
                f"Configured entry type contradicts Nextcloud: '{rule.source}' is actually a {actual}. "
                "Check the file:/dir: configuration."
            )

    async def _allowed_is_dir(self, path: str) -> bool:
        cached = self._types.get(path)
        if cached and time.monotonic() - cached[1] < TYPE_CACHE_SECONDS:
            return cached[0]
        infos = await self._propfind(path, depth=0)
        return next(info.is_dir for info in infos if info.path == path)

    async def _check_containment(self, path: str) -> None:
        """A path *below* an untyped allowed entry is only released if that entry is a folder."""
        matched = self.policy.matching_allows(path)
        if not matched:
            raise AccessDeniedError(ACCESS_DENIED_MESSAGE)
        if any(rule.path == path for rule in matched):
            return
        for rule in matched:
            if await self._allowed_is_dir(rule.path):
                return
        raise AccessDeniedError(ACCESS_DENIED_MESSAGE)

    def _parse_multistatus(
        self, payload: bytes, *, requested: str, depth: int, diagnostics: dict | None = None
    ) -> list[FileInfo]:
        try:
            xml = SafeET.fromstring(payload, forbid_dtd=True)
        except (DefusedXmlException, SafeET.ParseError, ValueError):
            raise NextcloudError("Invalid or unsafe WebDAV XML response from Nextcloud.") from None
        if xml.tag != f"{DAV}multistatus":
            raise NextcloudError("Unexpected WebDAV response from Nextcloud (no multistatus).")
        found: list[FileInfo] = []
        seen: set[str] = set()
        responses = xml.findall(f"{DAV}response")
        if len(responses) > MAX_DIRECTORY_ITEMS + 1:
            raise LimitExceededError("Too many directory entries; choose a smaller folder.")
        for item in responses:
            relative = self._relative_from_href(item.findtext(f"{DAV}href"))
            if relative is None or relative in seen:
                continue
            if depth == 0 and relative != requested:
                continue
            if depth == 1 and not (relative == requested or relative.rpartition("/")[0] == requested):
                continue
            if self.policy.is_denied(relative):
                self._check_denied_kind(relative, item)
                continue
            if relative != requested and not self.policy.matching_allows(relative):
                continue
            prop = self._ok_prop(item)
            if prop is None:
                continue
            resource_type = prop.find(f"{DAV}resourcetype")
            is_dir = resource_type is not None and resource_type.find(f"{DAV}collection") is not None
            size_text = (prop.findtext(f"{DAV}getcontentlength") or "").strip()
            seen.add(relative)
            if diagnostics is not None:
                diagnostics[relative] = self._share_metadata(prop)
            found.append(
                FileInfo(
                    path=relative,
                    name=relative.rsplit("/", 1)[-1],
                    is_dir=is_dir,
                    size_bytes=int(size_text) if size_text.isdigit() else None,
                    content_type=prop.findtext(f"{DAV}getcontenttype"),
                    modified=prop.findtext(f"{DAV}getlastmodified"),
                    etag=prop.findtext(f"{DAV}getetag"),
                    permissions=prop.findtext(f"{OC}permissions"),
                )
            )
        return found

    @staticmethod
    def _share_metadata(prop: object) -> dict:
        """Extract documented share/mount properties; None means 'not delivered by the server'."""
        mount_type = prop.find(f"{NC}mount-type")  # type: ignore[attr-defined]
        mount_root = prop.find(f"{NC}is-mount-root")  # type: ignore[attr-defined]
        share = (prop.findtext(f"{OCS}share-permissions") or "").strip()  # type: ignore[attr-defined]
        root_text = (mount_root.text or "").strip().lower() if mount_root is not None else ""
        return {
            "mount_type": (mount_type.text or "").strip() if mount_type is not None else None,
            "mount_root": {"true": True, "1": True, "false": False, "0": False}.get(root_text),
            "share_permissions": int(share) if share.isdigit() else None,
        }

    def _check_denied_kind(self, relative: str, item: object) -> None:
        rule = self.policy.denied_rule_for(relative)
        if rule is None or rule.kind == "auto":
            return
        prop = self._ok_prop(item)
        if prop is None:
            return
        resource_type = prop.find(f"{DAV}resourcetype")
        is_dir = resource_type is not None and resource_type.find(f"{DAV}collection") is not None
        self._verify_kind(rule, is_dir)

    @staticmethod
    def _ok_prop(item: object):
        for propstat in item.findall(f"{DAV}propstat"):  # type: ignore[attr-defined]
            status = propstat.findtext(f"{DAV}status") or ""
            if " 200 " in status:
                prop = propstat.find(f"{DAV}prop")
                if prop is not None:
                    return prop
        return None

    def _relative_from_href(self, href: str | None) -> str | None:
        """Map an href to a canonical relative path, or None if it is foreign/invalid."""
        if not href:
            return None
        parsed = urlsplit(href.strip())
        if parsed.netloc and (parsed.scheme, parsed.netloc) != self._origin:
            return None
        if parsed.query or parsed.fragment:
            return None
        # Split first, then decode each segment once: %2F can never create a new level.
        parts = [unicodedata.normalize("NFC", unquote(segment)) for segment in parsed.path.strip("/").split("/")]
        base = [unicodedata.normalize("NFC", part) for part in self._base_parts]
        if parts[:4] != base:
            return None
        relative_parts = parts[4:]
        if not relative_parts or any(part in ("", ".", "..") or "/" in part or "\\" in part for part in relative_parts):
            return None
        relative = "/".join(relative_parts)
        if any(unicodedata.category(char) in ("Cc", "Cf", "Cs", "Co") for char in relative):
            return None
        return relative

    # ------------------------------------------------------------------ public API
    async def info(self, path: str) -> FileInfo:
        normalized = self.policy.check(path)
        infos = await self._propfind(normalized, depth=0)
        return next(info for info in infos if info.path == normalized)

    async def list_files(self, path: str = "", *, limit: int = 100) -> dict:
        if not isinstance(limit, int) or not 1 <= limit <= 250:
            raise InvalidArgumentError("limit must be between 1 and 250.")
        if not path:
            items = [(await self.info(rule.path)).to_dict() for rule in self.policy.allowed]
            return {"folder": "", "items": items[:limit], "truncated": len(items) > limit}
        normalized = self.policy.check(path)
        infos = await self._propfind(normalized, depth=1)
        own = next(info for info in infos if info.path == normalized)
        if not own.is_dir:
            raise InvalidArgumentError("This is a file. Use get_file_info or read_file.")
        children = [entry.to_dict() for entry in infos if entry.path != normalized]
        children.sort(key=lambda item: (not item["is_dir"], item["name"].casefold()))
        return {"folder": normalized, "items": children[:limit], "truncated": len(children) > limit}

    async def search_files(self, query: str, *, path: str = "", max_depth: int = 3, max_results: int = 25) -> dict:
        """Breadth-first name search below the released entries or below one released folder (*path*).

        The server-side limits come from the settings (``NEXTCLOUD_SEARCH_*``); a call can lower
        but never exceed them. ``complete`` is only true if the chosen area was searched entirely;
        otherwise ``incomplete_reasons`` names every limit that actually cut the search.
        """
        depth_cap = self.config.search_max_depth
        result_cap = self.config.search_max_results
        budget = self.config.search_max_directories
        if not isinstance(query, str) or not query.strip() or len(query) > 120:
            raise InvalidArgumentError("A search string of 1-120 characters is required.")
        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 0 <= max_depth <= depth_cap:
            raise InvalidArgumentError(f"max_depth must be between 0 and {depth_cap}.")
        if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= result_cap:
            raise InvalidArgumentError(f"max_results must be between 1 and {result_cap}.")
        if not isinstance(path, str):
            raise InvalidArgumentError("path must be a string.")
        term = unicodedata.normalize("NFC", query).casefold().strip()
        matches: list[dict] = []
        matched: set[str] = set()
        reasons: set[str] = set()

        def consider(entry: FileInfo) -> None:
            if entry.path in matched or term not in entry.name.casefold():
                return
            if len(matches) >= max_results:
                reasons.add("result_limit")  # a further hit exists that is not returned
                return
            matches.append(entry.to_dict())
            matched.add(entry.path)

        frontier: list[str] = []
        scope = ""
        if path:
            # The start folder is checked by the central policy like every other path; its own
            # name is not a candidate, only what lies inside it.
            scope = self.policy.check(path)
            start = await self.info(scope)
            if not start.is_dir:
                raise InvalidArgumentError("path must be a folder; this is a file. Use get_file_info or read_file.")
            frontier.append(scope)
        else:
            for rule in self.policy.allowed:
                metadata = await self.info(rule.path)
                consider(metadata)  # released files and folders are candidates themselves
                if metadata.is_dir:
                    frontier.append(metadata.path)
        visited: set[str] = set()
        slots = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def scan(folder: str) -> list[FileInfo]:
            async with slots:
                return await self._propfind(folder, depth=1)

        level = 0
        while frontier:
            if len(matches) >= max_results:
                reasons.add("result_limit")  # folders remain unscanned
                break
            batch = [folder for folder in dict.fromkeys(frontier) if folder not in visited]
            room = budget - len(visited)
            if len(batch) > room:
                batch = batch[:room]
                reasons.add("directory_limit")
            if not batch:
                break
            visited.update(batch)
            listings = await asyncio.gather(*(scan(folder) for folder in batch))
            frontier = []
            for folder, listing in zip(batch, listings, strict=True):
                for entry in listing:
                    if entry.path == folder:
                        continue
                    consider(entry)
                    if not entry.is_dir or entry.path in visited:
                        continue
                    if level >= max_depth:
                        reasons.add("depth_limit")  # a subfolder below max_depth is not searched
                    elif len(frontier) <= budget:  # never queue more folders than could be scanned
                        frontier.append(entry.path)
                    else:
                        reasons.add("directory_limit")
            level += 1
        ordered = [reason for reason in INCOMPLETE_REASONS if reason in reasons]
        return {
            "query": query,
            "path": scope,
            "results": matches,
            "directories_scanned": len(visited),
            "complete": not ordered,
            "incomplete_reasons": ordered,
            "note": "File and folder name search only; no full-text search inside documents.",
        }

    async def read_file(
        self,
        path: str,
        *,
        max_chars: int = 16000,
        offset: int = 0,
        etag: str | None = None,
        html_visible_text: bool = False,
    ) -> dict:
        """Return ``max_chars`` characters of the extracted text starting at ``offset``.

        The whole document is extracted once (bounded, see ``extractors``) and kept in a short-lived
        cache keyed by path and ETag, so follow-up calls with ``next_offset`` do not download or
        parse the file again unless it changed.
        """
        normalized = self.policy.check(path)
        if not isinstance(max_chars, int) or not 100 <= max_chars <= 30000:
            raise InvalidArgumentError("max_chars must be between 100 and 30000.")
        if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= MAX_EXTRACTED_CHARS:
            raise InvalidArgumentError(f"offset must be between 0 and {MAX_EXTRACTED_CHARS}.")
        if etag is not None and (not isinstance(etag, str) or not etag.strip() or len(etag) > 200):
            raise InvalidArgumentError("etag must be the non-empty etag value returned by a previous read_file call.")
        metadata = await self.info(normalized)
        if metadata.is_dir:
            raise InvalidArgumentError("This is a folder. Use list_files.")
        if etag is not None and metadata.etag is not None and etag != metadata.etag:
            raise FileChangedError(
                "The file has changed since the previous read_file call (ETag mismatch). Earlier sections "
                "may no longer match; read the file again from offset 0."
            )
        visible = bool(html_visible_text) and normalized.rsplit(".", 1)[-1].lower() in {
            ext.lstrip(".") for ext in HTML_EXTENSIONS
        }
        key = (normalized, metadata.etag or "", visible)
        document = self.cache.get(key) if metadata.etag else None
        size_bytes = metadata.size_bytes
        if document is None:
            document, size_bytes = await self._extract(normalized, metadata, visible)
            if metadata.etag:
                self.cache.put(key, document)
        return self._section(normalized, document, size_bytes, metadata.etag, offset, max_chars, visible)

    async def _extract(self, normalized: str, metadata: FileInfo, visible: bool) -> tuple[Extraction, int]:
        limit = self.config.max_file_bytes
        too_large = f"The file exceeds the download limit of {limit} bytes (NEXTCLOUD_MAX_FILE_BYTES)."
        if metadata.size_bytes is not None and metadata.size_bytes > limit:
            raise LimitExceededError(too_large)
        large = metadata.size_bytes is None or metadata.size_bytes > LARGE_FILE_BYTES
        async with self._extract_slots:
            if large:
                await self._large_slot.acquire()
            try:
                with tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode="w+b") as spool:
                    async with self._request(
                        "GET", self._url(normalized), headers={"Accept": "application/octet-stream"}
                    ) as response:
                        if response.status_code != 200:
                            raise self._status_error(response)
                        size = await self._spool_limited(response, spool, limit, too_large)
                    spool.seek(0)
                    # CPU-bound parsing must not block the event loop (parallel HTTP clients).
                    document = await asyncio.to_thread(extract_document, normalized, spool, html_visible_text=visible)
            finally:
                if large:
                    self._large_slot.release()
        return document, size

    @staticmethod
    async def _spool_limited(response: httpx.Response, spool, limit: int, message: str) -> int:
        length = response.headers.get("Content-Length", "").strip()
        if length.isdigit() and int(length) > limit:
            raise LimitExceededError(message)
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > limit:
                raise LimitExceededError(message)
            spool.write(chunk)
        return size

    @staticmethod
    def _section(
        path: str,
        document: Extraction,
        size_bytes: int | None,
        etag: str | None,
        offset: int,
        max_chars: int,
        visible: bool,
    ) -> dict:
        total = len(document.text)
        if offset > total:
            raise InvalidArgumentError(
                f"offset {offset} is beyond the end of the extracted text (total_chars={total})."
            )
        text = document.text[offset : offset + max_chars]
        end = offset + len(text)
        has_more = end < total
        result: dict = {
            "path": path,
            "format": document.format,
            "size_bytes": size_bytes,
            "text": text,
            # True whenever this response does not contain the complete document text.
            "truncated": has_more or offset > 0 or not document.complete,
            "note": UNTRUSTED,
            "offset": offset,
            "returned_chars": len(text),
            "next_offset": end if has_more else None,
            "has_more": has_more,
            "total_chars": total,
            "extraction_complete": document.complete,
            "etag": etag,
        }
        if document.notes:
            result["extraction_notes"] = list(document.notes)
        if document.encoding:
            result["encoding"] = document.encoding
        if visible:
            result["html_visible_text"] = True
        if offset == 0 and document.sections:
            result["sections"] = [
                {"title": title, "offset": start} for title, start in document.sections[:MAX_SECTIONS_RETURNED]
            ]
            if len(document.sections) > MAX_SECTIONS_RETURNED:
                result["sections_truncated"] = True
        return result

    async def check_access(self) -> list[dict]:
        """Read-only self-check of all allowed entries (used by ``--check-nextcloud``).

        Only PROPFIND is used. Each entry keeps the keys of 0.5.0 (``entry``, ``is_dir``,
        ``permissions``, ``writable_in_nextcloud`` = raw letter finding on the entry itself) and
        gets an additive, conservative interpretation, see :meth:`_diagnose`.
        """
        report = []
        for rule in self.policy.allowed:
            try:
                report.append(await self._diagnose(rule))
            except LevuvoError as exc:
                report.append(
                    {
                        "entry": rule.source,
                        "is_dir": None,
                        "permissions": None,
                        "writable_in_nextcloud": None,
                        "assessment": "error",
                        "content_writable": None,
                        "verified": False,
                        "notes": [str(exc)],
                    }
                )
        return report

    async def _diagnose(self, rule: PathRule) -> dict:
        extras: dict[str, dict] = {}
        own = next(
            info for info in await self._propfind(rule.path, depth=0, diagnostics=extras) if info.path == rule.path
        )
        meta = extras.get(own.path, {"mount_type": None, "mount_root": None, "share_permissions": None})
        letters = set(own.permissions or "")
        notes: list[str] = []
        definite_write: list[str] = []
        open_points: list[str] = []
        mount_root = meta["mount_root"]
        share_bits = meta["share_permissions"]

        if own.permissions is None:
            open_points.append("Nextcloud does not return oc:permissions for this entry.")
        content_letters = letters & set("WCK")
        if content_letters:
            definite_write.append(
                f"Permissions {''.join(sorted(content_letters))} on the entry allow writing/creating."
            )
        mount_letters = letters & MOUNT_POINT_LETTERS
        if mount_letters:
            if mount_root is True:
                if "D" in mount_letters:
                    notes.append(
                        "D on the mount point of a share: according to the Nextcloud WebDAV documentation "
                        "(nc:is-mount-root) a mount point can only be unshared, not deleted."
                    )
                undocumented = "".join(sorted(mount_letters - {"D"}))
                if undocumented:
                    open_points.append(
                        f"{undocumented} on the mount point: presumably renaming/moving the own mount point; "
                        "not described in the Nextcloud documentation."
                    )
            elif mount_root is False or meta["mount_type"] == "":
                definite_write.append(
                    f"Permissions {''.join(sorted(mount_letters))} on an entry that is not the mount point of a share: "
                    "deleting/renaming affects the original data."
                )
            else:
                open_points.append(
                    f"Permissions {''.join(sorted(mount_letters))} on the entry; Nextcloud does not return "
                    "nc:is-mount-root, so it is unclear whether only the mount point is affected."
                )

        if share_bits is not None:
            names = [name for bit, name in SHARE_PERMISSION_NAMES.items() if share_bits & bit]
            notes.append(
                f"Share permissions according to ocs:share-permissions ({share_bits}): {', '.join(names) or 'none'}."
            )
            if share_bits & SHARE_WRITE_BITS:
                definite_write.append("The share allows updating, creating or deleting (ocs:share-permissions).")
        elif meta["mount_type"] == "":
            notes.append("The entry is in the technical account's own storage (not a received share).")
        else:
            open_points.append("Nextcloud does not return ocs:share-permissions; check the share permissions manually.")

        children_checked = 0
        children_flagged: list[str] = []
        children_truncated = False
        if own.is_dir:
            try:
                children = [
                    info
                    for info in await self._propfind(own.path, depth=1, diagnostics=extras)
                    if info.path != own.path
                ]
            except LimitExceededError:
                children, children_truncated = [], True
                open_points.append(f"More than {MAX_DIRECTORY_ITEMS} entries: contents not checked.")
            children_checked = len(children)
            for child in children:
                child_letters = set(child.permissions or "") & WRITE_PERMISSION_LETTERS
                child_bits = extras.get(child.path, {}).get("share_permissions")
                if child_letters or (child_bits is not None and child_bits & SHARE_WRITE_BITS):
                    children_flagged.append(child.path)
            if children_flagged:
                definite_write.append(
                    f"{len(children_flagged)} direct entry/entries with write/delete/rename permissions, "
                    f"e.g. {children_flagged[0]}."
                )
            if not children and not children_truncated:
                notes.append("The folder is empty; content permissions can only be derived from the share permissions.")
            if any(child.is_dir for child in children):
                open_points.append("Only direct entries checked; deeper subfolders were not checked.")
            own_key = fold_key(own.path)
            if any(deny.key.startswith(own_key + "/") for deny in self.policy.denied):
                notes.append("Excluded entries (NEXTCLOUD_DENIED_PATHS) were not checked.")

        if definite_write:
            assessment, content_writable, verified = "write_possible", True, True
        elif share_bits is None and meta["mount_type"] != "":
            assessment, content_writable, verified = "unverified", None, False
        else:
            content_writable = False
            assessment = "read_only_content" if mount_letters else "read_only"
            verified = not open_points
        return {
            "entry": rule.source,
            "is_dir": own.is_dir,
            "permissions": own.permissions,
            "writable_in_nextcloud": bool(letters & WRITE_PERMISSION_LETTERS),
            "assessment": assessment,
            "content_writable": content_writable,
            "verified": verified,
            "mount_type": meta["mount_type"],
            "mount_root": mount_root,
            "share_permissions": share_bits,
            "children_checked": children_checked,
            "children_truncated": children_truncated,
            "children_with_write_permissions": children_flagged[:10],
            "notes": [*definite_write, *notes, *open_points],
            "open_points": open_points,
        }
