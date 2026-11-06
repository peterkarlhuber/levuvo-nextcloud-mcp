# Levuvo Nextcloud MCP

Schreibgeschützter MCP-Server (Model Context Protocol) für die Hetzner Storage Share der Levuvo unter `https://storage.levuvo.com`. Er gibt einem KI-Client (z. B. Claude Code) Lesezugriff auf ausdrücklich freigegebene Dateien und Ordner – und auf nichts sonst.

## Kurzüberblick und Status

- **Version:** 0.5.0 (Python 3.11+, MIT-Lizenz).
- **Lokal (Standard):** Claude Code startet den Server über `stdio` auf dem Mac. Kein offener Port, kein Hosting.
- **Remote (optional):** Streamable HTTP auf `127.0.0.1` hinter einem TLS-Reverse-Proxy, mit statischem Bearer-Token oder OAuth (externer Identity Provider nötig).
- **Nur lesen:** Der Server sendet an Nextcloud ausschließlich `GET` und `PROPFIND`. Es gibt keine Werkzeuge zum Schreiben, Löschen, Verschieben oder Teilen.

> **Status:** Der lokale Betrieb ist implementiert und automatisiert getestet, wurde aber noch **nicht** gegen die echte Storage Share und nicht mit der echten Claude-Code-App geprüft. Ein öffentlich erreichbarer Remote-Endpunkt ist **nicht produktionsreif**, solange die Checkliste in [SECURITY.md](SECURITY.md) nicht abgearbeitet ist und Tests mit dem realen Client nicht bestanden sind. Zu Beginn nur einen Testordner ohne vertrauliche Daten freigeben.

## Werkzeuge

| Werkzeug | Parameter (Grenzen) | Ergebnis |
|---|---|---|
| `list_files` | `path` (leer = alle Freigaben), `limit` 1–250, Standard 100 | Freigegebene Einträge bzw. direkte Inhalte eines freigegebenen Ordners (`folder`, `items`, `truncated`) |
| `get_file_info` | `path` | Metadaten ohne Inhalt: Typ, Größe, Content-Type, Änderungsdatum, ETag, Nextcloud-Rechte |
| `search_files` | `query` 1–120 Zeichen, `max_depth` 0–6 (Standard 3), `max_results` 1–100 (Standard 25) | Treffer im **Datei- oder Ordnernamen** (keine Volltextsuche); `complete` zeigt, ob vollständig gesucht wurde |
| `read_file` | `path`, `max_chars` 100–30000 (Standard 16000) | Text der Datei (`format`, `size_bytes`, `text`, `truncated`, bei Textdateien zusätzlich `encoding`) |

Alle vier Werkzeuge tragen die MCP-Annotationen `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true` und `openWorldHint=false` (eine fest konfigurierte Nextcloud, geschlossener Bereich). Die Annotationen beschreiben das Verhalten nur; erzwungen wird es im Code.

Erwartbare Fehler (Pfad nicht freigegeben, Datei zu groß, Nextcloud nicht erreichbar …) kommen als MCP-Werkzeugfehler mit deutscher Meldung zurück. Bei unerwarteten Abstürzen erhält der Client nur eine allgemeine Meldung (`Error executing tool <name>`); Details landen im Server-Log auf stderr.

**Unterstützte Formate in `read_file`:** Textformate (`.txt .md .markdown .csv .tsv .json .jsonl .yaml .yml .xml .html .htm .log .toml .ini .cfg .py .js .ts .css .sql .rst`), `.pdf`, `.docx`, `.xlsx`.

