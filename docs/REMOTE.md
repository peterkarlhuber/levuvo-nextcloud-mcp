# Remote operation

Remote is optional. Local operation with Claude Code (`stdio`) needs nothing from this page.

> A publicly reachable endpoint is **not production-ready** until the checklist in [SECURITY.md](../SECURITY.md#checklist-before-any-public-operation) has been worked through and tests with the real client have passed. None of the routes described below has been tried in practice with this server so far.

## What the server does in HTTP mode

- Start: `levuvo-nextcloud-mcp --transport http`
- Listens **only on `127.0.0.1:MCP_HTTP_PORT`** (default 8765). TLS and public reachability are handled by a reverse proxy or tunnel.
- Streamable HTTP, stateless, JSON responses, endpoint `/mcp`.
- Host header allowlist: host from `MCP_PUBLIC_URL` plus `localhost`/`127.0.0.1`; otherwise HTTP 421. Browser origins are not permitted.
- Request body max. 128 KiB, max. 32 concurrent connections, no server header, no access log.
- Authentication via `MCP_AUTH_MODE`:
  - `static`: fixed bearer token (`MCP_STATIC_TOKEN`, ≥ 32 characters); every route without a valid token returns 401.
  - `oauth`: verification of RS256 JWT access tokens from an external identity provider; Protected Resource Metadata at `/.well-known/oauth-protected-resource/mcp`. A login/OAuth server of its own is **not** included.

The Hetzner Storage Share cannot host this Python service; it needs a machine of its own.

## Testing locally (without internet)

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'   # generate a token, put it in .env as MCP_STATIC_TOKEN
.venv/bin/levuvo-nextcloud-mcp --transport http --check-config  # also checks the remote settings
.venv/bin/levuvo-nextcloud-mcp --transport http
```

In a second terminal:

```bash
curl -i http://127.0.0.1:8765/mcp
# expected: 401 Unauthorized

read -rs TOKEN   # paste the token; it does not end up in the shell history
curl -i http://127.0.0.1:8765/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
# expected: JSON response with serverInfo "Levuvo Nextcloud Read-Only"

curl -i http://127.0.0.1:8765/mcp -H "Authorization: Bearer $TOKEN" -H "Host: other.example"
# expected: 421 Invalid Host header
```

Alternatively, use the official MCP Inspector as the client.

## Options without mandatory hosting costs

Constraints: no mandatory hosting costs, no Cloudflare, no Docker requirement, the local Mac has priority, and remote must not be a prerequisite for local operation.

| Option | Costs | Reachability | Assessment |
|---|---|---|---|
| 1. Local only (`stdio`) | none | only Claude Code on the Mac | **Default and recommended.** No open port. |
| 2. Own existing Linux server | no additional costs if the server is running anyway | permanent | Clean solution for later. Examples in `deploy/`. |
| 3. Tunnel without Cloudflare, e.g. Tailscale Funnel | free plan available | only while the Mac is running and online | External service in the data path. Not tested. |
| 4. Router port forwarding + dynamic DNS | none | while the Mac is running | **Not recommended**: the home network becomes directly attackable; certificates and updates are your responsibility. |

### Option 2: own Linux server (Caddy + systemd)

1. Point a DNS record (A/AAAA) for the desired domain to the server. `mcp.levuvo.com` is only a placeholder in the examples; this project does not set up DNS.
2. Put the project in `/opt/levuvo-nextcloud-mcp` and create the venv as described in the README.
3. Put the configuration in `/etc/levuvo-nextcloud-mcp/levuvo.env` (owned by the service user, `chmod 600`) and set `MCP_PUBLIC_URL` to the real domain.
4. Adapt and install `deploy/levuvo-nextcloud-mcp.service.example`; check `systemd-analyze security levuvo-nextcloud-mcp`.
5. Adapt `deploy/Caddyfile.example`; open ports 80/443, but **not** port 8765.
6. Check from outside: 401 without a token, 421 for a foreign host (with a valid token), paths outside the released entries rejected.
7. Only then connect a client.

### Option 3: Tailscale Funnel (not tested)

Funnel exposes a local port publicly at `https://<device>.<tailnet>.ts.net`; Tailscale handles TLS. According to Tailscale, Funnel is available on all plans, requires MagicDNS, HTTPS certificates and the `funnel` attribute in the tailnet policy, and only allows ports 443, 8443 and 10000 ([Tailscale documentation](https://tailscale.com/kb/1223/funnel)).

Sketch (check the command syntax for your Tailscale version):

```bash
# .env: MCP_PUBLIC_URL=https://<device>.<tailnet>.ts.net/mcp
levuvo-nextcloud-mcp --transport http
tailscale funnel 8765
```

Keep in mind: the Mac must be running and must not sleep; Tailscale is an external service in the data path; the address is public, so token protection is mandatory. Stop Funnel again after the test.

### Option 4: router port forwarding + dynamic DNS

Technically possible (own TLS proxy on the Mac, forward port 443), but not recommended. If at all, only briefly for testing and with all points of the checklist.

## Connecting clients

All of the following routes are implemented on the server side, but **not tested with the real client against a real deployment**.

### Claude Code CLI (remote, `static`)

Technically supported by Claude Code:

```bash
claude mcp add --transport http levuvo-nextcloud https://mcp.example/mcp \
  --header "Authorization: Bearer <MCP_STATIC_TOKEN>"
```

Note: the token is then stored in the Claude Code configuration and possibly in the shell history.

### Claude Web (custom connector)

- Requires a public HTTPS endpoint; Claude connects from the Anthropic cloud, not from the Mac.
- According to [Claude's help](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp), the connector dialog offers sign-in via OAuth or "no login"; as the OAuth client, Claude's published identity, automatic registration or a dedicated client; and fixed request headers for API keys/bearer tokens. Whether `static` works with this server that way is **not verified**.
- For `oauth`, the identity provider must fit one of these variants and issue RS256 JWT access tokens with a matching `aud` and scope. **Not verified.**
- On Team/Enterprise plans, admins add connectors; a static token is then the same for all members.

### ChatGPT

- Custom MCP connectors are available in Developer Mode; according to [OpenAI](https://developers.openai.com/api/docs/guides/developer-mode) for Plus, Pro, Business, Enterprise and Education on the web. Workspace admins can restrict it ([OpenAI Help](https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt)).
- Supported authentication according to OpenAI: OAuth, no authentication, mixed. Fixed headers are not provided for; `static` therefore cannot be used, and `oauth` with an external identity provider is required.
- Requires public HTTPS. **Not verified.**

### Claude Code on the web (cloud sessions)

Runs in the Anthropic cloud and can only reach public HTTPS endpoints, not a server on the Mac. **Not verified.**

## OAuth mode

```dotenv
MCP_AUTH_MODE=oauth
MCP_PUBLIC_URL=https://mcp.levuvo.com/mcp
MCP_OAUTH_ISSUER=https://login.example.com/
MCP_OAUTH_JWKS_URL=https://login.example.com/.well-known/jwks.json
MCP_OAUTH_AUDIENCE=https://mcp.levuvo.com/mcp
MCP_OAUTH_SCOPE=files:read
```

Requirements for the identity provider:

- Access tokens as **JWT, signed with RS256**, JWKS via HTTPS with `kid`.
- Claims `iss` (exactly as `MCP_OAUTH_ISSUER`, including any trailing `/`), `aud` (contains `MCP_OAUTH_AUDIENCE`), `sub`, `exp`, scope in `scope` (space-separated or list) or `scp`.
- Header `typ` is absent or `JWT`/`at+jwt`. ID tokens, opaque tokens, HS256 tokens and tokens over 8 KB are rejected.
- Login, consent, PKCE and client registration are handled by the identity provider.

If `MCP_OAUTH_AUDIENCE` equals `MCP_PUBLIC_URL`, the MCP SDK additionally checks the resource binding (RFC 8707). With a different, IdP-specific audience, only the JWT verifier checks `aud`.

Important: OAuth authenticates the client to the MCP server. In Nextcloud, everyone still accesses via the same technical account.
