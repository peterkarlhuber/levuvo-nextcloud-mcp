# Levuvo Nextcloud MCP v0.4

Eigener **read-only MCP-Server** für eure Hetzner Storage Share NX11 (`storage.levuvo.com`).

- **Claude Code**: lokal über `stdio`, ohne weiteren Server.
- **Claude Web**: über `https://mcp.levuvo.com/mcp` + Authentifizierung (nach Hosting/Setup).
- **ChatGPT**: derselbe Remote-MCP-Server ist technisch verwendbar; direkte eigene MCP-Connectoren erfordern laut aktueller OpenAI-Hilfe einen geeigneten Business- oder Enterprise/Edu-Workspace. OAuth-Integration benötigt zusätzlich einen kompatibel konfigurierten Identity Provider.

> Status: Quellcode und Offline-Tests vorhanden. **Nicht** gegen eure echte Nextcloud oder einen echten Cloud-Connector getestet; Deployment und Authentifizierung müssen erst konfiguriert werden. Vertrauliche Daten zunächst nicht freigeben.

## Enthalten

```
levuvo-nextcloud-mcp-v0.4/
├── .env.example
├── pyproject.toml
├── src/levuvo_nextcloud_mcp/
│   ├── __main__.py          # Einstieg
│   ├── server.py            # MCP SDK: stdio + Remote-HTTP
│   ├── webdav.py            # Nur GET und PROPFIND, Allowlist
│   ├── extractors.py        # TXT/MD/CSV/JSON/PDF/DOCX/XLSX
│   ├── settings.py          # Nextcloud-Konfiguration
│   ├── remote_settings.py   # Remote-Betrieb und Auth-Validierung
│   ├── static_bearer.py     # HTTP-Bearer-Token-Schutz
│   └── jwt_tokens.py        # JWT-Zugriffstoken verifizieren
├── deploy/
│   ├── Caddyfile.example
│   └── levuvo-nextcloud-mcp.service.example
├── tests/
└── SECURITY.md
```

### Exponierte MCP-Werkzeuge

| Werkzeug | Beschreibung |
|---|---|
| `list_files(path="", limit=100)` | Erlaubte Dateien/Ordner oder direkte Ordnerinhalte auflisten |
| `get_file_info(path)` | Datei-Metadaten |
| `search_files(query, max_depth=3, max_results=25)` | Dateinamensuche inkl. einzeln erlaubter Dateien, keine Volltextsuche |
| `read_file(path, max_chars=16000)` | Datei in Text umwandeln, begrenzt (max. 30.000 Zeichen) |

Keinerlei MCP-Werkzeuge zum Schreiben, Löschen, Hochladen, Verschieben oder Freigeben.

## Neu in v0.4: mehrere Dateien und Ordner, optionale Ausschlüsse

Die Einstellungen werden in `.env` als **kommagetrennte Pfade** relativ zum Nextcloud-Startordner des technischen Benutzers angegeben:

```dotenv
NEXTCLOUD_ALLOWED_PATHS=dir:01_Unternehmen/Strategie,file:02_Finanzen/Budget_2027.xlsx,05_Projekte/SaaS-Produkte,06_Marketing/CI.pdf
NEXTCLOUD_DENIED_PATHS=05_Projekte/SaaS-Produkte/Intern,01_Unternehmen/Strategie/Personalplanung.docx
```

**Typdefinition für Freigaben:**

- `dir:Pfad` – Ordner einschließlich Unterordner; ein tatsächlicher Datei-Pfad wird als Konfigurationskonflikt abgelehnt.
- `file:Pfad` – genau diese einzelne Datei, niemals deren Unterpfade; ein tatsächlicher Ordner wird als Konfigurationskonflikt abgelehnt.
- `Pfad` – ohne Präfix, automatische Typerkennung; WebDAV-Metadaten bestimmen, ob Datei oder Ordner. **Für vertrauliche Daten `file:`/`dir:` ausdrücklich angeben.**
- `NEXTCLOUD_DENIED_PATHS` – optional. Exakte Datei/Ordner-Ausschlüsse; ein ausgeschlossener Ordner sperrt seine gesamte Unterstruktur. **Deny hat Vorrang, auch bei überlappenden Freigaben.**