- Text: UTF-8 (mit oder ohne BOM), UTF-16 mit BOM, sonst Windows-1252 (`encoding: "cp1252"`, typisch für Excel-CSV). Binäre Inhalte werden abgelehnt.
- PDF: höchstens 40 Seiten, keine OCR; bei gescannten PDFs folgt ein Hinweis. Verschlüsselte PDFs werden abgelehnt.
- DOCX: Absätze und Tabellen des Haupttexts in Dokumentreihenfolge (keine Kopf-/Fußzeilen, Textfelder, Kommentare).
- XLSX: höchstens 10 Blätter, 1000 Zeilen, 60 Spalten; nur gespeicherte Werte, Formeln werden nicht berechnet.
- Office-Dateien werden vor dem Entpacken auf Zip-Bomben geprüft; beschädigte Dokumente ergeben eine klare Fehlermeldung.
- Downloadlimit: `NEXTCLOUD_MAX_FILE_BYTES` (Standard 8 MB).

## Schnellstart: macOS mit Claude Code

### 1. Voraussetzungen

- **Python 3.11 oder neuer.** Das System-Python von macOS ist oft 3.9 und funktioniert nicht. Prüfen mit `python3 --version`; sonst `brew install python@3.12` oder [uv](https://docs.astral.sh/uv/) (`brew install uv`, uv lädt bei Bedarf selbst ein passendes Python).
- Claude Code CLI (`claude`).
- Ein eigenes technisches Nextcloud-Konto (z. B. `agent.levuvo`) mit App-Passwort und einem **schreibgeschützt** geteilten Testordner – Einrichtung siehe [SECURITY.md](SECURITY.md#nextcloud-seite-minimale-rechte).

### 2. Installieren (reproduzierbar über Lockfiles)

Mit uv (empfohlen):

```bash
cd levuvo-nextcloud-mcp
uv sync --extra dev          # nutzt uv.lock, legt .venv an
```

Alternativ mit pip und Hash-geprüfter Lockdatei:

```bash
cd levuvo-nextcloud-mcp
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
```

`requirements.lock` enthält nur die Laufzeitabhängigkeiten (ohne Test-Werkzeuge).

### 3. Konfigurieren

```bash
cp .env.example .env
chmod 600 .env
```

In `.env` mindestens setzen:

```dotenv
NEXTCLOUD_URL=https://storage.levuvo.com
NEXTCLOUD_USERNAME=agent.levuvo
NEXTCLOUD_APP_PASSWORD=<App-Passwort aus Nextcloud>
NEXTCLOUD_ALLOWED_PATHS=dir:00_Agent_Test
```

Prüfen:

```bash
.venv/bin/levuvo-nextcloud-mcp --check-config      # offline, zeigt keine Geheimnisse
.venv/bin/levuvo-nextcloud-mcp --check-nextcloud   # liest Metadaten der Freigaben aus Nextcloud
```

### 4. In Claude Code eintragen

Im Projektordner:

```bash
claude mcp add --scope user --transport stdio levuvo-nextcloud \
  --env LEVUVO_MCP_ENV_FILE="$(pwd)/.env" \
  -- "$(pwd)/.venv/bin/levuvo-nextcloud-mcp"
claude mcp list
```

Ein älterer Eintrag (z. B. aus v0.4) muss vorher entfernt werden:

```bash
claude mcp remove levuvo-nextcloud --scope user
```

Danach in Claude Code z. B.: „Liste mit levuvo-nextcloud die freigegebenen Ordner auf.“

`LEVUVO_MCP_ENV_FILE` ist nötig, weil Claude Code den Server nicht zwingend im Projektordner startet. Ohne die Variable sucht der Server `.env` nur neben `pyproject.toml` einer Quellcode-Installation.

## Berechtigungen

Zugriff steuern ausschließlich zwei Variablen mit identischer Syntax:

- `NEXTCLOUD_ALLOWED_PATHS` – Freigaben (Pflicht, mindestens ein Eintrag).
- `NEXTCLOUD_DENIED_PATHS` – Ausnahmen innerhalb der Freigaben (optional).

Andere oder ältere Variablen (z. B. `NEXTCLOUD_ALLOWED_ROOTS`) kennt v0.5 nicht; sie werden ignoriert, und der Server startet dann mit „NEXTCLOUD_ALLOWED_PATHS ist leer“ nicht.

### Syntax

Einträge werden mit Komma getrennt. Pfade sind relativ zum Dateibereich des technischen Kontos (so, wie `agent.levuvo` die Dateien in Nextcloud sieht), mit `/` getrennt.

| Form | Bedeutung |
|---|---|
| `dir:Pfad` | Ordner mit allen Unterordnern. Ist der Pfad in Nextcloud eine Datei, gibt es zur Laufzeit einen Fehler. |
| `file:Pfad` | Genau diese eine Datei. Ist der Pfad ein Ordner, gibt es zur Laufzeit einen Fehler. |
| `Pfad` | Typ wird über Nextcloud erkannt. Für vertrauliche Bereiche besser `dir:`/`file:` angeben. |

```dotenv
NEXTCLOUD_ALLOWED_PATHS=dir:01_Unternehmen/Strategie,file:02_Finanzen/Budget_2027.xlsx,dir:05_Projekte/SaaS-Produkte
NEXTCLOUD_DENIED_PATHS=dir:05_Projekte/SaaS-Produkte/Intern,file:01_Unternehmen/Strategie/Personalplanung.docx
```

### Regeln

- **Pfadform:** kein führendes `/`, kein Backslash, keine `.`/`..`-Abschnitte, keine Steuer- oder unsichtbaren Formatzeichen. Ein abschließendes `/` wird entfernt. Pfade werden Unicode-NFC-normalisiert.
- **Keine URL-Kodierung:** `%20` und ähnliche Sequenzen werden abgelehnt. Pfade unkodiert angeben (`Projekt Alpha`, nicht `Projekt%20Alpha`).
- **Präfixe:** nur `dir:` und `file:`, klein geschrieben. `DIR:`, `folder:` usw. sind ein Startfehler. Beginnt ein Ordnername selbst mit `Wort:` (z. B. `Projekt:Alpha`), immer mit Präfix angeben: `dir:Projekt:Alpha`.
- **Freigaben sind exakt:** Verglichen wird nach NFC-Normalisierung, Groß-/Kleinschreibung zählt. Die Normalisierung kann den Zugriff also nie erweitern.
- **Ausschlüsse sind vorsichtig:** Sie greifen auch bei anderer Schreibweise (Groß-/Kleinschreibung, Unicode-Varianten, Punkte/Leerzeichen am Ende eines Abschnitts) und sperren **immer den ganzen Teilbaum**, unabhängig von `dir:`/`file:`. Ausschluss hat immer Vorrang. Ein Präfix bei Ausschlüssen wird geprüft, sobald der Eintrag in einer Ordnerliste auftaucht; widerspricht er dem echten Typ, gibt es einen Fehler.
- **Gleiche Antwort:** Ein ausgeschlossener und ein nie freigegebener Pfad liefern dieselbe Meldung („Der Pfad ist nicht für den MCP-Agenten freigegeben.“).
- **Startfehler** (Server startet nicht, Exit-Code 2):
  - leere Freigabeliste,
  - doppelte Einträge, auch in anderer Schreibweise (`dir:Test` und `test`),
  - Ausschluss, der unter keiner Freigabe liegt (wirkungslos, meist Tippfehler),
  - Freigabe, die von einem Ausschluss vollständig gesperrt wird,
  - Einträge unterhalb einer `file:`-Freigabe,
  - unbekannte Präfixe, ungültige Pfade.

### Stolperfallen

- Breite Ordnerfreigaben geben auch **künftig angelegte** Dateien frei. Kleine, gezielte Freigaben sind sicherer als breite Freigaben mit vielen Ausnahmen.
- Nextcloud-Freigabe und MCP-Freigabe sind zwei getrennte Ebenen: Der Pfad muss für `agent.levuvo` in Nextcloud lesbar **und** hier freigegeben sein.
- Kommas in Datei- oder Ordnernamen lassen sich nicht angeben (Komma ist das Trennzeichen).
- Geteilte Ordner erscheinen beim Empfänger normalerweise in dessen Wurzelverzeichnis, je nach Nextcloud-Einstellung auch in einem Unterordner. Maßgeblich ist der Pfad, den `agent.levuvo` in der Weboberfläche sieht.

## Konfigurationsreferenz

Die Werte kommen aus echten Umgebungsvariablen oder einer `.env`-Datei. Echte Umgebungsvariablen haben Vorrang vor der Datei. Suchreihenfolge der Datei: `LEVUVO_MCP_ENV_FILE` (muss existieren, falls gesetzt) → `.env` neben `pyproject.toml` (nur in einer Quellcode-Installation) → keine Datei. Ist die Datei für Gruppe oder andere lesbar, warnt der Server (Empfehlung `chmod 600`).

| Variable | Pflicht | Standard | Bedeutung |
|---|---|---|---|
| `NEXTCLOUD_URL` | ja | – | HTTPS-Adresse ohne Pfad und ohne Zugangsdaten, z. B. `https://storage.levuvo.com` |
| `NEXTCLOUD_USERNAME` | ja | – | Loginname des technischen Kontos |
| `NEXTCLOUD_APP_PASSWORD` | ja | – | App-Passwort (nicht das Login-Passwort); Platzhalter werden abgelehnt |
| `NEXTCLOUD_USER_ID` | nein | = Loginname | WebDAV-Benutzer-ID, falls sie vom Loginnamen abweicht (z. B. Login per E-Mail-Adresse) |
| `NEXTCLOUD_ALLOWED_PATHS` | ja | – | Freigaben, siehe [Berechtigungen](#berechtigungen) |
| `NEXTCLOUD_DENIED_PATHS` | nein | leer | Ausnahmen |
| `NEXTCLOUD_MAX_FILE_BYTES` | nein | `8000000` | Downloadlimit für `read_file`, 1–30000000 |
| `NEXTCLOUD_TIMEOUT_SECONDS` | nein | `20` | Zeitlimit für Nextcloud-Anfragen, 1–120 |
| `LEVUVO_MCP_ENV_FILE` | nein | – | Expliziter Pfad zur `.env` |
| `MCP_PUBLIC_URL` | nur HTTP | `https://mcp.levuvo.com/mcp` | Öffentliche HTTPS-Adresse, muss auf `/mcp` enden, Port nur 443 |
| `MCP_HTTP_PORT` | nur HTTP | `8765` | Lokaler Port (1024–65535), immer nur `127.0.0.1` |
| `MCP_AUTH_MODE` | nur HTTP | `static` | `static` oder `oauth` |
| `MCP_STATIC_TOKEN` | bei `static` | – | Zufälliges Token, 32–512 Zeichen, ohne Leerzeichen |
| `MCP_OAUTH_ISSUER` | bei `oauth` | – | Issuer des Identity Providers (HTTPS, exakt wie im Token) |
| `MCP_OAUTH_JWKS_URL` | bei `oauth` | – | JWKS-Adresse des Identity Providers (HTTPS) |
| `MCP_OAUTH_AUDIENCE` | bei `oauth` | – | Erwarteter `aud`-Wert des Access Tokens |
| `MCP_OAUTH_SCOPE` | bei `oauth` | `files:read` | Erforderlicher Scope |

Die `MCP_*`-Variablen werden nur mit `--transport http` gelesen und geprüft.

## Prüfbefehle

Aufruf als `levuvo-nextcloud-mcp` oder `python -m levuvo_nextcloud_mcp`:

| Befehl | Wirkung |
|---|---|
| `--transport stdio` | Standard; für lokale Clients wie Claude Code |
| `--transport http` | Streamable HTTP auf `127.0.0.1:MCP_HTTP_PORT` |
| `--check-config` | Prüft die Konfiguration offline und gibt eine Zusammenfassung ohne Passwort/Token aus. Mit `--transport http` werden auch die Remote-Einstellungen geprüft. |
| `--check-nextcloud` | Liest jeden freigegebenen Eintrag per `PROPFIND` (nur lesend), zeigt Typ und Nextcloud-Rechtebuchstaben und warnt, wenn das technische Konto dort schreiben oder löschen könnte (Buchstaben `W C K D N V`). Exit-Code 1 bei Fehlern. |
| `--version` | Version ausgeben |

Konfigurationsfehler beenden den Server mit Exit-Code 2 und der Meldung `Konfigurationsfehler: …` auf stderr.

## Tests und Qualität

```bash
uv run --extra dev pytest                 # oder: .venv/bin/pytest
uv run --extra dev pytest --cov           # mit Abdeckung
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
```

Die GitHub-Actions-Pipeline `.github/workflows/ci.yml` prüft `uv lock --check`, `ruff check` und `ruff format --check` und führt `pytest` unter Python 3.11, 3.12 und 3.13 (Ubuntu) sowie 3.12 auf macOS aus. Ein weiterer Job installiert aus `requirements-dev.lock` mit `--require-hashes` (der dokumentierte pip-Weg). Hinweis: `uv run` ohne `--extra dev` entfernt die Entwicklungswerkzeuge wieder aus `.venv`.

**Lokaler Teststand v0.5.0 (2026-11-06):** 381 Tests bestanden, 0 fehlgeschlagen, unter Python 3.11 (Installation aus `requirements-dev.lock`), 3.12 und 3.13; Zeilen-/Zweigabdeckung 91 %. `ruff check` und `ruff format --check` ohne Befund.

Die Tests laufen offline gegen nachgebildete WebDAV-Antworten. Ein Test gegen die echte Storage Share und mit realen Clients steht aus (siehe [Kompatibilität](#kompatibilität)).

## Remote-Betrieb

Remote ist optional und für den lokalen Betrieb nicht nötig. Kurzfassung:

- Der Server bindet **nur `127.0.0.1`**. TLS und öffentliche Erreichbarkeit übernimmt ein Reverse-Proxy oder Tunnel.
- Transport: Streamable HTTP, zustandslos, JSON-Antworten, Endpunkt `/mcp`.
- Schutz: Host-Header-Allowlist (öffentlicher Host aus `MCP_PUBLIC_URL` und localhost), keine Browser-Origins, Request-Body max. 128 KiB, max. 32 gleichzeitige Verbindungen, kein Server-Header, kein Access-Log.
- Authentifizierung: `MCP_AUTH_MODE=static` (fester Bearer-Token, schützt alle Routen) oder `oauth` (nur Resource Server; Login und Token-Ausgabe macht ein externer Identity Provider).
- Die Hetzner Storage Share kann den Python-Dienst **nicht** hosten.

Optionen ohne Pflicht-Hostingkosten (nur lokal, eigener Linux-Server, Tailscale Funnel, Router-Portfreigabe) und alle Details: [docs/REMOTE.md](docs/REMOTE.md). Beispielkonfigurationen: [deploy/](deploy/).

## Kompatibilität

| Client | Technisch implementiert | Automatisiert getestet | Mit realem Client getestet | Nicht verifiziert |
|---|---|---|---|---|
| Claude Code lokal (`stdio`) | ja | ja, inkl. echtem stdio-Subprozess mit MCP-Handshake | nein | Betrieb gegen die echte Storage Share und mit der echten Claude-Code-App |
| Claude Code CLI remote (`--transport http --header`) | ja (Modus `static`) | ja: lokaler Uvicorn-Server auf 127.0.0.1 mit echtem MCP-HTTP-Client, dazu Negativtests für Token, Host, Origin und Body-Limit | nein | Ende-zu-Ende gegen ein echtes Deployment |
| Claude Web, benutzerdefinierter Connector | ja (Server-Seite) | Server-Seite ja | nein | Gesamtes Zusammenspiel. Braucht öffentliches HTTPS. Laut Claude-Hilfe bietet der Connector OAuth, „kein Login“ und feste Request-Header an; ob `static` damit funktioniert, ist ungeprüft. `oauth` braucht einen Identity Provider, der mit Claudes Ablauf zusammenspielt (automatische Registrierung oder eigener OAuth-Client). |
| ChatGPT (Developer Mode / eigene MCP-Connectoren) | ja (Server-Seite, `oauth`) | Server-Seite ja | nein | Gesamtes Zusammenspiel. Braucht passenden Tarif (laut OpenAI Developer Mode für Plus, Pro, Business, Enterprise, Education im Web; Workspace-Richtlinien können ihn einschränken), öffentliches HTTPS und OAuth. OpenAI nennt als Authentifizierung nur OAuth, „keine Authentifizierung“ und gemischt – keine festen Header, `static` ist dort also nicht nutzbar. |
| Claude Code im Web (Cloud-Sitzungen) | – | – | nein | Läuft in der Anthropic-Cloud und erreicht nur einen öffentlichen HTTPS-Endpunkt, keinen Server auf dem Mac. |

Quellen (Stand 2026-11-06): [Claude – Custom Connectors mit Remote-MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp), [OpenAI – ChatGPT Developer Mode](https://developers.openai.com/api/docs/guides/developer-mode), [OpenAI-Hilfe – Developer Mode und MCP-Connectoren](https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt). Tarife und Oberflächen ändern sich; vor der Einrichtung aktuell nachlesen.

## Fehlerbehebung

Häufige Fälle (Details in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)):

- Python zu alt (`requires-python >=3.11`) → Homebrew `python@3.12` oder uv.
- `.env` wird nicht gefunden → `LEVUVO_MCP_ENV_FILE` mit absolutem Pfad setzen.
- 401 → Benutzername oder App-Passwort falsch; 403 → Freigaberechte des Kontos prüfen.
- Leere Listen oder „Die WebDAV-Antwort enthält den angefragten Pfad nicht“ → `NEXTCLOUD_USER_ID` setzen.
- „Freigabe-Typ widerspricht Nextcloud“ → `file:`/`dir:` korrigieren.
- „URL-kodierte Zeichen“ → Pfad unkodiert eintragen.
- Startfehler bei Ausschlüssen → Ausschluss muss unter einer Freigabe liegen und darf sie nicht ganz sperren.
- Umlaute in CSV → Feld `encoding` beachten.
- Gescanntes PDF → keine OCR; Text vorher erzeugen.

## Projektstruktur

```
levuvo-nextcloud-mcp/
├── .env.example                 # alle Variablen mit Platzhaltern
├── pyproject.toml
├── uv.lock, requirements.lock, requirements-dev.lock
├── src/levuvo_nextcloud_mcp/
│   ├── __main__.py              # python -m levuvo_nextcloud_mcp
│   ├── server.py                # MCP-Werkzeuge, CLI, stdio/HTTP
│   ├── policy.py                # Pfadnormalisierung, Allow/Deny-Logik
│   ├── settings.py              # Nextcloud-Konfiguration, .env-Suche
│   ├── webdav.py                # Nextcloud-Client (nur GET/PROPFIND)
│   ├── extractors.py            # Text aus TXT/CSV/PDF/DOCX/XLSX
│   ├── errors.py                # erwartete Fehler mit deutschen Meldungen
│   ├── remote_settings.py       # Remote-Konfiguration
│   ├── static_bearer.py         # statischer Bearer-Token
│   └── jwt_tokens.py            # Prüfung von OAuth-JWT-Access-Tokens
├── tests/
├── deploy/                      # Caddy- und systemd-Beispiele
├── docs/REMOTE.md, docs/TROUBLESHOOTING.md
├── .github/workflows/ci.yml
├── SECURITY.md
└── CHANGELOG.md
```

## Lizenz

MIT, siehe [LICENSE](LICENSE).
