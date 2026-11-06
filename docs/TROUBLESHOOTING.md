# Fehlerbehebung

Erste Schritte bei jedem Problem:

```bash
.venv/bin/levuvo-nextcloud-mcp --version
.venv/bin/levuvo-nextcloud-mcp --check-config
.venv/bin/levuvo-nextcloud-mcp --check-nextcloud
claude mcp list
```

`--check-config` zeigt auch, welche Konfigurationsdatei geladen wurde (`config_file`).

## Installation

**`requires a different Python` / `Package requires Python >=3.11`**
Das System-Python von macOS ist oft 3.9. Abhilfe: `brew install python@3.12` und das venv mit `python3.12 -m venv .venv` anlegen, oder `uv sync --extra dev` verwenden (uv besorgt ein passendes Python).

**`--require-hashes`-Fehler bei pip**
Die Lockdatei passt nicht zur Plattform oder wurde verändert. Mit `uv sync --extra dev` installieren oder die Lockdatei neu exportieren lassen.

## Konfiguration

**`Konfigurationsfehler: NEXTCLOUD_URL muss … / NEXTCLOUD_USERNAME fehlt` obwohl `.env` ausgefüllt ist**
Die Datei wurde nicht gefunden. Claude Code startet den Server nicht unbedingt im Projektordner. Abhilfe: `LEVUVO_MCP_ENV_FILE` mit absolutem Pfad setzen (siehe README, `claude mcp add --env …`). Ohne die Variable wird nur `.env` neben `pyproject.toml` einer Quellcode-Installation gelesen. Echte Umgebungsvariablen überschreiben Werte aus der Datei.

**`LEVUVO_MCP_ENV_FILE zeigt auf keine vorhandene Datei`**
Pfad prüfen; `~` wird aufgelöst, relative Pfade beziehen sich auf das Startverzeichnis des Prozesses.

**Warnung „Die Konfigurationsdatei … ist für andere Benutzer lesbar“**
`chmod 600 .env`.

**`NEXTCLOUD_ALLOWED_PATHS ist leer`**
Variable fehlt oder heißt anders. v0.5 kennt nur `NEXTCLOUD_ALLOWED_PATHS` und `NEXTCLOUD_DENIED_PATHS`; ältere Namen wie `NEXTCLOUD_ALLOWED_ROOTS` werden ignoriert.

**`NEXTCLOUD_APP_PASSWORD fehlt oder enthält noch einen Platzhalter`**
Werte, die mit `EIGENES_`, `HIER_`, `CHANGE_ME` oder `<` beginnen, gelten als Platzhalter.

**`unbekanntes Präfix 'DIR:'` (oder `folder:`, `Projekt:` …)**
Nur `dir:` und `file:` in Kleinbuchstaben sind gültig. Beginnt ein Ordnername mit `Wort:`, den Eintrag mit Präfix schreiben: `dir:Projekt:Alpha`.

**`… bezeichnen denselben Pfad`**
Zwei Einträge unterscheiden sich nur in Schreibweise oder Präfix (`dir:Test`, `test`). Einen entfernen.

**`NEXTCLOUD_DENIED_PATHS: '…' liegt unter keiner Freigabe`**
Ein Ausschluss muss innerhalb einer Freigabe liegen, sonst ist er wirkungslos – meist ein Tippfehler im Pfad. Unter einer `file:`-Freigabe kann nichts ausgeschlossen werden.

**`Widersprüchliche Konfiguration: Die Freigabe … ist durch den Ausschluss … vollständig gesperrt`**
Ein Ausschluss deckt eine ganze Freigabe ab (auch in anderer Schreibweise). Einen der beiden Einträge entfernen.

**`… liegt unter der Einzeldatei …`**
Unter einer `file:`-Freigabe kann es keine weiteren Einträge geben.

**`Der Pfad enthält URL-kodierte Zeichen (z. B. %20)`**
Pfade so eintragen, wie sie in Nextcloud angezeigt werden: `dir:05_Projekte/Projekt Alpha`, nicht `Projekt%20Alpha`. Das gilt in `.env` und bei Werkzeugaufrufen.

## Nextcloud

**`Nextcloud-Anmeldung fehlgeschlagen` (HTTP 401)**
Loginname oder App-Passwort falsch, oder das App-Passwort wurde widerrufen. Neues App-Passwort unter *Einstellungen → Sicherheit → Geräte & Sitzungen* erzeugen. Wiederholte Fehlversuche können den Brute-Force-Schutz von Nextcloud auslösen.

**`Nextcloud hat den Zugriff verweigert` (HTTP 403)**
Das Konto hat auf diesen Pfad in Nextcloud keine Leserechte. Freigabe prüfen.

**`Datei oder Ordner nicht gefunden` (HTTP 404)**
Pfad aus Sicht von `agent.levuvo` prüfen: Empfangene Freigaben liegen normalerweise in dessen Wurzelverzeichnis (je nach Nextcloud-Einstellung auch in einem Unterordner) und können dort umbenannt worden sein. Groß-/Kleinschreibung zählt.

