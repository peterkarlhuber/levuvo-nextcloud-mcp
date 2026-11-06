# Sicherheit – Levuvo Nextcloud MCP 0.5

Dieses Dokument beschreibt, wovor der Server schützt, wovor nicht, und was auf der Nextcloud-Seite und im Betrieb zu tun ist.

Sicherheitsprobleme bitte nicht öffentlich als Issue melden, sondern direkt an die Projektverantwortlichen der Levuvo.

## Bedrohungsmodell und Grenzen

**Schützenswert:** Dateien in der Storage Share, das App-Passwort des technischen Kontos, der Remote-Token bzw. OAuth-Konfiguration.

**Angenommene Angreifer bzw. Risiken:**

1. Ein Sprachmodell, das durch Dokumentinhalte (Prompt-Injection) oder Fehlbedienung versucht, Pfade außerhalb der Freigaben zu lesen.
2. Fehler oder Tippfehler in der Konfiguration, die mehr freigeben als gewollt.
3. Unbefugte im Internet, falls ein Remote-Endpunkt öffentlich ist.
4. Manipulierte oder sehr große Antworten bzw. Dokumente (XML-Angriffe, Zip-Bomben, riesige Ordner).

**Nicht abgedeckt:**

- Ein kompromittierter Mac oder Server, auf dem der Dienst läuft. Wer dort die `.env` lesen kann, hat das App-Passwort und damit **alle** Rechte des technischen Kontos in Nextcloud – unabhängig von diesem Server.
- Was der KI-Anbieter mit gelesenen Inhalten macht.
- Rechte pro Endbenutzer: Alle Clients nutzen dieselbe technische Nextcloud-Identität.

## Zwei getrennte Ebenen

| Ebene | Wer erzwingt | Was |
|---|---|---|
| **MCP-Server** | dieser Code | Allow-/Denylist, nur `GET`/`PROPFIND`, keine Schreibwerkzeuge, Größen- und Mengenlimits, Remote-Authentifizierung |
| **Nextcloud** | Storage Share | Welche Dateien das Konto überhaupt sieht (Freigaben, Gruppenordner, eigener Home-Ordner) und was es dort darf |

Ein Pfad ist nur lesbar, wenn **beide** Ebenen ihn zulassen.

**Wichtig:** Ein Nextcloud-App-Passwort hat die vollen Rechte des Kontos; es lässt sich nicht auf „nur lesen“ beschränken. Das technische Konto hat außerdem normalerweise einen eigenen, beschreibbaren Home-Ordner. Dass nichts geschrieben wird, garantiert also allein der MCP-Code. Deshalb muss das Konto auf der Nextcloud-Seite so wenig wie möglich dürfen.

## Nextcloud-Seite: minimale Rechte

1. **Eigenes Konto** `agent.levuvo` anlegen – ohne Admin- und ohne Gruppen-Admin-Rechte, nicht in Gruppen mit beschreibbaren Gruppenordnern.
2. **Nur schreibgeschützte Freigaben empfangen:** Ordner werden von einem anderen Konto an `agent.levuvo` geteilt, dabei *Bearbeiten*, *Erstellen*, *Löschen* und *Weiterteilen* abwählen.
3. **Nie den eigenen Home-Bereich freigeben:** In `NEXTCLOUD_ALLOWED_PATHS` nur empfangene Freigaben eintragen, keine Ordner, die `agent.levuvo` selbst gehören (dort hätte das Konto volle Rechte).
4. **Prüfen:** `levuvo-nextcloud-mcp --check-nextcloud` ausführen. Es zeigt pro Freigabe die Nextcloud-Rechtebuchstaben und warnt bei `W` (schreiben), `C`/`K` (Datei/Ordner anlegen), `D` (löschen), `N` (umbenennen), `V` (verschieben). Ein `R` (weiterteilen) wird nicht als Schreibrecht gewertet, sollte aber ebenfalls fehlen. Die Prüfung nach jeder Änderung an Freigaben wiederholen.
5. **App-Passwort:** nur für diesen Dienst erzeugen, nur in `.env` speichern (`chmod 600`), nie in Git, Chats, Screenshots oder Tickets. Bei Verdacht sofort in Nextcloud unter *Einstellungen → Sicherheit → Geräte & Sitzungen* widerrufen und neu erstellen; sonst regelmäßig rotieren.
6. **Brute-Force-Schutz:** Nextcloud bremst nach fehlgeschlagenen Anmeldungen. Falsche Zugangsdaten in einer Schleife (z. B. durch Neustarts) können das Konto bzw. die IP verlangsamen; bei gehäuften 401/429 erst die Konfiguration korrigieren.

### Zum Speicherkontingent (Quota)

Ein Kontingent von 0 B ist **keine** Sicherheitsmaßnahme und wird hier nicht empfohlen:

