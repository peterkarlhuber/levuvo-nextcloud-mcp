# Sicherheit – Levuvo Nextcloud MCP v0.4

## Sicherheitsgrenzen

1. **Nextcloud-Konto:** ausschließlich separates `agent.levuvo` ohne Adminrechte, App-Passwort und schreibgeschützt geteilte Testordner. Das technische Benutzerkonto kann einen eigenen persönlichen Schreibbereich haben; deshalb keine pauschalen Nextcloud-Zugriffsrechte und nur explizite Datei-/Ordner-Allowlist.
2. **MCP-Tools:** nur 4 Lesewerkzeuge. Nextcloud-HTTP-Client sendet nur `GET` und `PROPFIND`, folgt keinen HTTP-Redirects und prüft TLS-Zertifikate.
3. **Datei-/Ordner-Allowlist und Denylist:** von der Client-Anfrage unabhängig an jeder WebDAV-Operation geprüft. Dateien sind einzeln freigebbar (`file:`), Ordner mitsamt Unterstruktur (`dir:`). `NEXTCLOUD_DENIED_PATHS` sperrt Ausnahmen (Deny hat immer Vorrang). Bei einzeln freigegebenen Dateien ohne Präfix wird der tatsächliche WebDAV-Typ geprüft. Keine absoluten Pfade, `..`, Backslashes oder Grenzüberschreitung durch `OrdnerX`.
4. **Limits:** Max. 8 MB Datei-Download voreingestellt, begrenzte Ausgabe und Dateinamensuche. Keine OCR, keine Shell-Ausführung von Datei-Inhalten.
5. **Remote-Zugriff:** nur Loopback-Listener; TLS am Reverse-Proxy; `static` verbietet jede HTTP-Anfrage ohne gültigen Bearer-Token. `oauth` verifiziert JWT + MCP SDK Autorisierung.
6. **Host/Origin:** HTTP-Betrieb hat Host-Allowlist (`mcp.levuvo.com`, localhost); keine Browser-Origins freigegeben. Reverse-Proxy muss Host und Authorization Header erhalten.
7. **Secrets:** `.env` (`chmod 600`), keine Schlüssel in Git, Screenshots, Ausgaben, Logs oder Cloud-Dateien. `.env.example` enthält nur Platzhalter. Secrets mindestens nach Verdacht rotieren.
8. **Datenverarbeitung:** Claude/ChatGPT können Inhalte, die der MCP-Server zurückliefert, zur Antwortgenerierung verarbeiten. Für Kundendaten sind Freigabe, Verträge, Datenschutz sowie Produkt-/Workspace-Richtlinien zu prüfen.
9. **Prompt-Injection:** Dokumente sind untrusted. Das MCP-Werkzeug liefert ausschließlich Daten; dennoch ist das Sprachmodell möglicherweise von schädlichen Anweisungen im Dokument beeinflussbar. Keine automatischen Schreib-/Netzwerk-/Ausführungsrechte in denselben Agenten hinzufügen.
10. **Betrieb:** TLS, Updates, Backups der Konfiguration ohne Secret-Exfiltration, Logging ohne Inhalte und Rate-Limiting am Proxy (optional) sind Betriebsaufgaben. Kein öffentlicher Produktivbetrieb ohne Sicherheitsprüfung.

## Authentifizierungsmodi

| Modus | Geeignet für | Einschränkung |
|---|---|---|
| `stdio` | Lokaler Claude Code | Alle Sicherheit liegt beim lokalen Benutzerprozess; kein HTTP-Token nötig |
| `static` | Kleine Testinstallation mit Claude Web | Gemeinsamer langlebiger Schlüssel; keine Benutzeridentitäten/Logout oder Token-Ablauf, nicht OAuth |
| `oauth` | Zukünftige Team- und ChatGPT-Integration | Externer IdP nötig; nur RS256 JWT-Access-Tokens; echte Interoperabilität noch nicht getestet |

**Kein Multi-Tenant-/Per-User-Nextcloud-Modell:** Alle Remote-Clients nutzen derzeit dasselbe technische Nextcloud-App-Passwort. OAuth authentifiziert nur den MCP-Client; es ändert **nicht** die Nextcloud-Freigaberechte pro eingeloggtem Claude-/ChatGPT-Benutzer. Für SaaS später Benutzerzuordnung, separierte Nextcloud-Credentials und Auditing ergänzen.

## Vor dem produktiven Einsatz überprüfen

- [ ] App-Passwort separat und eingeschränkt, Testordner read-only freigegeben
- [ ] Host und TLS geprüft; Port 8765 nur Loopback
- [ ] Anfrage ohne/falsches Token ergibt 401
- [ ] Datei- und Ordnerfreigaben geprüft; Deny-Pfade weder aufgelistet noch gesucht noch gelesen
- [ ] Pfade außerhalb Allowlist abgelehnt
- [ ] Kein Logeintrag mit Passwort, Token oder Dokumenteninhalt
- [ ] Vertrauenswürdige IdP-/OAuth-Konfiguration, falls verwendet
- [ ] Unternehmensfreigabe für externe Modellverarbeitung
- [ ] Keine ungewollte Verfügbarkeit für weitere Workspace-Mitglieder

## Restrisiken der Berechtigungspolitik

- Eine breit freigegebene Ordnerwurzel lässt automatisch **neu angelegte** Dateien und Unterordner zu. Eine Denylist ist keine Klassifizierung vertraulicher Dokumente.
- Eine ausgeschlossene Datei/Ordner wird zwar aus **MCP-Ausgaben** entfernt, die Nextcloud-Antwort für die Auflistung des übergeordneten erlaubten Ordners kann die ausgeschlossenen Namen bereits enthalten. Diese Daten werden nicht an das Modell zurückgegeben.
- `file:` und `dir:` sind für strenge Typkontrolle empfehlenswert; unbearbeitete Pfade werden anhand tatsächlicher WebDAV-Metadaten klassifiziert.
- Metadatenänderungen, Shares und Rechte müssen mit dem technischen Nextcloud-Konto regelmäßig überprüft werden.
- MCP-Token/OAuth schränken Nextcloud nicht individuell pro Claude- oder ChatGPT-Anwender ein; alle Benutzer dieses Dienstes teilen die konfigurierte technische Identität.