**Leere Listen oder `Die WebDAV-Antwort enthält den angefragten Pfad nicht`**
Die WebDAV-Benutzer-ID unterscheidet sich vom Loginnamen (häufig bei Anmeldung per E-Mail-Adresse). `NEXTCLOUD_USER_ID` setzen. Die ID steht in der Nextcloud-Weboberfläche unter *Dateien → Einstellungen → WebDAV* in der angezeigten Adresse (`…/remote.php/dav/files/<ID>/`).

**`Freigabe-Typ widerspricht Nextcloud: '…' ist tatsächlich ein(e) Ordner/Datei`**
`file:` steht vor einem Ordner oder `dir:` vor einer Datei – bei Freigaben oder Ausschlüssen. Präfix korrigieren.

**`Nextcloud begrenzt die Anfragen derzeit (HTTP 429)`**
Nextcloud drosselt. Warten (ggf. angegebene Sekunden) und Suchen mit kleinerem `max_depth` ausführen.

**`Zeitüberschreitung …` / `Verbindung zur Nextcloud fehlgeschlagen (Netzwerk oder TLS)`**
Netzwerk prüfen. Proxy-Einstellungen der Umgebung werden bewusst ignoriert. Bei langsamen Antworten `NEXTCLOUD_TIMEOUT_SECONDS` erhöhen (max. 120).

**`Nextcloud antwortet mit einer Weiterleitung`**
`NEXTCLOUD_URL` stimmt nicht (z. B. `http` statt `https`, falscher Hostname). Weiterleitungen werden aus Sicherheitsgründen nicht verfolgt.

**`Die Nextcloud-Verzeichnisantwort ist zu groß` / `Zu viele Verzeichniseinträge`**
Ordner mit mehr als 2000 Einträgen oder über 2 MB Antwort. Einen Unterordner freigeben bzw. auflisten.

**`--check-nextcloud` warnt vor Schreib-/Löschrechten**
Die Freigabe an `agent.levuvo` ist nicht schreibgeschützt oder es ist ein eigener Ordner des Kontos. Freigabe auf „nur lesen“ ändern (siehe SECURITY.md).

## Dateien lesen

**Umlaute in CSV sind falsch**
Das Feld `encoding` in der Antwort zeigt die erkannte Kodierung. `cp1252` ist typisch für Excel-Exporte unter Windows und wird korrekt dekodiert. Sieht der Text trotzdem falsch aus, hat die Datei eine andere Kodierung (z. B. UTF-16 ohne BOM); die Datei in UTF-8 speichern.

**`Die Datei scheint binär zu sein`**
Die Dateiendung ist ein Textformat, der Inhalt aber nicht. Datei prüfen.

**PDF liefert keinen Text / Hinweis „evtl. gescanntes PDF“**
Es gibt keine OCR. Das PDF vorher mit Texterkennung versehen. Verschlüsselte PDFs werden nicht gelesen. Ab Seite 41 wird nichts mehr verarbeitet.

**Text aus DOCX fehlt**
Gelesen werden nur Absätze und Tabellen des Haupttexts – keine Kopf-/Fußzeilen, Textfelder oder Kommentare.

**XLSX zeigt keine Formelergebnisse oder ist unvollständig**
Es werden nur in der Datei gespeicherte Werte gelesen; Formeln werden nicht berechnet (Datei in Excel speichern, damit Werte vorhanden sind). Limits: 10 Blätter, 1000 Zeilen, 60 Spalten (`truncated: true`).

**`Die Datei überschreitet das Downloadlimit`**
`NEXTCLOUD_MAX_FILE_BYTES` erhöhen (max. 30000000) oder eine kleinere Datei verwenden.

**`Dateiformat … wird nicht unterstützt`**
Unterstützt: Textformate (siehe README), `.pdf`, `.docx`, `.xlsx`. Alte Formate (`.doc`, `.xls`) vorher konvertieren.

**`search_files` findet Inhalte nicht**
Die Suche prüft nur Datei- und Ordnernamen. `complete: false` bedeutet, dass Tiefe, Trefferzahl oder die Grenze von 100 Ordnern erreicht wurde.

## Claude Code

**Server erscheint nicht oder „failed“ in `claude mcp list`**
Absoluten Pfad zu `.venv/bin/levuvo-nextcloud-mcp` prüfen und den Befehl einmal direkt im Terminal mit `--check-config` ausführen. Alten Eintrag mit `claude mcp remove levuvo-nextcloud --scope user` entfernen und neu anlegen.

**Werkzeug meldet nur `Error executing tool …` ohne Details**
Ein unerwarteter Fehler. Details stehen im stderr-Log des Servers (in Claude Code über die MCP-Logs bzw. durch direkten Start im Terminal).

## Remote

**401 trotz Token**
Header muss `Authorization: Bearer <Token>` lauten (genau ein Header, ohne zusätzliche Leerzeichen im Token). Proxy muss den Header weiterreichen.

**421 `Invalid Host header`**
Der Host der Anfrage passt nicht zu `MCP_PUBLIC_URL`. Proxy muss den ursprünglichen `Host` weiterreichen; `MCP_PUBLIC_URL` auf die tatsächliche Domain setzen.

**403 `Invalid Origin header`**
Browser-Anfragen (mit `Origin`-Header) sind nicht zugelassen.

**413 `Request body too large`**
Anfragen über 128 KiB werden abgelehnt.