**Beispiel:** `NEXTCLOUD_ALLOWED_PATHS=dir:05_Projekte` erlaubt künftig jede neue Datei unter diesem Ordner. `NEXTCLOUD_DENIED_PATHS=05_Projekte/Vertraulich` verbietet diesen Unterbaum, nicht aber neu angelegte andere vertrauliche Dateien außerhalb der Ausschlussliste. Deshalb bevorzugen wir kleine, präzise Freigaben statt breite Freigaben mit vielen Ausnahmen.

`list_files(path="")` liefert die freigegebenen Einträge **mit korrektem Datei-/Ordnertyp**, auch einzelne Dateien. `search_files` durchsucht Dateinamen der expliziten Dateien und Unterordner; ausgeschlossene Einträge werden weder in Listen noch Suchergebnissen angezeigt und können nicht direkt gelesen werden. `list_files(path=<Datei>)` meldet einen verständlichen Fehler (für Dateien `get_file_info`/`read_file` nutzen). Ohne gültige Freigaben startet der Server nicht.

**Wichtig:** Nextcloud-Freigaben und eure MCP-Allowlist sind **zwei verschiedene Sicherheitsebenen**. Der technische Benutzer benötigt die Lese-Freigabe zusätzlich zu den MCP-Pfaden. Es werden keine zusätzlichen Zugriffsmöglichkeiten in Nextcloud erzeugt. Dateien, die zur Analyse an Claude/ChatGPT gehen, verlassen eure Nextcloud-Infrastruktur.

## A. Schnellstart mit Claude Code (Mac)

Voraussetzungen: macOS, Python 3.11+, Claude Code CLI, ein Nextcloud-Konto mit eigenen App-Passwort.

```bash
# ZIP entpacken; Terminal im entpackten Projektordner öffnen
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
chmod 600 .env
```

In `.env` nur diese Felder passend setzen:

- `NEXTCLOUD_URL=https://storage.levuvo.com`
- `NEXTCLOUD_USERNAME=agent.levuvo` (exakter Nextcloud-Loginname)
- `NEXTCLOUD_APP_PASSWORD=...` (eigenes App-Passwort, kein normales Login-Passwort)
- `NEXTCLOUD_ALLOWED_PATHS=dir:00_Agent_Test` (zunächst **ein** mit Leserecht geteilter Testordner)

**Sicherer Freigabeablauf:** Account `agent.levuvo` ohne Adminrechte erstellen; einen Testordner **von einem anderen Benutzer aus** mit ausschließlich Lesezugriff an `agent.levuvo` teilen. Keine vertraulichen Daten hineinlegen. Ein technischer Nextcloud-Benutzer hat einen eigenen beschreibbaren Bereich: Der MCP-Code verbietet Schreibwerkzeuge und über die Allowlist wird nur die Testfreigabe sichtbar. Keine allgemeinen Nextcloud-Wurzelverzeichnisse freigeben.

Danach im Projektordner:

```bash
claude mcp add --scope user --transport stdio levuvo-nextcloud -- "$(pwd)/.venv/bin/python" -m levuvo_nextcloud_mcp
claude mcp list
```

Im Claude-Code-Chat: `Liste die freigegebenen Ordner mit levuvo-nextcloud auf.`

**Hinweis:** Für v0.4 nur die beiden Einstellungen `NEXTCLOUD_ALLOWED_PATHS` und `NEXTCLOUD_DENIED_PATHS` verwenden. Frühere `.env`-Dateien müssen entsprechend angepasst werden; alte Variablennamen werden nicht unterstützt. Falls `levuvo-nextcloud` in Claude Code schon eingetragen ist, den alten Eintrag erst mit `claude mcp remove levuvo-nextcloud --scope user` entfernen und anschließend das obige `add` ausführen.

