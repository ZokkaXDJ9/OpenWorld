# OpenWorld

Lokales Roleplay-Programm mit Welt- und Charakterverwaltung sowie persistenten Chats.
React-Editoren verwalten die Daten; das Backend stellt den
persoenlichen Kontext eines Charakters fuer einen OpenAI-kompatiblen Anbieter zusammen.
Die Oberfläche enthält nur Navigation, Editoren, Status- und Bedienhinweise;
keine Werbebanner oder Produktslogans.
Deutsche Beschriftungen und Fehlermeldungen verwenden echte Umlaute und ß.
Bestehende Profilfeldschlüssel bleiben für gespeicherte Charaktere kompatibel;
ihre Standardbeschriftungen werden mit korrekter Schreibweise angezeigt.

## Download und Start mit einem Doppelklick (Windows)

1. Das ZIP der Veröffentlichung herunterladen und vollständig entpacken.
2. **Start-OpenWorld.bat** doppelt anklicken.
3. Der Starter richtet Abhängigkeiten ein, baut die Oberfläche, aktualisiert das
   lokale Datenbankschema und öffnet OpenWorld im Browser. Ein Startfenster genügt;
   ein separater Vite-Server ist nicht erforderlich.

Fehlendes natives Python 3.12+ und Node.js 22+ versucht der Starter über Windows
Package Manager (`winget`) einzurichten. Dafür sind Internetzugang und gegebenenfalls
die Bestätigung des Windows-Installers erforderlich. Ohne `winget` diese beiden
Programme einmal selbst installieren. Beim ersten Start werden auch die
Python-/npm-Abhängigkeiten heruntergeladen; spätere Starts verwenden die lokale Installation.
Das Backend wird dabei als Python-Paket registriert, sodass auch die mitgelieferten
Tests und Startwege unabhängig vom Aufrufverzeichnis funktionieren.
Vor einem Update einen separat gestarteten Vite-Entwicklungsserver beenden:
Windows kann dessen geladene native npm-Dateien während einer Neuinstallation sperren.
Zum Beenden das Startfenster schließen oder **Ctrl+C** drücken.

Die Veröffentlichung enthält **keine Datenbanken, persönlichen Welten, Chats,
Provider-Schlüssel, lokalen Einstellungen oder installierten Abhängigkeiten**.
Neue lokale Daten entstehen erst beim Start unter `backend\data` und bleiben auf
dem eigenen Rechner. Für KI-Chats anschließend einen lokalen oder kompatiblen
Anbieter in den Einstellungen konfigurieren.

Für Einrichtung ohne Serverstart: `.\Start-OpenWorld.ps1 -PrepareOnly`.
Bei einem belegten Port: `.\Start-OpenWorld.bat -Port 8001`.
Ein schon mit Oberfläche laufendes OpenWorld auf demselben Port wird wieder geöffnet,
ohne einen zweiten Backendprozess zu starten.

## Implementiert

- Welten erstellen, bearbeiten und loeschen.
- Beliebig tiefe Ortsbaeume mit frei waehlbaren Typen, Tags und Zykluspruefung.
- Optionale Charakterprofile, eigene Felder, Aufenthaltsort, Reiseziel und Zustand.
- Typisierte Attribute: Text, Zahl mit optionalen Grenzen, Boolean, Auswahl,
  Mehrfachauswahl, Datum und Referenzen auf Objekte derselben Welt.
- Gerichtete, unabhaengige Beziehungen mit freien Beschreibungen und Attributen.
- Wissenseditor mit objektiven Fakten, Wissen, Ueberzeugungen, Vermutungen,
  Geruechten, Geheimnissen, Erinnerungen und erhaltenen Informationen.
- Persistente Einzelcharakter-Chats, Streaming, Wiederaufnahme, Regenerierung
  und Bearbeitung eigener Nachrichten mit ausdruecklicher Verwerfungsbestaetigung.
- OpenAI-kompatible Provider, einschliesslich Ollama und LM Studio.
- Verschluesselte API-Schluessel, konfigurierbares Modellfenster ohne globale
  8k-/32k-Grenze, eigener Bereich fuer erweiterte Modelleinstellungen.
- SQLite, versionierte Alembic-Migration und automatisierte Akzeptanztests.
- Responsives, helles/dunkles Interface mit Radix UI und TanStack Query.

