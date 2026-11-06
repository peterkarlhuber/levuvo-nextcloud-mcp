"""ASGI guard for a fixed bearer credential (``MCP_AUTH_MODE=static``).

Static credentials are an interim option for a small, trusted setup (e.g. Claude Code
with a ``--header``), *not* OAuth. The token is checked before the MCP app handles any
HTTP request, including discovery routes.
"""

from __future__ import annotations

import hmac

MAX_AUTHORIZATION_LENGTH = 600


class StaticBearerAuth:
    def __init__(self, app, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("Weak or missing bearer token")
        self.app = app
        self.secret = secret.encode("utf-8")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            return await self._reject(send, 403, b"Forbidden")
        values = [value for key, value in scope.get("headers", []) if key.lower() == b"authorization"]
        if len(values) != 1 or len(values[0]) > MAX_AUTHORIZATION_LENGTH:
            return await self._reject(send, 401, b"Unauthorized", challenge=True)
        scheme, _, token = values[0].partition(b" ")
        if scheme.lower() != b"bearer" or not hmac.compare_digest(token.strip(), self.secret):
            return await self._reject(send, 401, b"Unauthorized", challenge=True)
        return await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send, status: int, message: bytes, *, challenge: bool = False) -> None:
        headers = [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"cache-control", b"no-store"),
        ]
        if challenge:
            headers.append((b"www-authenticate", b'Bearer realm="levuvo-nextcloud-mcp"'))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": message})
