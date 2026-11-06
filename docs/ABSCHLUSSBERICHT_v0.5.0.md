# Abschlussbericht – Levuvo Nextcloud MCP v0.5.0

Stand: 2026-11-06 · Branch `release/v0.5` · Basis: v0.4 (ZIP-Import, Commit `bc008a3`)

**Freigabestatus:** v0.5.0 ist für den **lokalen Betrieb mit Claude Code** (Testordner, unkritische Daten) freigabefähig. Für einen **öffentlichen Remote-Betrieb** ist sie ausdrücklich **nicht** freigegeben: Tests gegen die echte Storage Share und mit realen Remote-Clients fehlen (siehe Abschnitt E und G).

---

## A. Executive Summary

Gegenüber v0.4 wurden alle bestätigten Findings des Reviews vom 2026-11-06 umgesetzt:

- **Berechtigungen:** Die Denylist ließ sich in v0.4 über Präfixe (`dir:X` wirkungslos), Unicode-NFD-Schreibweisen und Groß-/Kleinschreibung umgehen. v0.5 hat eine zentrale Policy (`policy.py`): Freigaben werden exakt nach NFC-Normalisierung verglichen, Ausschlüsse konservativ (NFKC + casefold) und immer für den ganzen Teilbaum. Widersprüchliche oder wirkungslose Konfigurationen verhindern den Start.
- **MCP:** In v0.4 kam jede Fehlermeldung beim Client nur als „Error executing tool …“ an (im MCP SDK 2.3.0 nachgewiesen). Jetzt erhalten Clients verständliche deutsche Fehlermeldungen, die Werkzeuge haben korrekte Annotations, Schema-Grenzen und strukturierte Ergebnisse.
- **WebDAV:** ein Verbindungspool pro Prozess, gestreamte Größenlimits, Unterstützung abweichender Nextcloud-User-IDs, begrenzt parallele Suche (ca. 3× schneller), nicht blockierende Dokumentauswertung, Encoding-Fallback für Excel-CSV und DOCX in Dokumentreihenfolge.
- **Qualität:** 381 statt 43 Tests, darunter echte MCP-Sitzungen über In-Process, stdio-Subprozess und Streamable HTTP (Uvicorn). Abdeckung 91 %, Ruff, Lockfiles mit Hashes und GitHub-Actions-CI.
- **Doku:** README, SECURITY.md, CHANGELOG, `.env.example`, Deploy-Beispiele, neu `docs/REMOTE.md` und `docs/TROUBLESHOOTING.md`.

## B. Umgesetzte Optimierungen

| ID | Beschreibung | Geänderte Dateien | Ergebnis |
|---|---|---|---|
| M1 / SEC-01, 02, 03, 05 | Zentrale Policy; gleiche `dir:`/`file:`-Syntax in beiden Variablen; NFC; konservativer Deny-Vergleich; Startfehler bei unbekannten Präfixen, Duplikaten, wirkungslosen Denies, vollständig gesperrten Allows | `policy.py` (neu), `settings.py`, `webdav.py` | umgesetzt, 107 Policy-Tests + WebDAV-Tests mit case-insensitivem Fake-Backend |
| M2 / MCP-01 | Erwartete Fehler → `ToolError` mit sicherer Meldung; eigene Fehlerklassen | `errors.py` (neu), `server.py`, alle Module | umgesetzt; generische Meldung nur noch bei echten Abstürzen |
| M3 / QA-01 | MCP-Integrationstests: in-process, stdio-Subprozess, Streamable HTTP mit Uvicorn und MCP-Client | `tests/test_mcp_tools.py`, `test_stdio_and_cli.py`, `test_http_transport.py`, `conftest.py` | umgesetzt |
| M4 / QA-02 | Sicherheits- und Grenzfalltests; weiche Asserts ersetzt | `tests/*` | umgesetzt |
| M5 / MCP-02, 03 | Tool-Annotations (`readOnlyHint`, `destructiveHint=false`, `idempotentHint`, `openWorldHint=false`), Schema-Grenzen, strukturierte Ausgabe | `server.py` | umgesetzt |
| M6 / SEC-04 | Rechte-Konzept für das Nextcloud-Konto, Quota-Semantik, `--check-nextcloud` mit Schreibrechte-Warnung | `SECURITY.md`, `webdav.py`, `server.py` | umgesetzt (Doku + Prüfbefehl) |
| M7 / MCP-05, QA-03 | Gepinnte Abhängigkeiten, `uv.lock`, `requirements(-dev).lock` mit Hashes, CI | `pyproject.toml`, Lockfiles, `.github/workflows/ci.yml` | umgesetzt |
| M8 / WD-02 | Ein HTTP-Client pro Prozess, Settings einmal geladen, Typ-Cache 5 min | `server.py`, `webdav.py` | 5× `read_file`: 11 statt 15 Requests, 1 TLS-Verbindung statt 5 |
| M9 / WD-03, WD-05 | Breitensuche mit 4 parallelen PROPFIND; Extraktion in Worker-Thread (max. 2) | `webdav.py` | 61 Ordner bei 20 ms Latenz: 0,38 s statt ≥ 1,22 s; Event-Loop bleibt frei (Test) |
| M10 / WD-04, WD-06 | UTF-8/UTF-16/cp1252, Binärerkennung, DOCX-Reihenfolge, Fehler bei beschädigten Dokumenten, Scan-Hinweis | `extractors.py` | umgesetzt |
| M11 / CFG-01, 02, WD-01 | `LEVUVO_MCP_ENV_FILE`, `NEXTCLOUD_USER_ID`, macOS-Anleitung, `--check-config`, Exit-Code 2 | `settings.py`, `server.py`, README | umgesetzt |
| M12 / SEC-06, 07, 08 | PROPFIND gestreamt (2 MB), DTD verboten; JWKS-Cache + Refresh-Drossel; korrekte Audience/`client_id` im AccessToken | `webdav.py`, `jwt_tokens.py`, `server.py` | umgesetzt |
| M14 / OPS-02, CFG-04 | systemd-/Caddy-Härtung; Uvicorn ohne Server-Header, `limit_concurrency`; eine Versionsquelle | `deploy/*`, `server.py`, `pyproject.toml`, `__init__.py` | umgesetzt |
| SEC-09 | Kein Traceback-Logging für erwartete Fehler; Secrets nicht in `repr`; Warnung bei lesbarer `.env` | `server.py`, `settings.py`, `remote_settings.py` | umgesetzt |
| CFG-03 | Großgeschriebene/unbekannte Präfixe sind Startfehler | `policy.py` | umgesetzt |
| M13 | Remote: Code geprüft und getestet, Doku der Voraussetzungen | `server.py`, `docs/REMOTE.md` | vorbereitet, **kein** Deployment |

