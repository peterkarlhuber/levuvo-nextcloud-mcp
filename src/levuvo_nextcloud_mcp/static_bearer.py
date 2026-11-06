"""HTTP ASGI guard for a fixed bearer credential.

Static credentials are a small-team interim option, *not* OAuth. The token is
checked before the MCP app handles any HTTP request, including discovery.
"""
from __future__ import annotations

import hmac


class StaticBearerAuth:
    def __init__(self, app, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("Weak or missing bearer token")
        self.app = app
        self.secret = secret.encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            return await self._reject(send, 403, b"Forbidden")
        headers = [(k.lower(), v) for k, v in scope.get("headers", [])]
        auth_headers = [v for k, v in headers if k == b"authorization"]
        if len(auth_headers) != 1:
            return await self._reject(send, 401, b"Unauthorized", challenge=True)
        supplied = auth_headers[0]
        if not supplied.startswith(b"Bearer ") or len(supplied) > 600:
            return await self._reject(send, 401, b"Unauthorized", challenge=True)
        token = supplied[7:]
        if not hmac.compare_digest(token, self.secret):
            return await self._reject(send, 401, b"Unauthorized", challenge=True)
        return await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send, status: int, message: bytes, *, challenge: bool = False):
        headers = [(b"content-type", b"text/plain; charset=utf-8"),
                   (b"cache-control", b"no-store")]
        if challenge:
            headers.append((b"www-authenticate", b'Bearer realm="levuvo-nextcloud-mcp"'))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": message})