Alle aktiven Editoraktionen schreiben in die Datenbank. Der
Produktiv-Chat ruft den konfigurierten Anbieter auf; ohne Modell gibt es eine
sichtbare Fehlermeldung statt einer vorgetaeuschten Antwort.

## Architektur und Projektstruktur

```text
OpenWorld\
  Start-OpenWorld.bat    Doppelklick-Starter
  Start-OpenWorld.ps1    Einrichtung, Build und gemeinsamer lokaler Server
  backend\
    app\
      main.py           HTTP-API, Schreibvalidierung, Chat-Lebenszyklus
      models.py         SQLAlchemy-Datenmodelle
      schemas.py        Pydantic-Eingabemodelle und Attributvalidierung
      db.py             Datenbank und Sessionverwaltung
      context.py        Wissensfilterung, Retrieval und Tokenbudget
      provider.py       Providerprotokoll, Streamingadapter, Schluesselverwaltung
    migrations\         Versioniertes Datenbankschema
    tests\              Backendtests und explizite Browser-Testdienste
    requirements-lock.txt
  frontend\
    src\                Navigation, Editoren, Chat, Einstellungen
    e2e\                Vollstaendiger grafischer Eldoria-Akzeptanztest
    package-lock.json
```

Ein FastAPI-Monolith, keine Microservices. SQLAlchemy trennt Datenzugriff und
Provider. JSON-Attribute bleiben portabel; Beziehungen, Orte, Wissen und Nachrichten
besitzen relationale Identitaeten und Fremdschluessel. PostgreSQL ist vorbereitet
durch eine konfigurierbare SQLAlchemy-URL, aber noch nicht zertifiziert.

## Voraussetzungen

- **Natives Windows-Python 3.12 oder neuer**, kein MSYS/Cygwin-Python.
- Node.js 22 und npm.
- Optional: Ollama, LM Studio oder ein anderer OpenAI-kompatibler Anbieter.
- Zwei PowerShell-Terminals nur für die manuelle lokale Entwicklung.

Die folgenden Befehle gehen von `C:\OpenWorld` aus. Python ist auf diesem Rechner
unter `C:\Python312\python.exe` verfuegbar. Bei anderen Installationen den Pfad ersetzen.
Es werden keine Cloud-Dienste fuer die Weltverwaltung benoetigt.

### Installation

```powershell
Set-Location C:\OpenWorld
& C:\Python312\python.exe -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r .\backend\requirements-lock.txt
& .\.venv\Scripts\python.exe -m pip install -e .\backend --no-deps

Set-Location C:\OpenWorld\frontend
npm ci
```

Die Lockdateien fixieren die getesteten Abhaengigkeiten. Fuer bewusst aktualisierte
Backendabhaengigkeiten kann stattdessen `pip install -e 'C:\OpenWorld\backend[dev]'`
verwendet werden; anschliessend Lockdatei und Tests aktualisieren.

### Starten

**Terminal 1:**

