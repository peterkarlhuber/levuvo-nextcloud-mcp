"""AP4/AP8: OAuth resource-server mode – JWT validation, JWKS abuse protection, metadata."""

from __future__ import annotations

import base64
import json
import time

import httpx
import jwt
import pytest
from conftest import default_tree
from cryptography.hazmat.primitives.asymmetric import rsa

from levuvo_nextcloud_mcp.jwt_tokens import JWTAccessTokenVerifier
from levuvo_nextcloud_mcp.remote_settings import RemoteSettings
from levuvo_nextcloud_mcp.server import build_http_app

pytestmark = pytest.mark.asyncio

ISSUER = "https://login.example.com/"
AUDIENCE = "https://mcp.levuvo.com/mcp"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_set(*pairs: tuple[str, object]) -> dict:
    keys = []
    for kid, private in pairs:
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
        public.update({"kid": kid, "use": "sig", "alg": "RS256"})
        keys.append(public)
    return {"keys": keys}


def make_token(key=KEY, kid: str = "k1", headers: dict | None = None, **overrides: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": "user-42",
        "aud": AUDIENCE,
        "scope": "files:read openid",
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid, **(headers or {})})


class CountingVerifier(JWTAccessTokenVerifier):
    def __init__(self, keys: dict, **kwargs: object) -> None:
        super().__init__(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url="https://login.example.com/jwks",
            required_scope="files:read",
            **kwargs,
        )  # type: ignore[arg-type]
        self.fetches = 0
        self.served = keys
        self.jwks.fetch_data = self._fetch  # type: ignore[method-assign]

    def _fetch(self) -> dict:
        self.fetches += 1
        return self.served


@pytest.fixture
def verifier() -> CountingVerifier:
    return CountingVerifier(jwk_set(("k1", KEY)))


async def test_valid_token_is_accepted_with_claims(verifier) -> None:
    claims = await verifier.verify(make_token(azp="claude-client"))
    assert claims is not None
    assert (claims.subject, claims.client_id, claims.audiences, claims.issuer) == (
        "user-42",
        "claude-client",
        (AUDIENCE,),
        ISSUER,
    )
    assert "files:read" in claims.scopes


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "https://elsewhere.example/mcp"},
        {"iss": "https://attacker.example/"},
        {"iss": ISSUER.rstrip("/")},
        {"exp": int(time.time()) - 300},
        {"nbf": int(time.time()) + 600},
        {"scope": "openid profile"},
        {"scope": None, "scp": ["openid"]},
        {"scope": 42},
        {"sub": None},
        {"sub": ""},
        {"exp": None},
        {"token_use": "id"},
        {"typ": "ID"},
    ],
)
async def test_invalid_claims_are_rejected(verifier, overrides) -> None:
    assert await verifier.verify(make_token(**overrides)) is None


async def test_scope_as_list_and_audience_list(verifier) -> None:
    claims = await verifier.verify(make_token(scope=None, scp=["files:read"], aud=["other", AUDIENCE]))
    assert claims is not None and claims.audiences == ("other", AUDIENCE)


def unsigned(header: dict, claims: dict) -> str:
    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{b64(header)}.{b64(claims)}."


async def test_alg_none_hs256_and_wrong_key_are_rejected(verifier) -> None:
    claims = jwt.decode(make_token(), options={"verify_signature": False})
    assert await verifier.verify(unsigned({"alg": "none", "kid": "k1"}, claims)) is None
    # Algorithm confusion: HS256 signed with the public key bytes as HMAC secret.
    import hashlib
    import hmac

    from cryptography.hazmat.primitives import serialization

    secret = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    signing_input = unsigned({"alg": "HS256", "kid": "k1", "typ": "JWT"}, claims).rstrip(".")
    signature = (
        base64.urlsafe_b64encode(hmac.new(secret, signing_input.encode(), hashlib.sha256).digest())
        .rstrip(b"=")
        .decode()
    )
    assert await verifier.verify(f"{signing_input}.{signature}") is None
    assert await verifier.verify(make_token(key=OTHER_KEY)) is None


@pytest.mark.parametrize("headers", [{"typ": "id+jwt"}, {"typ": "JOSE+JSON"}])
async def test_unexpected_token_types_are_rejected(verifier, headers) -> None:
    assert await verifier.verify(make_token(headers=headers)) is None


