# Remote-Betrieb

Remote ist optional. Der lokale Betrieb mit Claude Code (`stdio`) braucht nichts von dieser Seite.

> Ein öffentlich erreichbarer Endpunkt ist **nicht produktionsreif**, bevor die Checkliste in [SECURITY.md](../SECURITY.md#checkliste-vor-jedem-öffentlichen-betrieb) abgearbeitet ist und Tests mit dem realen Client bestanden sind. Keiner der unten beschriebenen Wege wurde bisher mit diesem Server praktisch erprobt.

## Was der Server im HTTP-Modus macht

- Start: `levuvo-nextcloud-mcp --transport http`
- Lauscht **nur auf `127.0.0.1:MCP_HTTP_PORT`** (Standard 8765). TLS und öffentliche Erreichbarkeit übernimmt ein Reverse-Proxy oder Tunnel.
- Streamable HTTP, zustandslos, JSON-Antworten, Endpunkt `/mcp`.
- Host-Header-Allowlist: Host aus `MCP_PUBLIC_URL` sowie `localhost`/`127.0.0.1`; sonst HTTP 421. Browser-Origins sind nicht zugelassen.
- Request-Body max. 128 KiB, max. 32 gleichzeitige Verbindungen, kein Server-Header, kein Access-Log.
- Authentifizierung über `MCP_AUTH_MODE`:
  - `static`: fester Bearer-Token (`MCP_STATIC_TOKEN`, ≥ 32 Zeichen); jede Route ohne gültigen Token ergibt 401.
  - `oauth`: Prüfung von RS256-JWT-Access-Tokens eines externen Identity Providers; Protected Resource Metadata unter `/.well-known/oauth-protected-resource/mcp`. Ein eigener Login/OAuth-Server ist **nicht** enthalten.

Die Hetzner Storage Share kann diesen Python-Dienst nicht hosten; er braucht einen eigenen Rechner.

## Lokal testen (ohne Internet)

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'   # Token erzeugen, in .env als MCP_STATIC_TOKEN
.venv/bin/levuvo-nextcloud-mcp --transport http --check-config  # prüft auch die Remote-Einstellungen
.venv/bin/levuvo-nextcloud-mcp --transport http
```

In einem zweiten Terminal:

```bash
curl -i http://127.0.0.1:8765/mcp
# erwartet: 401 Unauthorized

read -rs TOKEN   # Token einfügen, landet nicht in der Shell-History
curl -i http://127.0.0.1:8765/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
# erwartet: JSON-Antwort mit serverInfo "Levuvo Nextcloud Read-Only"

curl -i http://127.0.0.1:8765/mcp -H "Authorization: Bearer $TOKEN" -H "Host: fremd.example"
# erwartet: 421 Invalid Host header
```

Alternativ den offiziellen MCP Inspector als Client verwenden.

## Optionen ohne Pflicht-Hostingkosten

Vorgaben: keine verpflichtenden Hostingkosten, kein Cloudflare, kein Docker-Zwang, der lokale Mac hat Vorrang, und Remote darf keine Voraussetzung für den lokalen Betrieb sein.

| Option | Kosten | Erreichbarkeit | Bewertung |
|---|---|---|---|
| 1. Nur lokal (`stdio`) | keine | nur Claude Code auf dem Mac | **Standard und empfohlen.** Kein offener Port. |
| 2. Eigener, vorhandener Linux-Server | keine zusätzlichen, falls der Server ohnehin läuft | dauerhaft | Saubere Lösung für später. Beispiele in `deploy/`. |
| 3. Tunnel ohne Cloudflare, z. B. Tailscale Funnel | kostenloser Tarif verfügbar | nur solange der Mac läuft und online ist | Externer Dienst im Datenpfad. Nicht getestet. |
| 4. Router-Portfreigabe + DynDNS | keine | solange der Mac läuft | **Nicht empfohlen**: Heimnetz wird direkt angreifbar, Zertifikate und Updates liegen bei euch. |

### Option 2: eigener Linux-Server (Caddy + systemd)

1. DNS-Eintrag (A/AAAA) für die gewünschte Domain auf den Server setzen. `mcp.levuvo.com` ist in den Beispielen nur ein Platzhalter; dieses Projekt richtet kein DNS ein.
2. Projekt nach `/opt/levuvo-nextcloud-mcp`, venv wie im README anlegen.
3. Konfiguration nach `/etc/levuvo-nextcloud-mcp/levuvo.env` (Besitzer Dienstbenutzer, `chmod 600`), `MCP_PUBLIC_URL` auf die echte Domain setzen.
4. `deploy/levuvo-nextcloud-mcp.service.example` anpassen und installieren; `systemd-analyze security levuvo-nextcloud-mcp` prüfen.
5. `deploy/Caddyfile.example` anpassen; Ports 80/443 öffnen, Port 8765 **nicht**.
6. Von außen prüfen: ohne Token 401, fremder Host 421 (mit gültigem Token), Pfade außerhalb der Freigabe abgelehnt.
7. Erst danach einen Client anbinden.

### Option 3: Tailscale Funnel (nicht getestet)

Funnel stellt einen lokalen Port unter `https://<gerät>.<tailnet>.ts.net` öffentlich bereit; TLS übernimmt Tailscale. Laut Tailscale ist Funnel in allen Tarifen verfügbar, setzt MagicDNS, HTTPS-Zertifikate und das `funnel`-Attribut in der Tailnet-Policy voraus und erlaubt nur die Ports 443, 8443 und 10000 ([Tailscale-Doku](https://tailscale.com/kb/1223/funnel)).

Skizze (Befehlssyntax je nach Tailscale-Version prüfen):

```bash
# .env: MCP_PUBLIC_URL=https://<gerät>.<tailnet>.ts.net/mcp
levuvo-nextcloud-mcp --transport http
tailscale funnel 8765
```

Zu beachten: Der Mac muss laufen und darf nicht schlafen; Tailscale ist ein externer Dienst im Datenpfad; die Adresse ist öffentlich, der Token-Schutz also zwingend. Funnel nach dem Test wieder beenden.

### Option 4: Router-Portfreigabe + DynDNS

Technisch möglich (eigener TLS-Proxy auf dem Mac, Port 443 weiterleiten), aber nicht empfohlen. Wenn überhaupt, nur kurzfristig zum Testen und mit allen Punkten der Checkliste.

## Clients anbinden

Alle folgenden Wege sind auf der Server-Seite implementiert, aber **nicht mit dem realen Client gegen ein echtes Deployment getestet**.

### Claude Code CLI (Remote, `static`)

Von Claude Code technisch unterstützt:

```bash
claude mcp add --transport http levuvo-nextcloud https://mcp.example/mcp \
  --header "Authorization: Bearer <MCP_STATIC_TOKEN>"
```

Hinweis: Der Token steht danach in der Claude-Code-Konfiguration und ggf. in der Shell-History.

### Claude Web (benutzerdefinierter Connector)

- Braucht einen öffentlichen HTTPS-Endpunkt; Claude verbindet sich aus der Anthropic-Cloud, nicht vom Mac aus.
- Laut [Claude-Hilfe](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp) bietet der Connector-Dialog Anmeldung per OAuth oder „kein Login“, als OAuth-Client Claudes veröffentlichte Identität, automatische Registrierung oder einen eigenen Client, sowie feste Request-Header für API-Keys/Bearer-Tokens. Ob `static` damit mit diesem Server funktioniert, ist **nicht verifiziert**.
- Für `oauth` muss der Identity Provider zu einer dieser Varianten passen und RS256-JWT-Access-Tokens mit passendem `aud` und Scope ausstellen. **Nicht verifiziert.**
- Bei Team-/Enterprise-Tarifen fügen Admins Connectoren hinzu; ein statischer Token ist dann für alle Mitglieder derselbe.

### ChatGPT

- Eigene MCP-Connectoren gibt es im Developer Mode; laut [OpenAI](https://developers.openai.com/api/docs/guides/developer-mode) für Plus, Pro, Business, Enterprise und Education im Web. Workspace-Admins können ihn einschränken ([OpenAI-Hilfe](https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt)).
- Unterstützte Authentifizierung laut OpenAI: OAuth, keine Authentifizierung, gemischt. Feste Header sind nicht vorgesehen; `static` ist damit nicht nutzbar, `oauth` mit externem Identity Provider ist nötig.
- Braucht öffentliches HTTPS. **Nicht verifiziert.**

### Claude Code im Web (Cloud-Sitzungen)

Läuft in der Anthropic-Cloud und erreicht nur öffentliche HTTPS-Endpunkte, keinen Server auf dem Mac. **Nicht verifiziert.**

## OAuth-Modus

```dotenv
MCP_AUTH_MODE=oauth
MCP_PUBLIC_URL=https://mcp.levuvo.com/mcp
MCP_OAUTH_ISSUER=https://login.example.com/
MCP_OAUTH_JWKS_URL=https://login.example.com/.well-known/jwks.json
MCP_OAUTH_AUDIENCE=https://mcp.levuvo.com/mcp
MCP_OAUTH_SCOPE=files:read
```

Anforderungen an den Identity Provider:

- Access Tokens als **JWT, signiert mit RS256**, JWKS über HTTPS mit `kid`.
- Claims `iss` (exakt wie `MCP_OAUTH_ISSUER`, inkl. eines eventuellen `/`), `aud` (enthält `MCP_OAUTH_AUDIENCE`), `sub`, `exp`, Scope in `scope` (Leerzeichen-getrennt oder Liste) oder `scp`.
- Header `typ` fehlt oder ist `JWT`/`at+jwt`. ID-Tokens, opake Tokens, HS256-Tokens und Tokens über 8 KB werden abgelehnt.
- Login, Einwilligung, PKCE und Client-Registrierung erledigt der Identity Provider.

Ist `MCP_OAUTH_AUDIENCE` gleich `MCP_PUBLIC_URL`, prüft das MCP-SDK zusätzlich die Ressourcenbindung (RFC 8707). Bei einer abweichenden, IdP-eigenen Audience prüft nur der JWT-Verifier das `aud`.

Wichtig: OAuth authentifiziert den Client am MCP-Server. In Nextcloud greifen trotzdem alle über dasselbe technische Konto zu.