```powershell
Set-Location C:\OpenWorld\backend
& ..\.venv\Scripts\python.exe -m alembic upgrade head
& ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2:**

```powershell
Set-Location C:\OpenWorld\frontend
npm run dev
```

Frontend: <http://127.0.0.1:5173>  
API-Dokumentation: <http://127.0.0.1:8000/docs>  
Gesundheitspruefung: <http://127.0.0.1:8000/api/health>

Beide Prozesse mit `Ctrl+C` beenden. Daten bleiben unter `backend\data` erhalten.
`npm run dev` startet ausschliesslich das Frontend, nicht das Python-Backend.
Bei `ECONNREFUSED 127.0.0.1:8000` das Backend in einem zweiten Terminal mit den
obigen Befehlen starten. Eine aktivierte Python-Umgebung allein startet keinen
Server. Bei leeren oder nicht-JSON Proxyantworten zeigt das Frontend den
HTTP-Fehler mit einem Hinweis auf den Backend-Start statt eines JSON-Parserfehlers.
Migrationen vor jedem Start nach einer Schemaaenderung ausfuehren.
`npm run build` erstellt den Frontend-Produktionsbuild; `npm run preview` dient nur
der Vorschau, nicht als selbststaendiger API-Server.

### Erster Benutzerablauf

1. **Meine Welten** → Neue Welt → Namen/Beschreibung speichern.
2. Welt oeffnen → **Welteditor** → Orte anlegen; Eltern und eigene Felder waehlen.
3. **Charaktere** → mindestens einen Charakter erstellen; optional Profil und Ort setzen.
4. **Beziehungen** → gerichtete Beziehung mit eigenen Werten erstellen.
5. **Wissen & Erinnerungen** → geheime Weltfakten und individuelles Wissen getrennt anlegen.
6. **Einstellungen** → Base-URL, Modell und gegebenenfalls API-Schluessel speichern.
7. **Chats** → Charakter auswaehlen → Neues Gespraech → Nachricht senden.

### Orte verschieben und ordnen

Im **Welteditor** lassen sich Orte am Griff oder an ihrer Zeile ziehen:

- Oberhalb bzw. unterhalb der Mitte einer Zielzeile: davor bzw. danach einordnen.
- Während des Ziehens nach rechts oder links bewegen: ein- bzw. ausrücken.
  Der Baum zeigt den verschobenen Bereich sofort an der vorgeschlagenen Position
  und Hierarchieebene. Bestehende Unterorte ziehen mit um.
- Auf den Weltnamen ziehen: zurück auf die oberste Ebene, ans Ende der Liste.
- Es gibt keine Pfeilbuttons zum Verschieben; die Struktur wird direkt gezogen.

Die Struktur wird nach jedem Verschieben dauerhaft gespeichert. Beschreibungen, eigene
Felder und Charakterzuordnungen bleiben erhalten. Eigene Unterorte können nicht zum
Elternort werden. Bei einem Speicherkonflikt erscheint ein Fehler und die aktuelle
Struktur wird neu geladen; es wird nichts stillschweigend überschrieben.
Ein Klick auf eine Ortszeile öffnet ihr Formular im rechten Seitenbereich, ohne
die Baumansicht zu verlassen. Auch während der Bearbeitung bleibt Drag-and-drop möglich.
Ungespeicherte Textänderungen bleiben beim Umordnen erhalten; ein verschobener Ort
wird gegen seinen aktuellen Elternort und seine aktuelle Revision gespeichert.
Nur während eines laufenden Speichervorgangs sind weitere Schreibaktionen gesperrt.
Der Elternort lässt sich weiterhin auch im Formular ändern.

### Lokale KI konfigurieren

**Ollama:** Modell zuvor installieren, beispielsweise `ollama pull llama3.1:8b`.
Den Ollama-Dienst starten. Base-URL `http://localhost:11434/v1`, Modell
`llama3.1:8b`, kein API-Schluessel.

**LM Studio:** Ein Modell laden und den lokalen OpenAI-kompatiblen Server starten.
Base-URL normalerweise `http://localhost:1234/v1`; den Modellbezeichner aus
LM Studio verwenden.

**OpenAI / kompatibler Anbieter:** Vollstaendige API-Basis inklusive `/v1`
eintragen, beispielsweise `https://api.openai.com/v1`. Modellname und
API-Schluessel des Anbieters verwenden. Der Adapter nutzt `/chat/completions`
mit SSE-Streaming, `max_tokens` und `temperature`. Anbieter/Modelle, die diese
Parameter nicht unterstuetzen, benoetigen einen weiteren Adapter.

Es gibt keine automatische Verbindungsgarantie beim Speichern. Verbindungs-,
Format- und Providerfehler erscheinen beim Chat explizit. Unvollstaendige Antworten
werden nicht als fertige Assistentennachrichten gespeichert. Mit **Erneut antworten**
kann eine bereits gespeicherte Benutzernachricht wiederholt werden.

## Wissens- und Zustandsregeln

**Welt- und Ortsbeschreibungen, ihre Attribute und Zustaende gelten als oeffentlich.**
Versteckte Informationen dort nicht eintragen. Der Wissenseditor ist der Ort fuer
verborgene Fakten. Andere Charakterprofile, Inventare und Standorte werden nicht
pauschal in den Kontext eines Charakters geladen.

Die Datenbankabfrage erlaubt nur:

- Wissen mit `character_id` des aktuellen Charakters;
- objektive Weltfakten mit `public = true`.

Ein privater objektiver Fakt und ein persoenliches Geheimnis eines anderen
Charakters gelangen daher gar nicht zum Modell. Der aktuelle Charakter kennt sein
eigenes Profil, seinen aktuellen Ort samt Vorfahren und ausgehende Beziehungen.
Eingehende Beziehungen verraten keine fremden Einschaetzungen oder Geheimnisse.
Weltbeschreibungen und Nachrichten werden als Daten behandelt, nicht als Befehle
fuer Datenbankzugriffe. Das LLM besitzt keine Schreibwerkzeuge oder Codeausfuehrung.

