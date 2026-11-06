"""Validated remote transport settings (read-only MCP).

Do not reuse the Nextcloud password as the client authentication token.
HTTP is always bound to localhost and must be placed behind a TLS reverse proxy.
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
        raise ConfigurationError("Remote URLs must be public HTTPS addresses without credentials.")
    if path is not None and parsed.path != path:
        raise ConfigurationError(f"The remote endpoint must end with {path}.")
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
            raise ConfigurationError("MCP_AUTH_MODE must be static or oauth.")
        if not (1024 <= self.port <= 65535):
            raise ConfigurationError("MCP_HTTP_PORT must be between 1024 and 65535.")
        if self.auth_mode == "static":
            if (
                len(self.static_token) < 32
                or len(self.static_token) > 512
                or self.static_token.startswith("HIER_")
                or any(c.isspace() for c in self.static_token)
            ):
                raise ConfigurationError(
                    "MCP_STATIC_TOKEN must be a random token without whitespace and at least 32 characters long."
                )
        else:
            https_endpoint(self.oauth_issuer)
            https_endpoint(self.oauth_jwks_url)
            if not self.oauth_audience:
                raise ConfigurationError("MCP_OAUTH_AUDIENCE is missing.")
            if not self.oauth_scope or any(x.isspace() for x in self.oauth_scope):
                raise ConfigurationError("MCP_OAUTH_SCOPE must contain a scope.")

    @property
    def public_host(self) -> str:
        return urlsplit(self.public_url).hostname or ""

    @classmethod
    def from_env(cls) -> RemoteSettings:
        try:
            port = int(os.getenv("MCP_HTTP_PORT", "8765"))
        except ValueError as exc:
            raise ConfigurationError("MCP_HTTP_PORT must be a number.") from exc
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
