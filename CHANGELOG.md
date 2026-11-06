# Changelog

## 0.5.0 – 2026-11-06

### Breaking changes

- Ausschlüsse in `NEXTCLOUD_DENIED_PATHS` mit Präfix (`dir:`, `file:`) werden jetzt wie Freigaben ausgewertet, statt als Teil des Pfads gelesen zu werden.
- Strengere Prüfung beim Start: Duplikate (auch in anderer Schreibweise), wirkungslose Ausschlüsse, vollständig gesperrte Freigaben, Einträge unter `file:`-Freigaben und unbekannte Präfixe (`DIR:`, `folder:` …) sind Startfehler (Exit-Code 2).
- URL-kodierte Pfade (z. B. `%20`) werden abgelehnt; Pfade unkodiert angeben.
- `read_file` liefert bei Textdateien zusätzlich das Feld `encoding`.
- `create_mcp(settings, …)` und `build_http_app(settings, remote, …)` erwarten jetzt ein `Settings`-Objekt.

### Sicherheit

- SEC-01: Ausschlüsse verstehen dieselben Präfixe `dir:`/`file:` wie Freigaben (in v0.4 wurde `dir:X` als wörtlicher Pfad gelesen und war damit wirkungslos); unbekannte Präfixe sind Startfehler.
- SEC-02: Zentrale Pfad-Policy (`policy.py`) mit Unicode-NFC-Normalisierung aller Pfade (Konfiguration, Anfrage, Nextcloud-`href`). Freigaben gelten exakt, die Normalisierung erweitert nie den Zugriff.
- SEC-03: Ausschlüsse werden vorsichtig verglichen (NFKC, Groß-/Kleinschreibung, Punkte/Leerzeichen am Abschnittsende) und sperren immer den ganzen Teilbaum; Vorrang vor Freigaben.
- SEC-04: SECURITY.md beschreibt die minimalen Rechte des technischen Nextcloud-Kontos (schreibgeschützte Freigaben, kein eigener Home-Ordner in der Allowlist, App-Passwort-Rotation, Quota ist keine Zugriffskontrolle); `--check-nextcloud` meldet Schreibrechte des Kontos.
- SEC-05: Wirkungslose (außerhalb jeder Freigabe), doppelte oder widersprüchliche Einträge verhindern den Start (fail closed).
- SEC-06: `PROPFIND`-Antworten werden gestreamt und bei 2 MB abgebrochen; DTDs/Entities in XML verboten.
- SEC-07: JWKS-Schlüssel werden 5 min gecacht; ein unbekannter `kid` löst prozessweit höchstens eine Aktualisierung pro 60 s aus. Nur RS256, `typ` geprüft, ID-Tokens und Tokens über 8 KB abgelehnt.
- SEC-08: OAuth: `AccessToken` übernimmt die echte Audience und `client_id`/`azp`; die SDK-Ressourcenprüfung greift, wenn `MCP_OAUTH_AUDIENCE` = `MCP_PUBLIC_URL`.
- SEC-09: Erwartete Fehler werden nicht mehr als Absturz mit Traceback geloggt; Fehlermeldungen enthalten keine Zugangsdaten; `Settings`/`RemoteSettings` zeigen Geheimnisse nicht in `repr`.
- Zusätzlich: Steuer-/Formatzeichen und URL-kodierte Sequenzen in Pfaden werden abgelehnt; `href`-Werte werden pro Abschnitt genau einmal dekodiert (ein kodierter `/` erzeugt keine neue Ebene), fremde Hosts/Benutzer verworfen; ausgeschlossene und nicht freigegebene Pfade liefern dieselbe Meldung; Warnung bei für andere lesbarer `.env`; statischer Token mit Groß-/Kleinschreibung-unabhängigem `Bearer`-Schema.

### MCP

- MCP-01: Erwartete Fehler (nicht freigegeben, nicht gefunden, Format, Limits, Nextcloud-Fehler) kommen als MCP-Werkzeugfehler (`ToolError`) mit deutscher Meldung beim Client an; unerwartete Abstürze nur mit allgemeiner Meldung.
- MCP-02: Alle Werkzeuge mit `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false` und Titel.
- MCP-03: Parametergrenzen im JSON-Schema (pydantic `Field`); Werkzeuge liefern zusätzlich strukturierte Ergebnisse.
- MCP-04: Client-Kompatibilität ehrlich dokumentiert (README, docs/REMOTE.md), inkl. Korrektur: Claudes Connector-Oberfläche bietet laut Hilfe-Center feste Request-Header an (mit diesem Server nicht verifiziert).
- MCP-05: Abhängigkeiten gepinnt (`mcp>=2.3,<2.4`) und über Lockfiles reproduzierbar; SDK-API gegen MCP SDK 2.3.0 getestet.

### WebDAV und Dokumente