@pytest.mark.parametrize("headers", [{"typ": "at+jwt"}, {"typ": "JWT"}])
async def test_access_token_types_are_accepted(verifier, headers) -> None:
    assert await verifier.verify(make_token(headers=headers)) is not None


@pytest.mark.parametrize("token", ["", "x" * 9000, "abc", "a.b.c"])
async def test_garbage_tokens(verifier, token) -> None:
    assert await verifier.verify(token) is None


async def test_missing_kid_is_rejected(verifier) -> None:
    claims = jwt.decode(make_token(), options={"verify_signature": False})
    assert await verifier.verify(jwt.encode(claims, KEY, algorithm="RS256")) is None
    assert verifier.fetches == 0


async def test_unknown_kids_cannot_amplify_jwks_requests(verifier) -> None:
    assert await verifier.verify(make_token()) is not None
    assert verifier.fetches == 1
    for i in range(25):
        assert await verifier.verify(make_token(kid=f"attacker-{i}")) is None
    assert verifier.fetches == 1  # throttled: at most one refresh per min_refresh_seconds
    assert await verifier.verify(make_token()) is not None
    assert verifier.fetches == 1  # cached key reused


async def test_key_rotation_is_picked_up_after_refresh_interval() -> None:
    v = CountingVerifier(jwk_set(("k1", KEY)), min_refresh_seconds=0.0)
    assert await v.verify(make_token()) is not None
    v.served = jwk_set(("k2", OTHER_KEY))
    assert await v.verify(make_token(key=OTHER_KEY, kid="k2")) is not None
    assert v.fetches == 2


async def test_jwks_outage_fails_closed(verifier) -> None:
    def down() -> dict:
        raise jwt.PyJWKClientError("down")

    verifier.jwks.fetch_data = down  # type: ignore[method-assign]
    assert await verifier.verify(make_token()) is None


# --------------------------------------------------------------------------- OAuth HTTP app
@pytest.fixture
def oauth_app(make_settings, monkeypatch):
    keys = jwk_set(("k1", KEY))
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: keys)
    settings = RemoteSettings(
        public_url=AUDIENCE,
        auth_mode="oauth",
        oauth_issuer=ISSUER,
        oauth_jwks_url="https://login.example.com/jwks",
        oauth_audience=AUDIENCE,
    )
    return build_http_app(make_settings("dir:05_Projekte/Offen"), settings, transport=default_tree().transport())


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}},
}
ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def call(app, **kwargs):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
        ) as client:
            return await client.request(**kwargs)


async def test_protected_resource_metadata(oauth_app) -> None:
    response = await call(oauth_app, method="GET", url="/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    metadata = response.json()
    assert metadata["resource"] == AUDIENCE
    assert metadata["authorization_servers"] == [ISSUER]
    assert "files:read" in metadata.get("scopes_supported", [])


async def test_missing_token_gets_resource_metadata_challenge(oauth_app) -> None:
    response = await call(oauth_app, method="POST", url="/mcp", headers=ACCEPT, json=INIT)
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]


@pytest.mark.parametrize(
    "token, status",
    [
        (lambda: make_token(), 200),
        (lambda: make_token(aud="https://elsewhere.example/mcp"), 401),
        (lambda: make_token(scope="openid"), 401),
        (lambda: make_token(key=OTHER_KEY), 401),
    ],
)
async def test_token_validation_through_http(oauth_app, token, status) -> None:
    response = await call(
        oauth_app, method="POST", url="/mcp", headers={**ACCEPT, "Authorization": f"Bearer {token()}"}, json=INIT
    )
    assert response.status_code == status


async def test_custom_audience_disables_sdk_resource_check_but_verifier_enforces_aud(
    make_settings, monkeypatch
) -> None:
    from levuvo_nextcloud_mcp.server import _oauth_options

    remote = RemoteSettings(
        public_url=AUDIENCE,
        auth_mode="oauth",
        oauth_issuer=ISSUER,
        oauth_jwks_url="https://login.example.com/jwks",
        oauth_audience="api://levuvo",
    )
    assert _oauth_options(remote)["auth"].validate_token_resource is False
    same = RemoteSettings(
        public_url=AUDIENCE,
        auth_mode="oauth",
        oauth_issuer=ISSUER,
        oauth_jwks_url="https://login.example.com/jwks",
        oauth_audience=AUDIENCE,
    )
    assert _oauth_options(same)["auth"].validate_token_resource is True
