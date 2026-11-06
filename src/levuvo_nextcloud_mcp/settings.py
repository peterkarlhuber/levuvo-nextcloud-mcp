"""Configuration and fail-closed allow/deny path access policy."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Invalid or missing server configuration."""


def validate_path(path: str, *, allow_empty: bool = False) -> str:
    """Normalize relative WebDAV paths without changing their logical directory level."""
    if not isinstance(path, str):
        raise ValueError("Der Dateipfad muss eine Zeichenkette sein.")
    if not path:
        if allow_empty:
            return ""
        raise ValueError("Ein Dateipfad ist erforderlich.")
    if path.startswith("/") or path.startswith("\\") or "\\" in path:
        raise ValueError("Nur relative Nextcloud-Pfade sind erlaubt.")
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise ValueError("Der Pfad enthält nicht erlaubte Steuerzeichen.")
    if path.endswith("//"):
        raise ValueError("Mehrfache abschließende Schrägstriche sind nicht erlaubt.")
    path = path.removesuffix("/")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Leere Segmente und . oder .. sind nicht erlaubt.")
    return "/".join(parts)


@dataclass(frozen=True)
class AllowedPath:
    path: str
    kind: str  # 'auto' (detect via WebDAV), 'dir', or 'file'


def parse_allowed_path(value: str) -> AllowedPath:
    """Unprefixed paths auto-detect file/folder; prefixes force a strict type."""
    kind = "auto"
    path = value.strip()
    for prefix, candidate in (("file:", "file"), ("dir:", "dir")):
        if path.startswith(prefix):
            kind = candidate
            path = path[len(prefix):]
            break
    if not path or path != path.strip():
        raise ConfigurationError("NEXTCLOUD_ALLOWED_PATHS enthält einen leeren oder ungültigen Pfad.")
    return AllowedPath(validate_path(path), kind)


def same_or_child(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent + "/")


@dataclass(frozen=True)
class Settings:
    base_url: str
    username: str
    app_password: str
    allowed_paths: tuple[str, ...]
    max_file_bytes: int = 8_000_000
    timeout_seconds: float = 20.0
    denied_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError("NEXTCLOUD_URL muss eine gültige HTTPS-Adresse ohne Zugangsdaten sein.")
        if parsed.path not in ("", "/"):
            raise ConfigurationError("NEXTCLOUD_URL darf keinen Pfad enthalten (nur https://storage.levuvo.com).")
        if not self.username or "/" in self.username or "\\" in self.username:
            raise ConfigurationError("NEXTCLOUD_USERNAME ist ungültig.")
        if not self.app_password or self.app_password.startswith("EIGENES_NEXTCLOUD_APP_PASSWORT") or self.app_password.startswith("HIER_"):
            raise ConfigurationError("NEXTCLOUD_APP_PASSWORD fehlt oder enthält einen Platzhalter.")
        if not self.allowed_paths:
            raise ConfigurationError("Mindestens eine erlaubte Datei oder ein Ordner ist erforderlich (fail closed).")
        parsed_allowed = [parse_allowed_path(x) for x in self.allowed_paths]
        if len({r.path for r in parsed_allowed}) != len(parsed_allowed):
            raise ConfigurationError("Der gleiche erlaubte Pfad wurde mehrfach angegeben.")
        for denied in self.denied_paths:
            if denied != validate_path(denied):
                raise ConfigurationError("NEXTCLOUD_DENIED_PATHS enthält einen ungültigen Pfad.")
        if not (1 <= self.max_file_bytes <= 30_000_000):
            raise ConfigurationError("NEXTCLOUD_MAX_FILE_BYTES muss zwischen 1 und 30000000 liegen.")
        if not (1 <= self.timeout_seconds <= 120):
            raise ConfigurationError("NEXTCLOUD_TIMEOUT_SECONDS muss zwischen 1 und 120 liegen.")

    @property
    def allowed_specs(self) -> tuple[AllowedPath, ...]:
        return tuple(parse_allowed_path(entry) for entry in self.allowed_paths)

    @classmethod
    def from_env(cls) -> Settings:
        # Resolve .env relative to project installation, not Claude Code working dir.
        project_dir = Path(__file__).resolve().parents[2]
        load_dotenv(project_dir / ".env", override=False)
        raw_allowed = os.getenv("NEXTCLOUD_ALLOWED_PATHS", "")
        raw_denied = os.getenv("NEXTCLOUD_DENIED_PATHS", "")
        allowed = tuple(x.strip() for x in raw_allowed.split(",") if x.strip())
        denied = tuple(dict.fromkeys(validate_path(x.strip()) for x in raw_denied.split(",") if x.strip()))
        try:
            max_size = int(os.getenv("NEXTCLOUD_MAX_FILE_BYTES", "8000000"))
            timeout = float(os.getenv("NEXTCLOUD_TIMEOUT_SECONDS", "20"))
        except ValueError as exc:
            raise ConfigurationError("Die Größen- und Timeout-Angaben müssen Zahlen sein.") from exc
        return cls(
            base_url=os.getenv("NEXTCLOUD_URL", "").rstrip("/"),
            username=os.getenv("NEXTCLOUD_USERNAME", "").strip(),
            app_password=os.getenv("NEXTCLOUD_APP_PASSWORD", ""),
            allowed_paths=allowed,
            denied_paths=denied,
            max_file_bytes=max_size,
            timeout_seconds=timeout,
        )

    def is_denied(self, path: str) -> bool:
        normalized = validate_path(path)
        return any(same_or_child(normalized, denied) for denied in self.denied_paths)

    def matched_allowed_paths(self, path: str) -> tuple[AllowedPath, ...]:
        """Syntactic policy only: explicit files never authorize descendants."""
        normalized = validate_path(path)
        if self.is_denied(normalized):
            return ()
        return tuple(
            allowed for allowed in self.allowed_specs
            if normalized == allowed.path or (allowed.kind != "file" and same_or_child(normalized, allowed.path))
        )

    def require_allowed(self, path: str) -> str:
        normalized = validate_path(path)
        if not self.matched_allowed_paths(normalized):
            raise PermissionError("Der Pfad ist nicht für den MCP-Agenten freigegeben.")
        return normalized
