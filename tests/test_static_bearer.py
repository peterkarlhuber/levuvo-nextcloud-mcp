import httpx
import pytest

from levuvo_nextcloud_mcp.static_bearer import StaticBearerAuth

SECRET = "some-very-long-random-test-value-not-real-123"


async def downstream(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    else:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"OK"})


@pytest.mark.asyncio
async def test_auth_is_enforced_before_downstream():
    app = StaticBearerAuth(downstream, SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        for method in (client.get, client.post):
            for h in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic " + SECRET}):
                r = await method("/mcp", headers=h)
                assert r.status_code == 401
                assert r.headers["www-authenticate"].startswith("Bearer")
                assert SECRET not in r.text
            r = await method("/mcp", headers={"Authorization": "Bearer " + SECRET})
            assert r.status_code == 200 and r.text == "OK"


@pytest.mark.asyncio
async def test_duplicate_auth_headers_rejected():
    app = StaticBearerAuth(downstream, SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        r = await client.get(
            "/mcp", headers=[("Authorization", "Bearer " + SECRET), ("Authorization", "Bearer " + SECRET)]
        )
        assert r.status_code == 401