### Abweichungen vom Review-Plan (begründet)

- **Quota 0 nicht empfohlen.** Eine Nextcloud-Quota begrenzt nur den Speicher im eigenen Bereich. Dateien in empfangenen Freigaben zählen zur Quota des Eigentümers. Ordner und leere Dateien bleiben möglich. Quota ist also keine Zugriffskontrolle. Die wirksamen Maßnahmen sind schreibgeschützte Freigaben, den eigenen Home-Bereich nie freigeben und `--check-nextcloud` (siehe SECURITY.md).
- **Deny case-insensitiv statt nur Warnung (E3/E4).** Gemäß Leitentscheidung „konservative Deny-Prüfung, Startfehler bei Fehlkonfiguration“: Ein Deny außerhalb jeder Freigabe ist ein Startfehler, und Deny vergleicht ohne Groß-/Kleinschreibung. Dadurch kann zu viel gesperrt werden, aber nie zu wenig.
- **URL-kodierte Pfade werden abgelehnt statt dekodiert.** Ein Pfad wird genau einmal interpretiert, nämlich von Nextcloud nach unserer Kodierung. Doppelte Dekodierung ist damit ausgeschlossen. Ein einzelnes `%` bleibt erlaubt.
- **Allow-Eintrag unter Deny = Startfehler.** In v0.4 wurde `file:X` unter einem gesperrten Ordner still ignoriert. Jetzt meldet der Start den Widerspruch.
- **Korrektur meines Review-Befunds MCP-04.** Laut Claude-Hilfe-Center bieten benutzerdefinierte Connectoren neben OAuth auch feste Request-Header an. Static-Bearer könnte daher in Claude Web funktionieren. Verifiziert ist das mit diesem Server nicht. ChatGPT bietet laut OpenAI keine festen Header, dort bleibt nur OAuth.

## C. Sicherheitsbewertung

**Behoben:** SEC-01 bis SEC-09 sowie zusätzlich:

- Ablehnung von Steuer- und Formatzeichen (Bidi, Zero-Width)
- einmalige Dekodierung pro `href`-Segment (ein kodiertes `/` wird verworfen)
- gleiche Meldung für gesperrte und nicht freigegebene Pfade
- Algorithmus-Confusion (HS256/none) nachweislich abgelehnt
- Requests nur `GET`/`PROPFIND`, zur Laufzeit und statisch geprüft

**Nachweis durch Tests (Auswahl):**

