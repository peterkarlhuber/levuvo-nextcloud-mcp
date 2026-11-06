"""Central, fail-closed access policy for Nextcloud paths.

All path decisions of the server go through this module:

* :func:`normalize_path` turns a client- or config-supplied path into the canonical
  form that is sent to Nextcloud (Unicode NFC, no traversal, no encoded sequences).
* :class:`AccessPolicy` decides whether a canonical path is released.

Design rules
------------
* **Allow is exact.** A path is only released if it equals an allowed entry or lies
  below an allowed folder, compared byte-exact after NFC normalisation. Normalisation
  can therefore never widen access.
* **Deny is conservative.** Denied entries are compared with a *folded* key
  (NFKC + casefold + trailing dots/spaces removed per segment). Different spellings of a
  denied path (upper/lower case, NFD vs. NFC, compatibility characters) are all blocked,
  even if the Nextcloud backend would treat them as different names. Over-blocking is
  accepted; under-blocking is not.
* **Deny always wins** and always covers the complete subtree of the denied entry.
* Denied and not-released paths produce the same error message, so the client cannot
  probe which denied entries exist.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from .errors import AccessDeniedError, ConfigurationError, InvalidArgumentError

MAX_PATH_LENGTH = 1024
MAX_SEGMENT_LENGTH = 255
# Unicode categories that never belong into a file path we accept: control, format
# (e.g. bidi overrides, zero-width characters), surrogates and private use.
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co"})
_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_PREFIX = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):")
_KNOWN_PREFIXES = ("dir", "file")

ACCESS_DENIED_MESSAGE = "The path is not released for the MCP agent."

Kind = Literal["auto", "dir", "file"]


def normalize_path(path: object, *, allow_empty: bool = False) -> str:
    """Return the canonical relative path or raise :class:`InvalidArgumentError`.

    The returned value is NFC-normalised, has no leading/trailing slash and contains no
    empty, ``.`` or ``..`` segment. Percent-encoded sequences are rejected instead of
    decoded, so a path is interpreted exactly once (by Nextcloud, after our own
    per-segment encoding).
    """
    if not isinstance(path, str):
        raise InvalidArgumentError("The path must be a string.")
    if not path:
        if allow_empty:
            return ""
        raise InvalidArgumentError("A path is required.")
    if len(path) > MAX_PATH_LENGTH:
        raise InvalidArgumentError(f"The path is too long (maximum {MAX_PATH_LENGTH} characters).")
    path = unicodedata.normalize("NFC", path)
    if any(unicodedata.category(char) in _FORBIDDEN_CATEGORIES for char in path):
        raise InvalidArgumentError("The path contains control or invisible formatting characters.")
    if path.startswith("/") or "\\" in path:
        raise InvalidArgumentError("Only relative Nextcloud paths with '/' as separator are allowed.")
    if _PERCENT_ESCAPE.search(path):
        raise InvalidArgumentError(
            "The path contains URL-encoded characters (e.g. %20). Please specify the path without encoding."
        )
    if path.endswith("/"):
        path = path[:-1]
    parts = path.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise InvalidArgumentError("Empty path segments as well as '.' and '..' are not allowed.")
        if len(part) > MAX_SEGMENT_LENGTH:
            raise InvalidArgumentError(f"A path segment is longer than {MAX_SEGMENT_LENGTH} characters.")
    return "/".join(parts)


def fold_key(path: str) -> str:
    """Conservative comparison key for deny checks (see module docstring)."""
    if not path:
        return ""
    return "/".join(unicodedata.normalize("NFKC", segment).casefold().rstrip(" .") for segment in path.split("/"))


def _same_or_below(key: str, parent: str) -> bool:
    return key == parent or key.startswith(parent + "/")


@dataclass(frozen=True)
class PathRule:
    """One entry of NEXTCLOUD_ALLOWED_PATHS or NEXTCLOUD_DENIED_PATHS."""

    path: str
    kind: Kind
    key: str
    source: str

    def describe(self) -> str:
        return self.source


def parse_rule(raw: str, setting: str) -> PathRule:
    """Parse ``dir:path``, ``file:path`` or ``path`` with identical rules for both settings."""
    value = raw.strip()
    kind: Kind = "auto"
    match = _PREFIX.match(value)
    if match:
        prefix = match.group(1)
        if prefix in _KNOWN_PREFIXES:
            kind = prefix  # type: ignore[assignment]
            value = value[len(prefix) + 1 :]
            inner = _PREFIX.match(value)
            if inner and inner.group(1).lower() in _KNOWN_PREFIXES:
                raise ConfigurationError(f"{setting}: duplicate prefix in '{raw}'.")
        else:
            raise ConfigurationError(
                f"{setting}: unknown prefix '{prefix}:' in '{raw}'. Only 'dir:' and 'file:' "
                "(lower case) are allowed. Always specify paths whose first segment contains a colon "
                "with 'dir:' or 'file:'."
            )
    if not value or value != value.strip():
        raise ConfigurationError(f"{setting}: empty path or leading/trailing whitespace in '{raw}'.")
    try:
        path = normalize_path(value)
    except InvalidArgumentError as exc:
        raise ConfigurationError(f"{setting}: invalid path '{raw}': {exc}") from None
    return PathRule(path=path, kind=kind, key=fold_key(path), source=raw.strip())


def parse_rules(raw: str, setting: str) -> tuple[PathRule, ...]:
    """Split a comma-separated setting. Empty entries (e.g. a trailing comma) are ignored."""
    return tuple(parse_rule(item, setting) for item in raw.split(",") if item.strip())


class AccessPolicy:
    """Allowlist/denylist decision logic. Immutable after construction."""

    def __init__(self, allowed: tuple[PathRule, ...], denied: tuple[PathRule, ...] = ()) -> None:
        if not allowed:
            raise ConfigurationError(
                "NEXTCLOUD_ALLOWED_PATHS is empty: at least one allowed file or folder is required (fail closed)."
            )
        self._check_duplicates(allowed, "NEXTCLOUD_ALLOWED_PATHS")
        self._check_duplicates(denied, "NEXTCLOUD_DENIED_PATHS")
        for rule in allowed:
            for other in allowed:
                if other is not rule and other.kind == "file" and rule.path.startswith(other.path + "/"):
                    raise ConfigurationError(
                        f"NEXTCLOUD_ALLOWED_PATHS: '{rule.source}' lies below the single file '{other.source}'."
                    )
            for deny in denied:
                if _same_or_below(rule.key, deny.key):
                    raise ConfigurationError(
                        f"Contradictory configuration: the share '{rule.source}' is completely blocked by the "
                        f"exclusion '{deny.source}'. Please remove one of the two entries."
                    )
        for deny in denied:
            if not any(
                _same_or_below(deny.key, rule.key) and (rule.kind != "file" or deny.key == rule.key) for rule in allowed
            ):
                raise ConfigurationError(
                    f"NEXTCLOUD_DENIED_PATHS: '{deny.source}' does not lie below any share from "
                    "NEXTCLOUD_ALLOWED_PATHS and would have no effect (typo?)."
                )
        self.allowed = allowed
        self.denied = denied

    @staticmethod
    def _check_duplicates(rules: tuple[PathRule, ...], setting: str) -> None:
        seen: dict[str, PathRule] = {}
        for rule in rules:
            if rule.key in seen:
                raise ConfigurationError(
                    f"{setting}: '{rule.source}' and '{seen[rule.key].source}' refer to the same path."
                )
            seen[rule.key] = rule

    def is_denied(self, path: str) -> bool:
        """True if *path* (already canonical) is a denied entry or lies below one."""
        key = fold_key(path)
        return any(_same_or_below(key, rule.key) for rule in self.denied)

    def denied_rule_for(self, path: str) -> PathRule | None:
        key = fold_key(path)
        return next((rule for rule in self.denied if rule.key == key), None)

    def matching_allows(self, path: str) -> tuple[PathRule, ...]:
        """Allowed entries that release *path* (syntactically; folder types are verified later)."""
        if not path or self.is_denied(path):
            return ()
        return tuple(
            rule
            for rule in self.allowed
            if path == rule.path or (rule.kind != "file" and path.startswith(rule.path + "/"))
        )

    def check(self, path: object) -> str:
        """Normalise *path* and raise :class:`AccessDeniedError` unless it is released."""
        normalized = normalize_path(path)
        if not self.matching_allows(normalized):
            raise AccessDeniedError(ACCESS_DENIED_MESSAGE)
        return normalized

    def visible_roots(self) -> tuple[PathRule, ...]:
        return self.allowed