Jede akzeptierte Benutzernachricht erzeugt vorerst **einen originalgetreuen Eintrag
`received` mit Quelle `Benutzeraussage`, Vertrauen 50 und Nachrichtenreferenz**.
Das ist eine konservative Grundlage fuer Langzeitwissen, keine semantische
Faktenextraktion: auch Fragen und belanglose Nachrichten werden so gespeichert.
Ein Geruecht wird dadurch niemals zum objektiven Fakt. Assistentenaussagen
erzeugen keine automatischen Welt- oder Zustandsaenderungen.

Beschreibung und `state` werden getrennt gespeichert. Manuelle Zustandsaenderungen
ueberschreiben nicht die Beschreibung. Ein historisches Ereignis-/Undo-Protokoll
ist noch nicht implementiert.

### Kontextverwaltung

Modellfenster und Ausgabereserve sind konfigurierbar, auch 128k oder 256k.
Pflichtkontext (Profil, Welt, aktueller Ort und letzte Nachricht) hat Vorrang.
Dann folgen aktuelle Gespraechsnachrichten und persoenliches Wissen, gewichtet
nach Wortueberschneidung mit der letzten Nachricht; bei gleichem Gewicht zuerst
neuere Eintraege. Bereits im Verlauf enthaltene Benutzeraussagen werden nicht
zusaetzlich als Erinnerung eingespeist.

Tokenzaehlung mit `cl100k_base`, acht Overhead-Tokens pro Nachricht und 256 Tokens
Sicherheitsreserve. Das ist fuer fremde Modelltokenizer **eine Naeherung, keine
Garantie**. Ein zu grosser Pflichtkontext wird sichtbar abgelehnt und nicht heimlich
abgeschnitten. Aelteres Wissen wird bei Platzmangel priorisiert; automatische
Zusammenfassung und effizientere Datenbank-Retrieval-Indizes folgen spaeter.

## API, Konflikte und Loeschregeln

Die API verwendet das Praefix `/api`:

| Ressource | Endpoints |
|---|---|
| Welten | `GET/POST /worlds`, `PUT/DELETE /worlds/{id}` |
| Weltobjekte | `GET/POST /worlds/{id}/{resource}`, `PUT/DELETE /worlds/{id}/{resource}/{item}` |
| Gespraeche | `GET/POST /worlds/{id}/conversations`, `DELETE /conversations/{id}` |
| Nachrichten | `GET/POST /conversations/{id}/messages`, `PUT /conversations/{id}/messages/{message}` |
| Regenerierung | `POST /conversations/{id}/regenerate` |
| Provider | `GET/PUT /settings/provider` |

`resource` ist `locations`, `characters`, `relationships` oder `knowledge`.
Die jeweiligen Pydantic-Eingabemodelle stehen in `backend\app\schemas.py`.
PUT ist ein vollstaendiger Ersatz der editierbaren Felder, kein partieller PATCH.
Erstellte Identitaeten, Herkunftsreferenzen und Zeitstempel sind serververwaltet.

Beispielort:

```json
{
  "name": "Glade",
  "kind": "Region",
  "parent_id": null,
  "description": "Eine bewaldete Region.",
  "attributes": [
    {"name": "Magische Instabilitaet", "type": "number", "value": 42,
     "minimum": 0, "maximum": 100, "options": []}
  ],
  "state": {"Wetter": "Regen"},
  "tags": ["Wald"]
}
```

**Konfliktstrategie:** Editorobjekte besitzen eine `revision`. PUT verlangt die
zuletzt gelesene Revision, DELETE `?revision=...`. Eine veraltete Revision liefert
409 statt Last-write-wins. Nach einem Konflikt neu laden und die Aenderung bewusst
erneut anwenden. Dies ist eine lokale Grundlage, **noch kein Synchronisierungsdienst**.