- Gesperrte Pfade in NFC-, NFD- und NFKD-Form, mit anderer Groß-/Kleinschreibung, Vollbreitenzeichen sowie Punkt oder Leerzeichen am Ende werden abgelehnt. Das gilt auch gegen ein case-insensitives Fake-Backend, und es geht **keine** Anfrage an Nextcloud raus.
- Traversal (`..`, `.`, `//`, `\`, absolut), `%2F`, `%252F` und überlange Pfade werden abgelehnt.
- Feindliche WebDAV-Antworten werden verworfen: fremde Hosts und Benutzer, Traversal, Query, Enkel-Einträge, Duplikate, XXE und Billion Laughs.
- Static-Bearer ist auf allen Routen und Methoden durchgesetzt, inklusive doppelter Header. Ein falscher Host liefert 421, Browser-Origins werden abgelehnt, und das Body-Limit liefert 413.
- OAuth: falsche Audience, falscher Issuer, abgelaufene Tokens, `nbf`, fehlender Scope, ID-Tokens, fremder Schlüssel, `alg=none`, HS256-Confusion und fehlender `kid` werden abgelehnt. 25 unbekannte `kid`s lösen genau 1 JWKS-Abruf aus. Bei JWKS-Ausfall schlägt die Prüfung geschlossen fehl.

**Restrisiken:**

1. Das App-Passwort hat volle Kontorechte. Wer die `.env` liest, kann in Nextcloud schreiben. Gegenmaßnahmen: `chmod 600`, Konto ohne eigene freigegebene Daten, Rotation.
2. Alle Remote-Nutzer teilen sich eine technische Nextcloud-Identität. Es gibt keine Rechte pro Person.
3. Prompt-Injection über Dokumentinhalte ist möglich. Der Server liefert nur Daten, aber das Modell kann sich beeinflussen lassen. Deshalb keine Schreib- oder Ausführungs-Tools im selben Agenten.
4. Gelesene Inhalte gehen an den KI-Anbieter. Für Kundendaten müsst ihr DSGVO und Verträge prüfen.
5. Konservatives Deny kann ähnlich benannte Einträge mitsperren (z. B. `Intern` und `intern.`).
6. Die NFC-Normalisierung von Nextcloud und das Verhalten bei Groß-/Kleinschreibung auf der Storage Share sind nicht real gemessen. v0.5 ist so gebaut, dass beide Fälle sicher sind.

**Keine offenen kritischen Befunde.**

## D. Architekturänderungen

| Entscheidung | Begründung |
|---|---|
| Neues Modul `policy.py` für alle Pfadentscheidungen | Eine einzige, testbare Stelle für die Sicherheitslogik (Security by Design). `settings.py` lädt und validiert nur noch. |
| Neues Modul `errors.py` mit einer Fehlerhierarchie | Klare Trennung zwischen „sicher anzeigbar“ (`LevuvoError` → `ToolError`) und Absturz (generisch). |
| `create_mcp(settings, …)` bekommt Settings injiziert, ein Client pro Prozess (`_ClientHolder`) | Keine Neuinitialisierung pro Aufruf, testbar ohne Umgebungsvariablen. |
| `_request()`-Kontextmanager mit Methoden-Allowlist | Read-only als zweite Verteidigungslinie im Code, nicht nur per Konvention. |
| Keine neuen Frameworks und Dienste | Neu sind nur Entwicklungswerkzeuge (`pytest-cov`, `ruff`). Laufzeitabhängigkeiten unverändert (`pydantic` kommt bereits über `mcp`, jetzt explizit). |
| Version nur in `__init__.py` (`hatch` dynamic) | Konsistenz, per Test abgesichert. |

## E. Testergebnisse

| Kennzahl | Wert |
|---|---|
| Ausgeführte Tests | **381** (v0.4: 43, alle weiterhin enthalten und angepasst) |
| Bestanden / fehlgeschlagen | **381 / 0** |
| Python-Versionen lokal | 3.11.18 (Installation aus `requirements-dev.lock` mit `--require-hashes`), 3.12.3, 3.13.18 (via `uv run --frozen`) |
| Abdeckung (Zeilen + Zweige) | **91 %** (policy 98 %, webdav 95 %, jwt 99 %, server 69 %: CLI-Pfade laufen als Subprozess und werden nicht mitgezählt) |
| Lint | `ruff check` und `ruff format --check`: ohne Befund; `uv lock --check`: aktuell |
| GitHub Actions | im PR ausgeführt, Ergebnis siehe PR |

**Integrationstests (ohne Netzwerk):**

- MCP-Initialisierung und alle vier Werkzeuge über `mcp.Client`, in-process
- echter stdio-Subprozess, so wie Claude Code den Server startet
- echter Uvicorn-Server auf 127.0.0.1 mit MCP-Streamable-HTTP-Client und Bearer-Token
- OAuth-App mit Protected-Resource-Metadata und Token-Prüfung über HTTP

**Nicht überprüfbar in dieser Umgebung:**

- echte Storage Share: keine Zugangsdaten, nicht erlaubt
- echte Claude-Code-App, Claude Web, ChatGPT und Claude Code Web
- echter Identity Provider
- systemd- und Caddy-Beispiele auf einem echten Server
- Tailscale-Funnel-Syntax

## F. Kompatibilität

| Client | Nachgewiesener Umfang |
|---|---|
| Claude Code lokal (stdio, macOS) | Implementiert. Automatisiert getestet mit echtem stdio-Subprozess und MCP-Handshake (Linux; CI zusätzlich macOS). **Nicht** mit der echten App und nicht gegen die echte Storage Share getestet. |
| Claude Code CLI remote (`--transport http --header`) | Implementiert (static). Automatisiert getestet mit Uvicorn und MCP-HTTP-Client. Kein reales Deployment. |
| Claude Web (Custom Connector) | Serverseitig implementiert (static, oauth). Laut Hilfe-Center sind OAuth, keine Anmeldung und feste Header möglich. Braucht einen öffentlichen HTTPS-Endpunkt. **Nicht verifiziert.** |
| ChatGPT Web (Developer Mode) | Serverseitig implementiert (oauth). Braucht einen passenden Tarif, öffentliches HTTPS und einen Identity Provider. **Nicht verifiziert.** |
| Claude Code Web (Cloud) | Erreicht nur öffentliche Endpunkte, keinen Server auf dem Mac. **Nicht verifiziert.** |

## G. Bekannte Einschränkungen

- Ein öffentlicher Remote-Betrieb braucht einen erreichbaren HTTPS-Endpunkt. Die Storage Share kann den Dienst nicht hosten. Kostenlose Wege (eigener vorhandener Server, Tailscale Funnel) sind dokumentiert, aber nicht getestet.
- Für Claude Web mit OAuth bzw. für ChatGPT braucht ihr einen externen Identity Provider mit RS256-JWT-Access-Tokens (nicht im Projekt enthalten).
- Keine Volltextsuche, keine OCR, keine Formate `.doc`, `.xls`, `.pptx`, `.odt`. DOCX ohne Kopf- und Fußzeilen, Textfelder und Kommentare.
- Dateinamen mit Kommas lassen sich nicht in der Allowlist konfigurieren. Dateien mit `%XX` im Namen sind sichtbar, aber nicht lesbar.
- Die GitHub-Actions-Ergebnisse stehen erst nach dem Push fest.

## H. Release-Übersicht

```
levuvo-nextcloud-mcp/
├── .github/workflows/ci.yml        # Lint, Lockfile-Check, Tests 3.11–3.13 + macOS, pip-Lockfile-Job
├── src/levuvo_nextcloud_mcp/
│   ├── __init__.py                 # einzige Versionsquelle (0.5.0)
│   ├── __main__.py
│   ├── errors.py                   # neu: Fehlerhierarchie
│   ├── policy.py                   # neu: zentrale Pfad-Policy
│   ├── settings.py                 # Konfiguration, .env-Laden
│   ├── webdav.py                   # read-only WebDAV-Client
│   ├── extractors.py               # Text/PDF/DOCX/XLSX
│   ├── server.py                   # MCP-Server, CLI, HTTP-App
│   ├── remote_settings.py
│   ├── static_bearer.py
│   └── jwt_tokens.py
├── tests/                          # 15 Testmodule, conftest mit Fake-Nextcloud
├── deploy/                         # systemd- und Caddy-Beispiele
├── docs/                           # REMOTE.md, TROUBLESHOOTING.md, dieser Bericht
├── README.md · SECURITY.md · CHANGELOG.md · .env.example · LICENSE (MIT)
├── pyproject.toml
└── uv.lock · requirements.lock · requirements-dev.lock
```

Versionen: Paket 0.5.0, MCP SDK 2.3.0, Python ≥ 3.11.

**Kurzinstallation (macOS):**

```bash
brew install uv
git clone https://github.com/peterkarlhuber/levuvo-nextcloud-mcp && cd levuvo-nextcloud-mcp
uv sync --extra dev
cp .env.example .env && chmod 600 .env   # Werte eintragen
.venv/bin/levuvo-nextcloud-mcp --check-config
.venv/bin/levuvo-nextcloud-mcp --check-nextcloud
claude mcp add --scope user --transport stdio levuvo-nextcloud \
  --env LEVUVO_MCP_ENV_FILE="$(pwd)/.env" -- "$(pwd)/.venv/bin/levuvo-nextcloud-mcp"
```

## I. Offene Punkte für v0.6

1. **Realer Abnahmetest** gegen die Storage Share mit Testordner: NFC/NFD, Groß-/Kleinschreibung, User-ID und `--check-nextcloud`. Danach Erkenntnisse in den Tests nachziehen.
2. **Entscheidung zum Remote-Weg** (vorhandener Server oder Tunnel) und zum Identity Provider, danach ein End-to-End-Test mit Claude Web.
3. Optional, wenn Bedarf entsteht: Volltextsuche über die Nextcloud-Such-API (statt eigenem Index).
