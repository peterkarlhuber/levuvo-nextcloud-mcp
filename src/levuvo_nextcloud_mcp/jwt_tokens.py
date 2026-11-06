"""OAuth 2.1 resource-server side: verification of RS256 JWT access tokens.

The identity provider (IdP) handles login, consent, PKCE and token issuance; this
server only *verifies* access tokens. ID tokens, unsigned tokens, symmetric (HS*)
tokens and opaque tokens are rejected.

JWKS handling is hardened against abuse: keys are cached, and an unknown ``kid``
triggers at most one JWKS refresh per ``min_refresh_seconds`` for the whole process,
so unauthenticated requests cannot turn the server into a request amplifier.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass

import jwt

logger = logging.getLogger(__name__)

MAX_TOKEN_LENGTH = 8192
ACCEPTED_TYP = frozenset({"", "jwt", "at+jwt", "application/at+jwt"})


@dataclass(frozen=True)
class VerifiedClaims:
    subject: str
    scopes: tuple[str, ...]
    expires_at: int
    audiences: tuple[str, ...]
    client_id: str | None
    issuer: str


class JWTAccessTokenVerifier:
    """Verify signed RS256 OAuth JWT access tokens against an HTTPS JWKS endpoint."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        required_scope: str,
        cache_seconds: float = 300.0,
        min_refresh_seconds: float = 60.0,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.required_scope = required_scope
        self.cache_seconds = cache_seconds
        self.min_refresh_seconds = min_refresh_seconds
        self.jwks = jwt.PyJWKClient(jwks_url, cache_jwk_set=False, cache_keys=False, timeout=5)
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = float("-inf")
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ keys
    def _refresh(self) -> None:
        jwk_set = self.jwks.get_jwk_set(refresh=True)
        keys = {}
        for key in jwk_set.keys:
            if key.key_id and key.key_type == "RSA" and (key.public_key_use in (None, "sig")):
                keys[key.key_id] = key
        self._keys = keys

    def signing_key(self, kid: str) -> jwt.PyJWK | None:
        with self._lock:
            now = time.monotonic()
            stale = now - self._fetched_at > self.cache_seconds
            if (kid not in self._keys or stale) and now - self._fetched_at >= self.min_refresh_seconds:
                self._fetched_at = now  # set before fetching: failures are throttled too
                try:
                    self._refresh()
                except (jwt.PyJWKClientError, OSError) as exc:
                    logger.warning("JWKS-Abruf fehlgeschlagen: %s", type(exc).__name__)
            return self._keys.get(kid)

    # ------------------------------------------------------------------ tokens
    def _check(self, token: str) -> VerifiedClaims | None:
        if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH:
            return None
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            typ = str(header.get("typ", "")).lower()
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not 0 < len(kid) <= 256:
                return None
            if typ not in ACCEPTED_TYP:
                return None
            key = self.signing_key(kid)
            if key is None:
                return None
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                leeway=30,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            return None
        scope_data = claims.get("scope", claims.get("scp", ""))
        if isinstance(scope_data, str):
            scopes = tuple(scope_data.split())
        elif isinstance(scope_data, list) and all(isinstance(item, str) for item in scope_data):
            scopes = tuple(scope_data)
        else:
            return None
        subject = claims.get("sub")
        if self.required_scope not in scopes or not isinstance(subject, str) or not subject:
            return None
        # Some IdPs mark ID tokens explicitly; they must never be accepted as access tokens.
        if claims.get("token_use") == "id" or str(claims.get("typ", "")).lower() in ("id", "id_token"):
            return None
        audience = claims.get("aud")
        audiences = (audience,) if isinstance(audience, str) else tuple(a for a in audience if isinstance(a, str))
        client_id = claims.get("client_id") or claims.get("azp")
        return VerifiedClaims(
            subject=subject,
            scopes=scopes,
            expires_at=int(claims["exp"]),
            audiences=audiences,
            client_id=client_id if isinstance(client_id, str) else None,
            issuer=str(claims["iss"]),
        )

    async def verify(self, token: str) -> VerifiedClaims | None:
        # Key retrieval may block on the network; keep the event loop free.
        return await asyncio.to_thread(self._check, token)
