import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from levuvo_nextcloud_mcp.jwt_tokens import JWTAccessTokenVerifier


@pytest.fixture
def signer():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private


def token(signer, **overrides):
    claims = {
        'iss': 'https://login.example.com',
        'sub': 'user-42',
        'aud': 'https://mcp.levuvo.com/mcp',
        'scope': 'files:read other:scope',
        'iat': int(time.time()),
        'exp': int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, signer, algorithm='RS256', headers={'kid': 'my-test-key'})


@pytest.mark.asyncio
async def test_jwt_signature_audience_scope_and_expiry(signer):
    verifier = JWTAccessTokenVerifier(
        issuer='https://login.example.com', audience='https://mcp.levuvo.com/mcp',
        jwks_url='https://login.example.com/keys', required_scope='files:read'
    )
    class SigningKey:
        key = signer.public_key()

    verifier.signing_key = lambda kid: SigningKey()
    approved = await verifier.verify(token(signer))
    assert approved is not None and approved.subject == 'user-42'
    assert approved.scopes == ('files:read', 'other:scope')
    assert await verifier.verify(token(signer, aud='elsewhere')) is None
    assert await verifier.verify(token(signer, scope='some:other')) is None
    assert await verifier.verify(token(signer, exp=int(time.time()) - 300)) is None
    assert await verifier.verify(token(signer, iss='https://attacker.example')) is None
    assert await verifier.verify(token(signer, token_use='id')) is None
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert await verifier.verify(token(other_key)) is None