**Ortsreihenfolge:** `sort_order` ist ein serververwaltetes Antwortfeld. Neue Orte
und im Formular umgehängte Orte werden bei ihren neuen Geschwistern angehängt;
normale Inhaltsänderungen lassen die Reihenfolge unverändert.
`PUT /api/worlds/{world_id}/location-tree` nimmt
`{"locations": [{"id": "...", "parent_id": null, "sort_order": 0, "revision": 1}]}`
entgegen. Der vollständige Snapshot muss alle Orte der Welt genau einmal enthalten
und die Reihenfolge je Elternort ab 0 lückenlos angeben. Zyklen und weltfremde Eltern
werden abgelehnt. Veraltete Revisionen sowie zwischenzeitlich erstellte/gelöschte Orte
führen zu HTTP 409; der gesamte Strukturwechsel ist atomar.
Migration `0002` ergänzt die Reihenfolge unter Erhalt der vorhandenen Daten.

Referenzen muessen zur selben Welt gehoeren; Ortszyklen und ungueltige Attributwerte
werden abgelehnt. Ein verwendeter Ort kann erst nach Umzug von Charakteren und
Entfernung seiner Unterorte geloescht werden. Eigene Feldreferenzen schuetzen auch
indirekt geloeschte Beziehungs- und Wissenseintraege.

Charakterloeschung entfernt dessen Chats, persoenliches Wissen und Beziehungen.
Weltloeschung entfernt saemtliche Daten dieser Welt.
Chatloeschung entfernt aus seinen Benutzernachrichten abgeleitetes Wissen.
Bearbeiten einer alten Benutzernachricht verlangt `confirm_discard: true`:
Nachfolgende Nachrichten und ihre abgeleiteten Eintraege werden entfernt;
das Wissen aus der bearbeiteten Nachricht wird ersetzt. Weltfakten bleiben
unveraendert. Quellengebundenes Chatwissen laesst sich nicht direkt in einen
Weltfakt umwandeln; dafuer bewusst einen separaten Weltfakt anlegen.
Eine Regenerierung ersetzt nur die letzte Assistentenantwort und
erst nach erfolgreichem Stream; bei Fehlern bleibt die bisherige Antwort erhalten.

Pro Gespraech ist nur eine laufende Generierung erlaubt. Konfliktbehaftetes
Loeschen/Bearbeiten wird waehrenddessen blockiert. **Nur einen Uvicorn-Worker
verwenden:** die lokale Laufzeitsperre ist pro Prozess, nicht verteilt.

Streaming liefert die SSE-Ereignisse `context`, `delta`, `done` oder `error`.
Ein `done` bestaetigt die persistierte Antwort, nicht nur das Ende einer HTTP-Anfrage.

## Daten, Schluessel und Betrieb

`backend\data\openworld.db` speichert Weltdaten. API-Schluessel werden mit Fernet
verschluesselt; der lokale Schluessel liegt separat unter
`backend\data\provider.key`. Beide sind ignorierte Laufzeitdaten und werden nicht
ans Frontend zurueckgegeben. Das Frontend erhaelt lediglich `has_api_key`.
Schluesseldatei nicht loeschen, solange gespeicherte Providerzugangsdaten benoetigt
werden.

Die Verschluesselung schuetzt nicht vor einem Angreifer mit Zugriff auf
Datenbank **und** Schluesseldatei. Unter Windows passende NTFS-Berechtigungen fuer
das Datenverzeichnis setzen; Backups mit Zugangsdaten ebenso schuetzen.
Ein reines Weltdatenexportformat darf Providerdaten nicht enthalten.
Aktuell gibt es noch keinen JSON-Exportbutton.

Optionale Umgebungsvariablen:

- `OPENWORLD_DATA_DIR`: absolutes Laufzeitdatenverzeichnis.
- `OPENWORLD_DATABASE_URL`: SQLAlchemy-Datenbank-URL statt SQLite-Standard.
- `OPENWORLD_ORIGINS`: kommagetrennte erlaubte Frontend-Origins.
- `OPENWORLD_API_URL`: Vite-Proxyziel, standardmaessig `http://127.0.0.1:8000`.

**Diese Version ist ausschliesslich fuer lokalen Einzelbenutzerbetrieb.**
Keine Authentifizierung, keine Benutzerkonten, keine abgesicherte oeffentliche
Serverinstallation. Nicht an `0.0.0.0` binden oder ins Internet freigeben.
Provider-URLs nur auf vertrauenswuerdige Ziele setzen: persoenlicher Kontext und
Chattexte werden bewusst dorthin gesendet. Benutzerkonten, TLS-/Proxykonfiguration,
Autorisierung und verteilte Konfliktverwaltung sind Voraussetzungen fuer Phase 4.