- WD-01: Neue Variable `NEXTCLOUD_USER_ID`; fehlt der angefragte Pfad in der WebDAV-Antwort, erklärt die Fehlermeldung die mögliche Ursache.
- WD-02: Ein gepoolter HTTPS-Client pro Prozess (Keep-Alive, max. 8 Verbindungen) statt pro Aufruf; Typprüfung freigegebener Einträge 5 min gecacht.
- WD-03: Dateinamensuche als Breitensuche mit max. 4 parallelen Anfragen (gemessen: 61 Ordner bei 20 ms Latenz deutlich unter 0,9 s statt ≥ 1,2 s sequenziell).
- WD-04: Textdateien: UTF-8 (mit/ohne BOM), UTF-16 mit BOM, Fallback Windows-1252 (Feld `encoding`); binäre Inhalte abgelehnt.
- WD-05: Dokumentauswertung im Worker-Thread (max. 2 parallel), blockiert den Event-Loop nicht.
- WD-06: DOCX mit Absätzen und Tabellen in Dokumentreihenfolge; klare Meldungen bei beschädigten DOCX/XLSX/PDF; Hinweis bei PDFs ohne Text (keine OCR).
- Zusätzlich: Meldungen für 401, 403, 404, 429 (mit `Retry-After`), 3xx, 5xx und Zeitüberschreitung.

### Konfiguration

- CFG-01: Neue Variable `LEVUVO_MCP_ENV_FILE`; sonst `.env` neben `pyproject.toml` einer Quellcode-Installation, sonst nur Umgebungsvariablen. Umgebungsvariablen haben Vorrang.
- CFG-02: Installationsanleitung für macOS mit Python-Versionsprüfung, uv und pip-Lockfile-Weg.
- CFG-03: Präfixe nur klein geschrieben; abweichende Schreibweisen sind Startfehler statt stiller Pfadteil.
- Neue CLI-Optionen `--check-config`, `--check-nextcloud` und `--version`; Konfigurationsfehler mit Exit-Code 2 ohne Traceback.

### Qualität

- QA-01: Tests über einen echten MCP-Client (in-process, stdio-Subprozess und Streamable HTTP über Uvicorn) für alle vier Werkzeuge.
- QA-02: Gezielte Sicherheits- und Grenzfalltests (Unicode NFC/NFD, Groß-/Kleinschreibung, Präfixe, Traversal, URL-Kodierung, Sonderzeichen, XML-Angriffe, HTTP-Fehler, Timeouts, Limits, Parallelität); unspezifische `pytest.raises(Exception)` ersetzt.
- QA-03: GitHub-Actions-CI (Lockfile-Check, `ruff`, `pytest` mit Abdeckung unter Python 3.11–3.13 und macOS, pip-Installation aus Hash-Lockfile); `uv.lock`, `requirements.lock`, `requirements-dev.lock`.
- Eine Versionsquelle (`__init__.py`, dynamisch in `pyproject.toml`), Test auf Konsistenz.

### Remote

- OPS-02: Gehärtete Beispiele für systemd und Caddy; Uvicorn ohne Server-Header und Access-Log, `limit_concurrency=32`.

### Dokumentation

- README, SECURITY.md und `.env.example` überarbeitet; neu `docs/REMOTE.md` (Remote-Optionen ohne Pflicht-Hostingkosten) und `docs/TROUBLESHOOTING.md`; ehrliche Kompatibilitätstabelle.

## 0.4.0 – 2026-11-05

- Einheitliche Konfigurationsnamen: `NEXTCLOUD_ALLOWED_PATHS` und `NEXTCLOUD_DENIED_PATHS`; kein Alias für alte Namen.
- `NEXTCLOUD_ALLOWED_PATHS`: beliebige Mischung aus mehreren Dateien und Ordnern, komma-getrennt.
- Explizite `file:`- (genau eine Datei) und `dir:`-Typangaben; unveränderte Pfade werden per WebDAV automatisch erkannt.
- `NEXTCLOUD_DENIED_PATHS`: optionale, komma-getrennte Ausnahmen; ausgeschlossene Teilbäume; Deny vor Allow.
- `list_files("")` listet erlaubte Dateien und Ordner mit echten Metadaten auf; einzeln freigegebene Dateien werden in `search_files` durch ihren Namen gefunden.
- Ausgeschlossene Pfade werden vor der Netzwerkanfrage abgelehnt bzw. aus Verzeichnislisten und Suchergebnissen gefiltert.
- Typkontrolle: `file:` darf nicht auf einen Ordner und `dir:` nicht auf eine Datei zeigen.
- Lokale Offline-Tests, einschließlich neuer Berechtigungs-, Metadaten-, Listen- und Suchtests.
- Kein zusätzliches Schreibwerkzeug, unveränderte lokale/Remote-Architektur aus v0.2.

## 0.2.0 – 2026-11-05

- Lokalen Claude-Code-Modus (`stdio`) beibehalten.
- Remote-MCP über Streamable HTTP (`--transport http`) hinzugefügt.
- Remote-HTTP bindet ausschließlich auf `127.0.0.1`.
- Zwei Authentifizierungswege: fester Bearer-Token für klein begrenzte Tests; OAuth-Ressourcenserver mit externem RS256-JWT-IdP.
- Host-/Origin-Allowlist, stateless HTTP, JSON-Antworten und Request-Body-Limit.
- Caddy- und systemd-Beispiel sowie vollständige Einrichtungs- und Sicherheitshinweise.
- Bestehende Dokumenten-/Ordnerfunktionen unverändert; nur vier Lesewerkzeuge.
- 31 Offline-Tests bestanden; echte MCP-SDK- und Online-Integration steht noch aus.
