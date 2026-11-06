from dataclasses import replace

import pytest

from levuvo_nextcloud_mcp.errors import ConfigurationError
from levuvo_nextcloud_mcp.remote_settings import RemoteSettings


def good() -> RemoteSettings:
    return RemoteSettings(public_url="https://mcp.levuvo.com/mcp", auth_mode="static", static_token="T" * 48)


def test_remote_defaults_require_security():
    assert good().public_host == "mcp.levuvo.com"
    for bad in ("", "short", "a b" * 20):
        with pytest.raises(ConfigurationError):
            replace(good(), static_token=bad)


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.levuvo.com/mcp",
        "https://mcp.levuvo.com/other",
        "https://user:pass@mcp.levuvo.com/mcp",
        "https://mcp.levuvo.com/mcp?token=bad",
        "https://mcp.levuvo.com:123/mcp",
    ],
)
def test_remote_url_must_be_public_https_mcp(url):
    with pytest.raises(ConfigurationError):
        replace(good(), public_url=url)


def test_oauth_needs_idp_and_jwks():
    with pytest.raises(ConfigurationError):
        RemoteSettings(public_url="https://mcp.levuvo.com/mcp", auth_mode="oauth")
    settings = RemoteSettings(
        public_url="https://mcp.levuvo.com/mcp",
        auth_mode="oauth",
        oauth_issuer="https://login.example.com",
        oauth_jwks_url="https://login.example.com/.well-known/jwks.json",
        oauth_audience="https://mcp.levuvo.com/mcp",
    )
    assert settings.oauth_scope == "files:read"


def test_placeholder_rejected():
    with pytest.raises(ConfigurationError):
        replace(good(), static_token="HIER_EIN_ZUFAELLIGES_TOKEN_MIT_32_ZEICHEN")