## B. Remote-HTTP lokal testen

Der Server bindet **immer `127.0.0.1`**, also nur Loopback. Die `MCP_PUBLIC_URL` ist der künftige öffentliche Name, nicht die lokale Bind-Adresse.

`.env` zusätzlich befüllen:

```dotenv
MCP_AUTH_MODE=static
MCP_PUBLIC_URL=https://mcp.levuvo.com/mcp
MCP_HTTP_PORT=8765
MCP_STATIC_TOKEN=DEIN_ZUFAELLIGER_WERT
```

Token erzeugen und in `.env` einfügen:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Dann starten:

```bash
source .venv/bin/activate
python -m levuvo_nextcloud_mcp --transport http
```

In einem **zweiten Terminal** kann ein Test ohne Token ausgeführt werden:

```bash
curl -i http://127.0.0.1:8765/mcp
# Erwartung: 401 Unauthorized
```

Für eine autorisierte MCP-Abfrage verwende den offiziellen MCP Inspector / einen MCP-HTTP-Client. Einen Token nicht direkt in die Shell-History kopieren; HTTP-Testaufrufe auf dem Produktivserver nur über localhost/TLS vornehmen. Die Authentifizierung schützt auch die Discovery- und MCP-Routen.

## C. Claude Web anbinden

Erst **nach** dem HTTPS-Deployment mit gültigem Zertifikat (Abschnitt D) und erfolgreichem Auth-Test:

1. In Claude Web `Anpassen → Connectoren → + Hinzufügen → Benutzerdefinierten Connector hinzufügen` öffnen.
2. Name: **Levuvo Nextcloud**.
3. URL: `https://mcp.levuvo.com/mcp`.
4. Mit `MCP_AUTH_MODE=static`: falls die Oberfläche es anbietet, unter *Request Headers* den Header `Authorization` mit Wert `Bearer <MCP_STATIC_TOKEN>` setzen. Bei Team-/Enterprise-Connectoren ist ein geteilter Schlüssel **nicht pro Benutzer getrennt**.
5. Connector aktivieren. Nur den Testordner abrufen.

Claude Web ruft über Anthropics Server aus dem Internet ab, nicht über `127.0.0.1` deines MacBooks. Ein lokaler Server ohne Tunnel/Hosting ist daher **nicht erreichbar**.

**Wichtig:** Statischer Bearer-Token ist eine Zwischenlösung für einen eng begrenzten Testbetrieb; für Teams und Unternehmensdaten besser OAuth (siehe E).

## D. Remote-Server veröffentlichen (Caddy / Linux)

**Hetzner Storage Share NX11 hostet nur Nextcloud, nicht euren Python-MCP-Dienst.** Ihr braucht einen eigenen kleinen Linux-Server/Container-Host mit DNS `mcp.levuvo.com`. Dafür kann ein separater Hetzner-VPS verwendet werden. Keine Portweiterleitung auf die Nextcloud selbst.

1. DNS `A/AAAA` von `mcp.levuvo.com` auf die IP eures MCP-Servers setzen.
2. Projekt nach `/opt/levuvo-nextcloud-mcp` kopieren; venv installieren; `.env` mit restriktiven Dateirechten erstellen; Service-Benutzer ohne Rootrechte einsetzen.
3. Port `8765` **nicht öffentlich öffnen**; MCP bindet ihn nur an `127.0.0.1`.
4. Caddy installieren und `deploy/Caddyfile.example` als Ausgangspunkt verwenden. Ports `80`/`443` für automatische HTTPS-Zertifikate verfügbar machen.
5. `deploy/levuvo-nextcloud-mcp.service.example` prüfen und an den Linux-Server anpassen (insbesondere Benutzer, Pfade, Schreibzugriffe).
6. **Zuerst** Testordner, TLS und Tokenzugriff prüfen. Öffentlicher Test ohne Token muss `401` ergeben.
7. Richtigen Connector erst danach hinzufügen. Logs dürfen nie Passwörter, Authorization-Header oder Dokumentinhalte enthalten.

