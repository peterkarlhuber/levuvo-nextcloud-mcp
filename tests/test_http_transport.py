"""AP8: Streamable HTTP app – static bearer auth, host validation, limits and a real E2E session."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx
import httpx2
import pytest
import uvicorn
from conftest import default_tree
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from levuvo_nextcloud_mcp.remote_settings import RemoteSettings
from levuvo_nextcloud_mcp.server import build_http_app

pytestmark = pytest.mark.asyncio

TOKEN = "T" * 24 + "-random-test-token-" + "x" * 10
ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}},
}


def remote(**overrides: object) -> RemoteSettings:
    values: dict[str, object] = {
        "public_url": "https://mcp.levuvo.com/mcp",
        "auth_mode": "static",
        "static_token": TOKEN,
    }
    values.update(overrides)
    return RemoteSettings(**values)  # type: ignore[arg-type]


@contextlib.asynccontextmanager
async def asgi_client(app, base_url: str = "http://127.0.0.1:8765"):
    inner = getattr(app, "app", app)
    async with inner.router.lifespan_context(inner):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url) as client:
            yield client


@pytest.fixture
def app(make_settings):
    return build_http_app(make_settings("dir:05_Projekte/Offen"), remote(), transport=default_tree().transport())


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "Basic " + TOKEN},
        {"Authorization": TOKEN},
        {"Authorization": "Bearer " + TOKEN + "x"},
        {"Authorization": "Bearer " + TOKEN[:-1]},
        {"Authorization": "Bearer " + "A" * 700},
    ],
)
@pytest.mark.parametrize("path", ["/mcp", "/", "/.well-known/oauth-protected-resource/mcp", "/anything"])
async def test_every_route_requires_the_static_token(app, headers, path) -> None:
    async with asgi_client(app) as client:
        for method in ("GET", "POST", "DELETE", "OPTIONS"):
            response = await client.request(
                method, path, headers={**ACCEPT, **headers}, json=INIT if method == "POST" else None
            )
            assert response.status_code == 401, (method, path, headers)
            assert response.headers["www-authenticate"].startswith("Bearer")
            assert TOKEN not in response.text


async def test_duplicate_authorization_headers_are_rejected(app) -> None:
    async with asgi_client(app) as client:
        response = await client.post(
            "/mcp",
            headers=[("Authorization", "Bearer " + TOKEN), ("Authorization", "Bearer " + TOKEN), *ACCEPT.items()],
            json=INIT,
        )
    assert response.status_code == 401


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
async def test_valid_token_initialises_session(app, scheme) -> None:
    async with asgi_client(app) as client:
        response = await client.post("/mcp", headers={**ACCEPT, "Authorization": f"{scheme} {TOKEN}"}, json=INIT)
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["serverInfo"]["name"] == "Levuvo Nextcloud Read-Only"


@pytest.mark.parametrize("host", ["evil.example", "mcp.levuvo.com.evil.example", "10.0.0.5:8765"])
async def test_unknown_host_header_is_rejected_even_with_token(app, host, caplog) -> None:
    async with asgi_client(app) as client:
        with caplog.at_level(logging.WARNING):
            response = await client.post(
                "/mcp", headers={**ACCEPT, "Authorization": f"Bearer {TOKEN}", "Host": host}, json=INIT
            )
    assert response.status_code == 421
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("host", ["mcp.levuvo.com", "127.0.0.1:8765", "localhost:8765"])
async def test_known_hosts_are_accepted(app, host) -> None:
    async with asgi_client(app) as client:
        response = await client.post(
            "/mcp", headers={**ACCEPT, "Authorization": f"Bearer {TOKEN}", "Host": host}, json=INIT
        )
    assert response.status_code == 200


async def test_browser_origin_is_rejected(app) -> None:
    async with asgi_client(app) as client:
        response = await client.post(
            "/mcp", headers={**ACCEPT, "Authorization": f"Bearer {TOKEN}", "Origin": "https://evil.example"}, json=INIT
        )
    assert response.status_code in (400, 403)


async def test_request_body_limit(app) -> None:
    async with asgi_client(app) as client:
        response = await client.post(
            "/mcp", headers={**ACCEPT, "Authorization": f"Bearer {TOKEN}"}, content=b'{"a":"' + b"x" * 200_000 + b'"}'
        )
    assert response.status_code == 413


async def test_websocket_scope_is_forbidden() -> None:
    from levuvo_nextcloud_mcp.static_bearer import StaticBearerAuth

    sent = []

    async def downstream(scope, receive, send):
        raise AssertionError("must not be reached")

    async def send(message):
        sent.append(message)

    await StaticBearerAuth(downstream, TOKEN)({"type": "websocket", "headers": []}, None, send)
    assert sent[0]["status"] == 403


# --------------------------------------------------------------------------- real server E2E
@contextlib.asynccontextmanager
async def running_server(app):
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", access_log=False, lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await task


async def test_end_to_end_streamable_http_with_mcp_client(app) -> None:
    async with running_server(app) as url:
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}) as http:
            async with Client(streamable_http_client(url, http_client=http)) as client:
                tools = await client.list_tools()
                listing = await client.call_tool("list_files", {"path": "05_Projekte/Offen"})
                read = await client.call_tool("read_file", {"path": "05_Projekte/Offen/Plan.md"})
                denied = await client.call_tool("read_file", {"path": "08_Privat/Tagebuch.txt"})
        async with httpx.AsyncClient() as anonymous:
            unauthorised = await anonymous.post(url, headers=ACCEPT, json=INIT)
    assert {tool.name for tool in tools.tools} == {"list_files", "get_file_info", "search_files", "read_file"}
    assert "Kunde A" in [item["name"] for item in listing.structured_content["items"]]
    assert read.structured_content["text"].startswith("# Freigegeben")
    assert denied.is_error and "nicht für den MCP-Agenten freigegeben" in denied.content[0].text
    assert unauthorised.status_code == 401