## Tests und Build

```powershell
Set-Location C:\OpenWorld\backend
& ..\.venv\Scripts\python.exe -m pytest -q
& ..\.venv\Scripts\python.exe -m ruff check app migrations tests

Set-Location C:\OpenWorld\frontend
npm run build
npm run test:e2e
```

Bei fehlendem Playwright-Browser einmalig:

```powershell
Set-Location C:\OpenWorld\frontend
node .\node_modules\playwright\cli.js install chromium
```

Der Browser-Test startet seine eigenen Dienste auf **18000, 18090 und 15173**.
Diese Ports vorher freihalten. Er verwendet eine isolierte temporaere Datenbank
mit echten Migrationen und einen expliziten Test-Provider, kein echtes LLM.
Produktive Daten oder Providerkonfigurationen werden nicht verwendet.
Der Test-Provider wird niemals vom normalen Anwendungsstart aktiviert.

Backendtests pruefen insbesondere den Eldoria-Fall:
Lumia kennt Powers privaten Kristall nicht; eine Aussage des Benutzers wird nur
Lumias erhaltenem Wissen hinzugefuegt, aendert keinen Weltfakt und informiert Power
nicht. Das Wissen steht in einem neuen Gespraech weiterhin zur Verfuegung.
Weitere Tests decken falsche Ueberzeugungen, Erinnerungen, Referenzen, asymmetrische
Beziehungen, Tokenbudgets ueber 32k, Migrationen, Schluessel und Providerfehler ab.
Browsertests pruefen den gesamten grafischen Ablauf, Streaming, Wiederaufnahme,
Nachrichtenbearbeitung, Regenerierung und mobile Breite.

Verifiziert am 3. November 2026: **42 Backendtests erfolgreich**, **1 vollstaendiger
Playwright-Benutzerablauf erfolgreich**, Ruff ohne Fehler, TypeScript-Pruefung und
Vite-Produktionsbuild erfolgreich. Desktop- und 390-Pixel-Mobilansicht wurden
zusaetzlich visuell kontrolliert. Der Testdienst prueft die Providerintegration
und die tatsaechlich uebertragenen Kontextdaten, nicht die Antwortqualitaet eines
echten LLM. Ein echtes Modell wurde in dieser Umgebung nicht getestet.
Starlette meldet im TestClient eine Abkuendigungswarnung fuer dessen httpx-Integration;
die Tests funktionieren mit den fixierten Versionen.
Zusaetzlich bestehen sechs Regressionstests fuer leere, HTML-, Text- und
ungueltige JSON-Fehlerantworten, unveraenderte FastAPI-Fehlerdetails und den
sichtbaren Backend-Starthinweis. Dieselbe Fehlerbehandlung gilt fuer API und Chat.

## Noch nicht implementiert / naechste Schritte

1. **Phase 2:** strukturierte LLM-Vorschlaege fuer Wissens- und Zustandsaenderungen;
   separate validierende Services; Regeln `auto`, `confirm`, `protected`;
   transaktionales Ereignisprotokoll mit Quelle, Ablehnung und Undo.
   Semantische Erinnerungsbildung, Zusammenfassungen, Korrekturverlauf und
   gezielteres SQL-Retrieval ergaenzen.
2. **Phase 3:** React-Flow-Beziehungsgraph, Gruppenchats, Simulation und Zeitachse,
   kontrollierte Reisen und weiterer Provideradapter. Portabler JSON-Import/-Export.
3. **Phase 4:** Konten, serverseitige Autorisierung, revisionsbasierte Synchronisierung,
   PostgreSQL-Tests, Feldvorlagen, Plugins und separater Google-Drive-Backupadapter.

Geplantes Exportformat: Envelope `{ "format": "openworld", "version": 1, "world": ...,
"locations": [...], "characters": [...], "relationships": [...], "knowledge": [...],
"conversations": [...], "messages": [...] }`, stabile IDs, ISO-8601-UTC-Zeitstempel,
typisierte Attribute und explizite Nachrichtenquellen. Kein Providerblock, keine
API-Schluessel. Import soll Schema/Referenzen in einer Transaktion validieren und
bestehende Revisionen nicht ungeprueft ueberschreiben. Das beschreibt den Vertrag
fuer die naechste Phase, keine schon vorhandene Importfunktion.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