### Erwartetes Ergebnis

- `https://mcp.levuvo.com/mcp` ist aus dem Internet über HTTPS erreichbar.
- Ohne Token: `401 Unauthorized`.
- Mit korrektem Token: gültige MCP-Transportantwort (abhängig von HTTP-Methode, MCP-Headern und Nachricht).
- Mit einem Pfad außerhalb `NEXTCLOUD_ALLOWED_PATHS`: Fehler **ohne Nextcloud-Anfrage**.

## E. OAuth-Modus (optional, für spätere ChatGPT-/Team-Anbindung)

**Nicht** mit dem statischen Bearer-Token verwechseln. Der OAuth-Modus nutzt das MCP-SDK als **OAuth Resource Server**, jedoch **kein eigenes Login-System**. Ihr benötigt vorher einen externen OAuth-2.1-/OIDC-kompatiblen Autorisierungsserver. Dieser muss u. a. Authorization Code + PKCE, passende Client-Registrierung und **RS256-signierte JWT-Access-Tokens** mit `aud`, `iss`, `sub`, `exp` und `scope` bereitstellen. Ein ID-Token ist **kein** Access-Token. Systeme mit ausschließlich opaken Tokens sind mit diesem Verifier nicht kompatibel.

```dotenv
MCP_AUTH_MODE=oauth
MCP_PUBLIC_URL=https://mcp.levuvo.com/mcp
MCP_OAUTH_ISSUER=https://login.example.com/
MCP_OAUTH_JWKS_URL=https://login.example.com/.well-known/jwks.json
MCP_OAUTH_AUDIENCE=https://mcp.levuvo.com/mcp
MCP_OAUTH_SCOPE=files:read
```

Im OAuth-Modus schützt das SDK `/mcp` und stellt *Protected Resource Metadata* über `/.well-known/oauth-protected-resource/mcp` bereit. Der Code prüft RSA-Signatur, Issuer, Audience, Ablauf und Scope. Die echte IdP-Integration, Registrierung der Clients und End-to-End-Tests sind **noch nicht eingerichtet**. Manche IdPs verwenden einen anderen Audience-Identifier: `MCP_OAUTH_AUDIENCE` muss zum `aud` des **Access Tokens** passen. Den Issuer einschließlich eines eventuellen abschließenden `/` exakt übernehmen.

Für den Einsatz mit ChatGPT muss zusätzlich der gebuchte ChatGPT-Workspace die Erstellung eigener MCP-Connectoren unterstützen. **Keine Garantie, dass jeder IdP unmittelbar mit allen Clients interoperabel ist.**

## F. Tests

```bash
python -m pip install -e '.[dev]'
pytest -q
```

Aktuell getestet: Pfadvalidierung, gemischte Datei-/Ordner-Allowlist, Denylist und Deny-Vorrang, nur `GET`/`PROPFIND`, Datei-Downloads mit Größenlimit, kein Redirect, Dateinamensuche, Dokumentextraktion, Bearer-Auth (auch doppelte Header), Konfigurationsprüfung, JWT-Signatur/Issuer/Audience/Expiry/Scope. **Keine** durchgehenden SDK-, WebDAV- oder Cloud-Connector-Integrationstests (keine reale Instanz/Zugangsdaten vorhanden).

## Quellen

- [MCP Python SDK v2 – Running your server](https://py.sdk.modelcontextprotocol.io/run/)
- [MCP Python SDK v2 – Authorization](https://py.sdk.modelcontextprotocol.io/run/authorization/)
- [MCP Python SDK v2 – Deploy & scale](https://py.sdk.modelcontextprotocol.io/run/deploy/)
- [Claude – Custom remote MCP connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
- [ChatGPT – Eigene MCP-Server verbinden](https://help.openai.com/de-de/articles/12584461-connecting-custom-mcp-servers-in-chatgpt)
