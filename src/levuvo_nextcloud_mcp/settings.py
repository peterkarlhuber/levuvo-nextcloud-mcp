"""Configuration loading and validation (environment variables, optional .env file).

Only ``NEXTCLOUD_ALLOWED_PATHS`` and ``NEXTCLOUD_DENIED_PATHS`` configure access; both
use the identical ``dir:``/``file:`` syntax implemented in :mod:`.policy`.
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from .errors import ConfigurationError
from .policy import AccessPolicy, PathRule, parse_rules

logger = logging.getLogger(__name__)

ENV_FILE_VARIABLE = "LEVUVO_MCP_ENV_FILE"
# Placeholder prefixes of the example configuration (EIGENES_/HIER_ are the German
# placeholders of earlier .env.example versions); a value starting with one is rejected.
_PLACEHOLDER_PREFIXES = ("EIGENES_", "HIER_", "CHANGE_ME", "<")


def _is_placeholder(value: str) -> bool:
    return any(value.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES)


@dataclass(frozen=True)
class Settings:
    """Validated Nextcloud settings. ``allowed_paths``/``denied_paths`` are the raw entries."""

    base_url: str
    username: str
    app_password: str = field(repr=False)
    allowed_paths: tuple[str, ...]
    denied_paths: tuple[str, ...] = ()
    user_id: str = ""
    max_file_bytes: int = 25_000_000
    timeout_seconds: float = 20.0
    policy: AccessPolicy = field(init=False, repr=False, compare=False)

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
            raise ConfigurationError(
                "NEXTCLOUD_URL must be an HTTPS address without credentials, e.g. https://storage.levuvo.com."
            )
        if parsed.path not in ("", "/"):
            raise ConfigurationError("NEXTCLOUD_URL must not contain a path (only e.g. https://storage.levuvo.com).")
        for name, value in (("NEXTCLOUD_USERNAME", self.username), ("NEXTCLOUD_USER_ID", self.user_id)):
            if value and ("/" in value or "\\" in value or value != value.strip() or _is_placeholder(value)):
                raise ConfigurationError(f"{name} is invalid.")
        if not self.username:
            raise ConfigurationError("NEXTCLOUD_USERNAME is missing.")
        if not self.app_password or _is_placeholder(self.app_password):
            raise ConfigurationError("NEXTCLOUD_APP_PASSWORD is missing or still contains a placeholder.")
        if not (1 <= self.max_file_bytes <= 100_000_000):
            raise ConfigurationError("NEXTCLOUD_MAX_FILE_BYTES must be between 1 and 100000000.")
        if not (1 <= self.timeout_seconds <= 120):
            raise ConfigurationError("NEXTCLOUD_TIMEOUT_SECONDS must be between 1 and 120.")
        allowed = self._rules(self.allowed_paths, "NEXTCLOUD_ALLOWED_PATHS")
        denied = self._rules(self.denied_paths, "NEXTCLOUD_DENIED_PATHS")
        object.__setattr__(self, "policy", AccessPolicy(allowed, denied))

    @staticmethod
    def _rules(entries: tuple[str, ...], setting: str) -> tuple[PathRule, ...]:
        if isinstance(entries, str):  # defensive: a plain string would be split per character
            raise ConfigurationError(f"{setting} must be passed as a list.")
        return tuple(rule for entry in entries for rule in parse_rules(entry, setting))

    def require_allowed(self, path: object) -> str:
        """Normalise *path* and raise ``AccessDeniedError`` unless the policy releases it."""
        return self.policy.check(path)

    @property
    def dav_user(self) -> str:
        """User ID used in WebDAV paths (defaults to the login name)."""
        return self.user_id or self.username

    @classmethod
    def from_env(cls) -> Settings:
        """Read settings from the process environment (after optionally loading a .env file)."""

        def number(name: str, default: str, kind: type) -> int | float:
            raw = os.getenv(name, default).strip()
            try:
                return kind(raw)
            except ValueError:
                raise ConfigurationError(f"{name} must be a number (current value: '{raw}').") from None

        raw_allowed = os.getenv("NEXTCLOUD_ALLOWED_PATHS", "")
        raw_denied = os.getenv("NEXTCLOUD_DENIED_PATHS", "")
        return cls(
            base_url=os.getenv("NEXTCLOUD_URL", "").strip().rstrip("/"),
            username=os.getenv("NEXTCLOUD_USERNAME", "").strip(),
            user_id=os.getenv("NEXTCLOUD_USER_ID", "").strip(),
            app_password=os.getenv("NEXTCLOUD_APP_PASSWORD", ""),
            allowed_paths=_split(raw_allowed),
            denied_paths=_split(raw_denied),
            max_file_bytes=int(number("NEXTCLOUD_MAX_FILE_BYTES", "25000000", int)),
            timeout_seconds=float(number("NEXTCLOUD_TIMEOUT_SECONDS", "20", float)),
        )


def _split(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def load_env_file() -> Path | None:
    """Load the configuration file, if any, without overriding real environment variables.

    Order:
    1. ``LEVUVO_MCP_ENV_FILE`` (must exist if set),
    2. ``.env`` in the project directory of a source checkout (next to ``pyproject.toml``),
    3. no file: only environment variables are used.
    """
    explicit = os.getenv(ENV_FILE_VARIABLE, "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigurationError(f"{ENV_FILE_VARIABLE} does not point to an existing file: {path}")
    else:
        project_dir = Path(__file__).resolve().parents[2]
        path = project_dir / ".env"
        if not ((project_dir / "pyproject.toml").is_file() and path.is_file()):
            return None
    warn_if_permissive(path)
    load_dotenv(path, override=False)
    return path


def warn_if_permissive(path: Path) -> bool:
    """Warn (stderr) if a secrets file is readable by group/others. Returns True if warned."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    if os.name == "posix" and mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning("The configuration file %s is readable by other users. Recommendation: chmod 600.", path)
        return True
    return False