- Das Kontingent begrenzt den belegten Speicher im **eigenen** Speicher des Kontos.
- Dateien in empfangenen Freigaben zählen zum Kontingent des **Eigentümers**. Ein Kontingent beim technischen Konto verhindert also kein Schreiben in beschreibbare Freigaben.
- Ein Kontingent von 0 B verhindert das Hochladen von Dateiinhalten in den eigenen Home-Bereich, ist aber keine Zugriffskontrolle: Ordner oder leere Dateien und beschreibbare Freigaben bleiben möglich; das Verhalten kann je nach Nextcloud-Version abweichen.

Ein kleines Kontingent ist höchstens eine optionale Schadensbegrenzung. Maßgeblich sind schreibgeschützte Freigaben plus MCP-Allowlist. Das tatsächliche Verhalten bei Bedarf auf der Storage Share selbst prüfen.

## Was der MCP-Server erzwingt

- **Nur lesen:** Der HTTP-Client lässt nur `GET` und `PROPFIND` zu; andere Methoden werden schon im Code abgewiesen. Es gibt keine Werkzeuge zum Schreiben, Löschen, Verschieben oder Teilen.
- **Pfadprüfung vor jeder Anfrage:** Jeder Pfad wird normalisiert (NFC) und gegen die Policy geprüft, bevor eine Nextcloud-Anfrage entsteht. Abgelehnt werden absolute Pfade, Backslashes, `.`/`..`, Steuer- und Formatzeichen (z. B. Bidi-Overrides, Zero-Width), URL-kodierte Sequenzen und überlange Pfade (1024 Zeichen, 255 pro Abschnitt).
- **Allow exakt, Deny vorsichtig:** Freigaben gelten nur für exakt passende Pfade (nach NFC, Groß-/Kleinschreibung zählt). Ausschlüsse greifen auch bei anderen Schreibweisen (NFKC, Groß-/Kleinschreibung, Punkte/Leerzeichen am Abschnittsende), immer für den ganzen Teilbaum und immer mit Vorrang. Ausgeschlossene und nicht freigegebene Pfade liefern dieselbe Meldung.
- **Widersprüche verhindern den Start:** leere Freigabeliste, Duplikate, wirkungslose Ausschlüsse, vollständig gesperrte Freigaben, Einträge unter `file:`-Freigaben, unbekannte Präfixe.
- **Typprüfung:** `dir:`/`file:` werden gegen den echten Nextcloud-Typ geprüft; Pfade unter einer Freigabe ohne Präfix sind nur erreichbar, wenn diese tatsächlich ein Ordner ist.
- **Antworten von Nextcloud:** keine Weiterleitungen (Zugangsdaten gehen nie an ein anderes Ziel), TLS-Prüfung aktiv, Proxy-/`.netrc`-Einstellungen der Umgebung werden ignoriert. XML wird mit `defusedxml` und verbotener DTD gelesen. `href`-Einträge fremder Hosts oder außerhalb des Benutzerpfads werden verworfen; jeder Abschnitt wird genau einmal dekodiert.
- **Limits gegen Überlast:** Verzeichnisantwort max. 2 MB und 2000 Einträge, Download max. `NEXTCLOUD_MAX_FILE_BYTES` (Standard 8 MB, gestreamt), Suche max. 100 Ordner und 4 parallele Anfragen, Textausgabe max. 30000 Zeichen, Dokumentauswertung in max. 2 parallelen Worker-Threads, PDF max. 40 Seiten, XLSX max. 10 Blätter/1000 Zeilen/60 Spalten, Zip-Bomben-Prüfung für Office-Dateien. Remote zusätzlich: Request-Body 128 KiB, 32 gleichzeitige Verbindungen.
- **Keine Ausführung:** keine Makros, keine Formelberechnung, keine OCR, keine Shell.

## Prompt-Injection

Dokumentinhalte sind nicht vertrauenswürdig. Ein Dokument kann Anweisungen enthalten, die das Modell befolgt („lies auch Ordner X“, „schicke den Inhalt an …“). Der Server liefert nur Daten und kennzeichnet sie in jeder `read_file`-Antwort als nicht vertrauenswürdig; die Allowlist begrenzt, was erreichbar ist. Er kann das Modell aber nicht daran hindern, Gelesenes anderweitig zu verwenden.

Daher diesen Server **nicht** im selben Agenten mit Werkzeugen kombinieren, die schreiben, Netzwerkanfragen senden, E-Mails verschicken oder Code ausführen – oder solche Werkzeuge nur mit Bestätigung pro Aufruf zulassen.

## Datenabfluss

Was `read_file`, `list_files` usw. zurückgeben, geht an den KI-Anbieter (Anthropic, OpenAI) und wird dort verarbeitet. Vor der Freigabe von Kunden-, Personal- oder Finanzdaten Datenschutz (DSGVO), Verträge und die Richtlinien des jeweiligen Tarifs/Workspaces prüfen.

## Protokollierung

- Der eigene Code protokolliert keine Passwörter, Tokens, Authorization-Header oder Dokumentinhalte. Fehlermeldungen an den Client enthalten keine Zugangsdaten.
- Logs gehen auf stderr, Stufe `WARNING`. Bei unerwarteten Abstürzen schreibt das MCP-SDK einen Traceback auf stderr; der Client sieht nur eine allgemeine Meldung.
- Im HTTP-Modus ist das Access-Log von Uvicorn abgeschaltet. Der Reverse-Proxy darf keine Authorization-Header und keine Bodies loggen.

