"""Validated remote transport settings (read-only MCP).

Do not reuse the Nextcloud password as the client authentication token.
HTTP is always bound to localhost and must be placed behind TLS reverse proxy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .errors import ConfigurationError


def https_endpoint(value: str, *, path: str | None = None) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise ConfigurationError("Remote-URLs müssen öffentliche HTTPS-Adressen ohne Zugangsdaten sein.")
    if path is not None and parsed.path != path:
        raise ConfigurationError(f"Remote-Endpunkt muss auf {path} enden.")
    return value


@dataclass(frozen=True)
class RemoteSettings:
    public_url: str
    auth_mode: str
    port: int = 8765
    static_token: str = field(default="", repr=False)
    oauth_issuer: str = ""
    oauth_jwks_url: str = ""
    oauth_audience: str = ""
    oauth_scope: str = "files:read"

    def __post_init__(self) -> None:
        https_endpoint(self.public_url, path="/mcp")
        if self.auth_mode not in ("static", "oauth"):
            raise ConfigurationError("MCP_AUTH_MODE muss static oder oauth sein.")
        if not (1024 <= self.port <= 65535):
            raise ConfigurationError("MCP_HTTP_PORT muss zwischen 1024 und 65535 liegen.")
        if self.auth_mode == "static":
            if (
                len(self.static_token) < 32
                or len(self.static_token) > 512
                or self.static_token.startswith("HIER_")
                or any(c.isspace() for c in self.static_token)
            ):
                raise ConfigurationError(
                    "MCP_STATIC_TOKEN muss ein zufälliges Token ohne Leerzeichen mit >=32 Zeichen sein."
                )
        else:
            https_endpoint(self.oauth_issuer)
            https_endpoint(self.oauth_jwks_url)
            if not self.oauth_audience:
                raise ConfigurationError("MCP_OAUTH_AUDIENCE fehlt.")
            if not self.oauth_scope or any(x.isspace() for x in self.oauth_scope):
                raise ConfigurationError("MCP_OAUTH_SCOPE muss einen Scope enthalten.")

    @property
    def public_host(self) -> str:
        return urlsplit(self.public_url).hostname or ""

    @classmethod
    def from_env(cls) -> RemoteSettings:
        try:
            port = int(os.getenv("MCP_HTTP_PORT", "8765"))
        except ValueError as exc:
            raise ConfigurationError("MCP_HTTP_PORT muss eine Zahl sein.") from exc
        return cls(
            public_url=os.getenv("MCP_PUBLIC_URL", "https://mcp.levuvo.com/mcp").strip(),
            auth_mode=os.getenv("MCP_AUTH_MODE", "static").strip().lower(),
            port=port,
            static_token=os.getenv("MCP_STATIC_TOKEN", ""),
            oauth_issuer=os.getenv("MCP_OAUTH_ISSUER", "").strip(),
            oauth_jwks_url=os.getenv("MCP_OAUTH_JWKS_URL", "").strip(),
            oauth_audience=os.getenv("MCP_OAUTH_AUDIENCE", "").strip(),
            oauth_scope=os.getenv("MCP_OAUTH_SCOPE", "files:read").strip(),
        )
