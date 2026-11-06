"""OIDC/JWT bearer verification for OAuth resource-server mode.

The identity provider handles login, consent, access token issuance and PKCE.
Never accept unsigned tokens or ID tokens as access tokens.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import jwt


@dataclass(frozen=True)
class VerifiedClaims:
    subject: str
    scopes: tuple[str, ...]
    expires_at: int


class JWTAccessTokenVerifier:
    """Verify signed RS256 OAuth JWTs using an HTTPS JWKS endpoint.

    This intentionally supports *RS256 JWT access tokens* only. Opaque tokens,
    other JWT signing algorithms and ID-token-only providers are not supported.
    """

    def __init__(self, *, issuer: str, audience: str, jwks_url: str, required_scope: str):
        self.issuer = issuer
        self.audience = audience
        self.required_scope = required_scope
        self.jwks = jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300,
                                     timeout=5, cache_keys=False)

    def _check(self, token: str) -> VerifiedClaims | None:
        try:
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, key.key, algorithms=["RS256"], issuer=self.issuer,
                audience=self.audience, leeway=30,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            scope_data = claims.get("scope", claims.get("scp", ""))
            if isinstance(scope_data, str):
                scopes = tuple(scope_data.split())
            elif isinstance(scope_data, list) and all(isinstance(s, str) for s in scope_data):
                scopes = tuple(scope_data)
            else:
                return None
            if self.required_scope not in scopes or not isinstance(claims.get("sub"), str):
                return None
            # Some providers issue ID tokens, which must not be accepted here.
            if claims.get("token_use") == "id" or claims.get("typ") == "id":
                return None
            return VerifiedClaims(claims["sub"], scopes, int(claims["exp"]))
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OSError):
            return None

    async def verify(self, token: str) -> VerifiedClaims | None:
        # PyJWKClient may fetch or refresh keys over the network.
        return await asyncio.to_thread(self._check, token)