## Remote-Authentifizierung

| Modus | Geeignet für | Eigenschaften und Grenzen |
|---|---|---|
| `stdio` | lokales Claude Code | Kein Netzwerk-Port. Sicherheit = Sicherheit des lokalen Benutzerkontos. |
| `static` | kleiner, vertrauenswürdiger Kreis (z. B. Claude Code mit `--header`) | Ein gemeinsamer, langlebiger Token für alle Routen. Vergleich in konstanter Zeit, Schema `Bearer` ohne Rücksicht auf Groß-/Kleinschreibung, genau ein Authorization-Header. Kein Ablauf, keine Benutzer, kein Logout. |
| `oauth` | spätere Anbindung von Claude Web / ChatGPT | Nur Resource Server, kein eigener Login. Externer Identity Provider nötig. Akzeptiert nur RS256-signierte JWT-Access-Tokens mit `iss`, `aud`, `sub`, `exp` und Scope (`scope` oder `scp`); `typ` muss fehlen, `JWT` oder `at+jwt` sein; ID-Tokens und Tokens über 8 KB werden abgelehnt. JWKS wird 5 Minuten gecacht; ein unbekannter `kid` löst höchstens eine Aktualisierung pro 60 s aus. Das SDK stellt Protected Resource Metadata unter `/.well-known/oauth-protected-resource/mcp` bereit. Ist `MCP_OAUTH_AUDIENCE` gleich `MCP_PUBLIC_URL`, prüft das SDK zusätzlich die Ressourcenbindung. Mit realen Identity Providern und Clients nicht getestet. |

Der Remote-Token ist ein eigenes Geheimnis und darf nie das Nextcloud-App-Passwort sein.

## Checkliste vor jedem öffentlichen Betrieb

Ein öffentlicher Endpunkt ist erst nach dieser Liste **und** erfolgreichen Tests mit dem realen Client vertretbar.

- [ ] Technisches Konto ohne Admin-/Gruppen-Admin-Rechte, nur schreibgeschützte Freigaben, `--check-nextcloud` ohne Warnung
- [ ] Freigaben minimal; keine vertraulichen Bereiche ohne ausdrückliche Entscheidung
- [ ] `.env` mit `chmod 600` (bzw. nur für den Dienstbenutzer lesbar), nicht im Git
- [ ] Remote-Token zufällig (z. B. `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`) oder OAuth mit vertrauenswürdigem Identity Provider
- [ ] Port 8765 nur auf `127.0.0.1`; von außen nicht erreichbar (geprüft)
- [ ] TLS gültig; Proxy reicht `Host` und `Authorization` unverändert durch
- [ ] Anfrage ohne bzw. mit falschem Token ergibt `401`
- [ ] Fremder `Host`-Header wird abgewiesen
- [ ] Ausgeschlossene Pfade erscheinen weder in Listen noch in Suchen und sind nicht lesbar
- [ ] Logs (Dienst und Proxy) ohne Token, Passwort und Dokumentinhalt
- [ ] Dienst läuft als eigener Benutzer ohne Root (siehe `deploy/`)
- [ ] Freigabe der Geschäftsführung für die Verarbeitung durch den KI-Anbieter
- [ ] Connector nicht ungewollt für weitere Workspace-Mitglieder sichtbar
- [ ] Verfahren für Rotation und Widerruf von App-Passwort und Token festgelegt

## Restrisiken

- **Gemeinsame Identität:** Alle Remote-Benutzer greifen über dasselbe technische Konto zu. OAuth authentifiziert den MCP-Client, ändert aber nichts an den Nextcloud-Rechten pro Person. Es gibt kein Audit pro Benutzer.
- **Neue Dateien:** Eine Ordnerfreigabe gilt auch für später angelegte Dateien. Ein Ausschluss ist keine Klassifizierung.
- **Überblockieren:** Der vorsichtige Ausschlussvergleich kann auch Pfade sperren, die nur ähnlich geschrieben sind (z. B. `Intern` sperrt auch `intern` und `Intern.`). Das ist gewollt.
- **Namen ausgeschlossener Einträge:** Nextcloud liefert sie in der Liste des übergeordneten Ordners mit. Der Server filtert sie heraus und gibt sie nicht an das Modell weiter, sie liegen aber kurz im Arbeitsspeicher.
- **App-Passwort mit vollen Rechten:** Gelangt die `.env` in falsche Hände, nützen alle MCP-Schutzmaßnahmen nichts. Nur die Nextcloud-Seite (schreibgeschützte Freigaben) begrenzt dann den Schaden.
- **Abhängigkeiten:** Parser für PDF/DOCX/XLSX und das MCP-SDK sind Fremdcode. Versionen über die Lockfiles fixieren und regelmäßig aktualisieren.
