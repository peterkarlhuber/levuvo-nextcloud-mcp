# Changelog

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
