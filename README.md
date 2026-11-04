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
- Ereignisse mit validierten Vorschlägen, konfigurierbaren Freigaben, Quellen,
  Zustandsverlauf, Bestätigung, Ablehnung und kontrollierter Rücknahme.
- Individuelle Erinnerungen mit Korrekturverlauf, widersprechenden Einträgen,
  historischem Ereigniszeitpunkt und vollständig lokaler hybrider Erinnerungssuche.
- Bewusst aktivierbare Ereigniserkennung nach gespeicherten Chatnachrichten,
  persistente lokale Aufträge, sichtbare Fehler und begrenzte Wiederholungen.
- Mehrcharaktergespräche mit individuellen Sprecherkontexten und gespeicherten Zuhörern.
- Begrenzte autonome Simulationen mit Pause, Fortsetzung, Eingriff und fiktiver Weltzeit.
- Gerichteter React-Flow-Beziehungsgraph, weiterhin derselbe Editor und dieselben Daten.
- Versionierter JSON-Weltexport und transaktionaler Import ohne Überschreiben.

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
      events.py         Validierung, Freigaben, atomare Mutationen und Undo
      event_bindings.py Bestehende Ziele, Attributbindung und ausdrückliche Wertebelege
      event_schemas.py  Strikte strukturierte Vorschläge und Operationen
      event_api.py      Ereignisse, Freigaberegeln, Aufträge und Erinnerungen
      extraction.py     Quellengebundene Extraktion und persistente Aufträge
      extraction_settings.py Separate Verbindung, Budgets und Anbieterprofile
      event_worker.py   Lokaler, sequenzieller Hintergrunddienst
      conversations.py  Gruppen, Anwesenheit und Nachrichtenzuhörer
      simulation.py     Persistente Runden, Budgets, Wiederaufnahme und Modellaufrufe
      simulation_api.py Simulation, Gruppengespräche und Weltzeit
      portability.py    Versionierte weltbezogene JSON-Snapshots ohne Providerdaten
      memory.py         Hybrides lokales Retrieval und Originalsatzauszüge
      serialization.py Gemeinsame Serialisierung mit UTC-Zeitstempeln
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
6. **Einstellungen → KI-Verbindung einrichten** → Programm auswählen, Verbindung prüfen,
   ein gefundenes Modell auswählen und eine Antwort testen. Danach Einrichtung abschließen.
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

Auf der Startseite ohne einsatzbereite Verbindung oder unter **Einstellungen →
KI-Verbindung einrichten** den Assistenten öffnen:

1. **Lokale KI auf diesem Computer**, **KI über einen Online-Anbieter** oder
   **Eigene Verbindung (erweitert)** auswählen.
2. Der lokale Assistent prüft LM Studio und Ollama und zeigt deren tatsächliche
   Chatmodelle mit Ladestatus. Ohne erreichbaren Server oder geladenes Modell
   nennt er die nächsten Schritte im jeweiligen Programm. Bei Online-Anbietern
   Anbieter auswählen, Schlüssel eingeben und Modelle abrufen.
3. Ein Modell wählen und **Antwort testen** anklicken. Erst nach einer echten,
   abgeschlossenen Antwort lässt sich die Einrichtung speichern.

Die Suche und die Statusanzeige fragen nur Modellmetadaten ab. Der bewusste
Antworttest sendet keine Welten oder Gespräche, kann bei Online-Anbietern aber
Kosten verursachen. Ein zweiter Test bei einer nicht unterstützten Einstellung
erfolgt nur mit der dafür sichtbaren Freigabe; online ist diese standardmäßig aus.
Bei Zugangsschlüssel-, Guthaben- und Verbindungsfehlern gibt es keine automatische
Wiederholung. OpenWorld installiert oder lädt keine KI-Modelle ungefragt herunter.

Der Assistent lässt geöffnete Chats, Entwürfe, Gruppen und Simulationen erhalten.
Nach dem Abschluss gelangt man zum vorherigen Vorgang zurück. Abbrechen verändert
keine gespeicherte Verbindung. Gespeicherte Schlüssel werden ausschließlich bei
unveränderter Serveradresse wiederverwendet und niemals zurückgegeben.

Das Backend verwendet das tatsächlich geladene Kontextfenster, soweit der Server
es zuverlässig meldet, nicht die theoretische Modellobergrenze. Ohne verlässliche
Angabe gelten vorsichtig 4.096 Kontexttokens und 1.024 Antworttokens; Unsicherheiten
werden intern festgehalten. Reasoning-Steuerung wird nicht aus Modellnamen geraten.
Bei unbekannter Unterstützung werden keine zusätzlichen Denkmodus-Parameter gesendet.
Experten können automatische Vorgaben ausschalten und weiterhin sämtliche
Verbindungs-, Budget-, Reasoning- und Ausgabeoptionen bearbeiten.

**Erinnerungen und Weltveränderungen** bietet normale Schalter für automatische
Erinnerungen und die Bestätigung wichtiger Änderungen. Dabei entstehen zusätzliche
Modellanfragen; darauf weist die Oberfläche vor der Aktivierung hin.
**Automatische Erinnerungen und Ereignisse deaktivieren** unterbindet diese
Anfragen auch in Simulationen. Wartende Aufträge werden übersprungen; das Ergebnis
einer bereits laufenden Anfrage wird nicht mehr angewendet. Bereits begonnene
Anbieteranfragen können dadurch nicht nachträglich kostenfrei gemacht werden.
Gespeicherte Chats und Erinnerungen bleiben erhalten.

Für neue Verbindungen bereitet der Assistent dieselbe KI auch für Erinnerungen vor:
validiertes JSON per Prompt, unabhängiges Antwortbudget und keine automatischen
Wiederholungen. Bei LM Studio/Ollama wird der Denkmodus nur bei tatsächlich
gemeldeter Unterstützung ausgeschaltet. Bestehende technische Sondereinstellungen
werden nur nach ausdrücklicher Auswahl ersetzt; die automatische Auswertung pro
Welt wird durch die Einrichtung nicht aktiviert. Neue Simulationen verwenden
standardmäßig die Chatverbindung ohne zusätzliche Erinnerungserkennung.

Die folgenden Angaben sind nur für die manuelle Einrichtung unter **Erweitert** nötig:

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

Eine Nachricht wird **nicht mehr pauschal als dauerhafte Erinnerung gespeichert**.
Die Ereigniserkennung ist standardmäßig ausgeschaltet. Auf der Seite **Ereignisse**
unter **Ereigniserkennung und Freigaben** kann sie bewusst pro Welt eingeschaltet
werden. Sie verwendet separat konfigurierbare Extraktionseinstellungen für zusätzliche
Aufrufe; bei Cloud-Anbietern können dadurch zusätzliche Kosten entstehen.

### Extraktionsmodell und Kompatibilität

Unter **Einstellungen → Erinnerungen aus Gesprächen → Erweitert** lassen sich Verbindung, Modell,
Kontextfenster, Ausgabebudget, Temperature und Zeitlimit unabhängig vom Chat festlegen.
Standardmäßig werden Verbindung und Zugangsschlüssel des Chats verwendet; ein leerer
Extraktionsmodellname übernimmt den Chatmodellnamen. Eigene Schlüssel werden separat
verschlüsselt gespeichert und niemals zurückgegeben. Das tatsächliche Modellfenster
muss für beide Aufgaben korrekt eingetragen sein.

Standard: **4.096 Ausgabetokens**, **16.384 Kontexttokens**, **300 Sekunden** Zeitlimit.
Ausgabetokens sind nicht das Kontextfenster: Bei Reasoning-Modellen zählen interne
Denktokens oft zum Ausgabelimit und können den Platz für JSON aufbrauchen.
Auch der Chat besitzt unter seinen erweiterten Einstellungen ein unabhängiges
Reasoning-Profil. Standard ist unverändert die Anbietervorgabe. Beim getesteten
LM-Studio-Server funktioniert im Chat `reasoning_effort: "none"`; für die native
Extraktion wird dagegen `reasoning: "off"` verwendet.

Das explizit gewählte Anbieterprofil steuert die tatsächlich verwendete API:

| Profil | Extraktions-API und Reasoning-Steuerung |
|---|---|
| OpenAI-kompatibel | `/chat/completions`, keine unbelegte Reasoning-Steuerung |
| OpenAI | `/chat/completions`, `max_completion_tokens`, `reasoning_effort` |
| llama.cpp / vLLM | `/chat/completions`, `chat_template_kwargs.enable_thinking` |
| Ollama | Native `/api/chat`, `think`, `options.num_predict` und optional JSON-Schema |
| LM Studio | Native `/api/v1/chat`, `reasoning`, `max_output_tokens`, `store: false`, keine Werkzeuge |

Profil und Reasoning-Modus müssen zum Server und zum konkreten Modell passen.
Nicht jede API akzeptiert jedes Reasoning-Level. LM Studio bietet bei Qwen 3.5 9B
laut Modellmetadaten `off` und `on`; ein generisches `enable_thinking` am
OpenAI-Endpunkt wurde im Praxistest ignoriert. Das native Profil verwendet
JSON-Anweisungen im Prompt statt einer nicht dokumentierten nativen Schemaoption.
Jede Antwort wird weiterhin streng mit Pydantic sowie allen Quellen-/Referenzregeln
geprüft. Es gibt keine heuristische JSON-Reparatur und keine ungeprüfte Übernahme.

Bei OpenAI-kompatiblen Endpunkten ist `auto`, JSON-Schema, JSON-Objekt oder reines
JSON per Prompt wählbar. Nur `auto` darf nach einer ausdrücklichen HTTP-400/422-
Ablehnung von `response_format` einmal ohne diesen Parameter verhandeln; Authentifizierungs-
und Netzwerkfehler lösen keine automatische Generierungswiederholung aus.

Nach jedem vollständig gespeicherten Gesprächswechsel werden **beide Nachrichten
gemeinsam in einem Auftrag** analysiert. Die Quellen besitzen unabhängige Rollen,
Sprecheridentitäten und Revisionen; die Gruppierung setzt keine Nutzernachricht
voraus. In Mehrcharaktergesprächen wird dagegen jede gehörte öffentliche Nachricht
pro tatsächlichem Empfänger verarbeitet. Reine, vollständig erkannte Gruß-/Dankesphrasen werden
konservativ ohne Modellaufruf als `skipped` protokolliert. Sobald zusätzlicher Inhalt
vorliegt, wird nicht anhand einzelner Stichwörter aussortiert.

Die Quellenrevisionen verhindern doppelte Verarbeitung, auch bei erneutem manuellem
Prüfen. Nachrichtenbearbeitung oder erfolgreiche Regenerierung invalidiert den
gesamten verknüpften Auftrag samt Ereignissen, nicht nur die zitierte Hälfte des
Gesprächswechsels. Eine bearbeitete Nutzernachricht wird automatisch erst nach der
neuen vollständigen Antwort analysiert; explizite manuelle Prüfung bleibt möglich.

**Begrenzte Wiederholungen:** Optional höchstens eine automatische Wiederholung je
Auftrag bei leerer, abgeschnittener oder ungültiger Ausgabe. Sie erhält einen
Korrekturhinweis; bei leerer/abgeschnittener Ausgabe wird das Budget soweit möglich
verdoppelt (z. B. 4.096 → 8.192), bei passendem Anbieterprofil gegebenenfalls Reasoning
abgeschaltet. Das Kontextbudget wird erneut geprüft. Nach erneutem Fehlschlag nur
noch manuell, insgesamt höchstens drei Versuche je Auftrag. Die automatische
Wiederholung ist separat abschaltbar. Alle Ereignisse einer Antwort werden atomar
validiert/übernommen; Chatnachrichten bleiben bei Fehlschlägen gespeichert.

Unter **Ereignisse → Diagnose** stehen Versuch, Modell/Profil, wirksames Budget,
Abbruchgrund und gemeldete Token-/Reasoning-Nutzung sowie HTTP-Anzahl einschließlich
Format-Aushandlung. Nicht gemeldete Werte werden nicht als null Tokens ausgegeben.
Ein angeforderter Reasoning-Stopp mit weiterhin gemeldeten Denktokens wird als
Warnung angezeigt. Es werden weder interne Denktexte noch Zugangsschlüssel protokolliert.

Die Extraktion liefert ausschließlich strukturierte Vorschläge. Jeder Vorschlag
aus einem Chat benötigt ein wörtliches Quellenzitat und existierende Referenzen
derselben Welt. Erhaltene Informationen bewahren die Originalaussage, bleiben
persönlich und haben höchstens 50 % Vertrauen. Fragen, Smalltalk und unklare
Rückblicke sollen keine neuen Tatsachen erzeugen. Unsichere/paraphrasierte persönliche
Erlebnisse sowie Assistentenerzählungen benötigen mindestens eine Bestätigung.
Ungültige Ausgaben führen zu einem sichtbaren Fehler und keinerlei Teiländerungen.
Ein LLM besitzt weiterhin weder Datenbankzugriff noch Schreibwerkzeuge.

Sichere Standardfreigaben:

- Persönliche erhaltene Informationen und eindeutige Erinnerungen: `auto`.
- Korrekturen früherer Überzeugungen, Beziehungen und Charakterzustände: `confirm`.
- Objektive Weltfakten sowie Welt- und Ortszustände: `protected`.

Regeln lassen sich nach Ereignistyp und Objektklasse ändern. Die spezifischste
Regel gilt; bei einem Vorschlag mit mehreren Operationen gilt die strengste
Freigabe. Geschützte Weltfakten und Welt-/Ortszustände lassen sich nicht durch
eine allgemeinere Auto-Regel entsperren; bewusst im jeweiligen Editor bearbeiten.
Neue Ereignistypen sind freie, stabile Bezeichner wie `knowledge_acquired` oder
`trust_changed`. Unterstützte Operationen sind persönliches Wissen, Korrekturen,
Archivierung, vorhandene Beziehungsattribute, Charakterzustände und Aufenthaltsorte.
Willkürliche neue Beziehungsattribute oder geänderte Attributdefinitionen werden
nicht als Ereignisänderung akzeptiert.

### Eindeutige Ziele und belegte Werte

Chat-Extraktionen dürfen **keine neuen Zustandsfelder** anlegen. Neue Felder zuerst
bewusst im manuellen Editor erstellen. Vorhandene Felder behalten ihren Datentyp;
ein Ersatz wie `trust_power`, `powerTrust` oder `Vertrauen zu Power` wird nicht
anstelle eines Beziehungsattributs angelegt. Auch bereits vorhandene Schattenfelder
dürfen eine ausdrücklich benannte Beziehungsänderung nicht aufnehmen.

Für Beziehungen referenziert die KI die vorhandene **Beziehungs-ID**, deren
Revision, `target_id` und den exakten vorhandenen Attributnamen. Die kompakte
Wertreferenz `attributes: [{"name": "Vertrauen", "value": 60}]` wird vom Backend
gegen die bestehende Definition aufgelöst: Typ, Auswahlmöglichkeiten und Grenzen
kommen aus der Datenbank, nicht aus Modellannahmen. Das bisherige vollständige
Attributformat bleibt unterstützt, darf die Definition aber nicht verändern.
Nur ausgehende Beziehungen des Gesprächsempfängers sind zulässig.

Zusätzlich muss das Quellenzitat Besitzer, Attribut und Ziel eindeutig verbinden,
etwa **„Dein Vertrauen zu Power steigt von 45 auf 60.“** oder
**„Lumias Vertrauen zu Power: 60.“** Bei gleichen Charakternamen oder mehreren
passenden Beziehungen reicht der Name nicht: Das Zitat muss die konkrete
Beziehungs-ID enthalten, beispielsweise `BEZIEHUNGS-ID Vertrauen: 60`.
„Mein“ gehört nur bei eigener Figurenrede zum Empfänger, nicht bei fremden Sprechern.

Numerische Änderungen brauchen eine ausdrückliche einzelne Zuweisung wie `: 60`,
`auf 60` oder `von 45 auf 60`; ein genannter Ausgangswert muss zum bestehenden Wert
passen. Dezimalkommas werden unterstützt. Aus Lob, Streit oder „etwas mehr Vertrauen“
wird **kein Zahlenwert errechnet**. Verneinte, beabsichtigte oder mehrdeutige Angaben
werden konservativ abgelehnt. Unterstützte Text-, Boolean- und Listenänderungen
benötigen ebenfalls einen wörtlichen Zuweisungsbeleg, keine bloße Paraphrase.
Mehrere Werte benötigen eigene unveränderte Teilzitate in `attribute_quotes`
beziehungsweise `value_quotes`; bei einem einzelnen Wert genügt `evidence_quote`.

Diese Prüfung gilt bei Extraktion, Vorschlagsbearbeitung **und erneut bei Bestätigung**,
auch für alte offene Vorschläge. Eine manuelle Bestätigung umgeht sie nicht.
Unklare Formulierungen erzeugen einen sichtbaren Validierungsfehler, keine stille
Umleitung auf ein anderes Feld. Der begrenzte Korrekturversuch darf einen neuen,
vollständig geprüften Vorschlag liefern. Sonst bleibt der Chat erhalten und die
Welt unverändert. Bewusste freie Änderungen bleiben im manuellen Editor möglich;
Quellenbindung bedeutet insbesondere, dass ein extrahierter Zahlenvorschlag nicht
nachträglich auf einen im Zitat unbelegten Wert umgeschrieben werden kann.
Freigaberegeln, Schutz objektiver Fakten, Audit und Undo bleiben erhalten.
Das ist eine konservative Bindungsprüfung, keine allgemeine Sprachverständnisgarantie.

Beschreibung und `state` werden getrennt gespeichert. Manuelle Zustandsaenderungen
überschreiben nicht die Beschreibung. Änderungen im Editor an Zuständen,
Aufenthaltsorten, Beziehungen und Wissensinhalten werden ebenfalls mit Vorher-/
Nachherwerten protokolliert. Alle automatisch angewendeten Änderungen besitzen
ein reversibles Mutationsprotokoll.

### Ereignisse, Quellen und Rücknahme

Ein **Ereignis** beschreibt einen Vorgang mit Beteiligten, optionalem Ort und
eigenem Ereigniszeitpunkt. Ein **Vorschlag** enthält zulässige Operationen und deren
Freigabe. Erst eine **Mutation** verändert einen Datensatz. Das Auditprotokoll
zeichnet Erstellung, Bearbeitung, automatische/manuelle Übernahme, Ablehnung,
Invalidierung und Rücknahme geordnet auf.

Ereigniszeit und Speicherzeit sind getrennt. Auch historische Erlebnisse, etwa
aus dem Jahr 1200, sind möglich. Nachrichten tragen eine eigene Revision und
eine optionale Sprecheridentität unabhängig von ihrer Chatrolle. Beteiligte,
Quellennachrichten, Ziele, Wissensverknüpfungen und Mutationen werden relational
gespeichert; Operationsdaten und Vorher-/Nachherwerte sind zusätzlich JSON.

**Rücknahme** prüft aktuelle Werte, Revisionsketten und Wissensabhängigkeiten.
Neuere abhängige Ereignisse müssen zuerst zurückgenommen werden. Unbekannte
manuelle Änderungen blockieren ein Undo, statt überschrieben zu werden. Die
Prüfung ist bewusst konservativ und erfolgt auf Objekt-/Feldebene; verschiedene
Änderungen innerhalb desselben Zustandsobjekts können deshalb ebenfalls blockieren.
Nach Rücknahme eines späteren Ereignisses lässt sich die frühere Änderung wieder
zurücknehmen. Das Undo wird selbst protokolliert; neue Erinnerungen werden dabei
als zurückgenommen markiert und nicht spurlos gelöscht.

Beim Bearbeiten/Löschen einer Quelle oder erfolgreicher Regenerierung werden
zugehörige Vorschläge invalidiert und angewendete Änderungen atomar zurückgenommen.
Bei Abhängigkeitskonflikten bleibt der ursprüngliche Verlauf erhalten und der
Benutzer erhält einen sichtbaren Konflikt. Fehlgeschlagene Regenerierung ersetzt
keine gespeicherte Antwort. Quellenzitate bleiben auch nach Entfernen einer
Nachricht im Ereignisverlauf erhalten.

Im Charaktereditor bietet **Erinnerungen** das Hinzufügen, Korrigieren und Entfernen
persönlicher Einträge. **Verlauf anzeigen** zeigt überholte/entfernte Einträge mit
Quelle und Korrekturverknüpfungen. Ungelöste Widersprüche können als `contradicts`
verknüpft werden; begründete Korrekturen verwenden `supersedes`. Unterschiedliche
Charaktere behalten voneinander unabhängige Sichtweisen auf dasselbe Ereignis.

### Kontextverwaltung

Modellfenster und Ausgabereserve sind konfigurierbar, auch 128k oder 256k.
Pflichtkontext (Profil, Welt, aktueller Ort und letzte Nachricht) hat Vorrang.
Systemregeln, öffentliche Daten und sichtbare Erinnerungen werden in einer einzigen
führenden Systemnachricht zusammengeführt. Damit funktionieren auch lokale
Chattemplates, die weitere Systemnachrichten ablehnen; Rollen und Reihenfolge
des eigentlichen Gesprächs bleiben erhalten.
Dann folgen aktuelle Gesprächsnachrichten und persönliches Wissen, gewichtet
nach Wortüberschneidung, verknüpften Charakteren, deutschen Themenmustern
(u. a. Beziehungen, Versprechen, Begegnungen, Verlust), Wichtigkeit und zeitlicher
Relevanz. So findet eine Frage nach „zwischen euch“ auch eine Erinnerung an
entzogenes Vertrauen ohne identische zentrale Begriffe.
Bereits im Verlauf enthaltene Aussagen und identische Wissenseinträge werden
nicht doppelt eingespeist. Überholte Überzeugungen erscheinen bei ausdrücklichen
Rückblicken mit ihrem historischen Status, nicht als aktuelle Wahrheit.

Tokenzaehlung mit `cl100k_base`, acht Overhead-Tokens pro Nachricht und 256 Tokens
Sicherheitsreserve. Das ist fuer fremde Modelltokenizer **eine Naeherung, keine
Garantie**. Ein zu grosser Pflichtkontext wird sichtbar abgelehnt und nicht heimlich
abgeschnitten. Älteres Wissen wird bei Platzmangel priorisiert; passende vollständige
Originalsätze können als ausdrücklich gekennzeichneter Auszug eingebunden werden.
Quelle, Wissensart, Unsicherheit und Charakterzuordnung bleiben getrennt.
Es gibt keine generative Zusammenfassung, keine verpflichtenden Embeddings und
keinen zusätzlichen Cloud-Dienst. Die lokale Themen-/Entitätensuche ist kein
universelles semantisches Sprachmodell und versteht nicht jede Paraphrase.

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
| Extraktionsmodell | `GET/PUT /settings/extraction` |
| Ereignisse | `GET/POST /worlds/{id}/events`, `GET/PUT /worlds/{id}/events/{event}` |
| Ereignisaktionen | `POST /worlds/{id}/events/{event}/approve`, `/reject`, `/undo` |
| Erkennung/Freigaben | `GET/PUT /worlds/{id}/event-settings`, `GET/PUT /worlds/{id}/event-rules` |
| Extraktionsaufträge | `GET /worlds/{id}/extraction-jobs`, `POST /worlds/{id}/extraction-jobs/{job}/retry` |
| Bestehenden Verlauf prüfen | `POST /conversations/{id}/extract` |
| Persönlicher Verlauf | `GET /worlds/{id}/characters/{character}/memories` |

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
Bestehende Ereignisabhängigkeiten können einzelne Objektlöschungen blockieren;
betroffene Änderungen zuerst zurücknehmen oder offene Vorschläge ablehnen.
Chatlöschung invalidiert seine Ereignisse und nimmt abgeleitete Änderungen zurück,
sofern keine neueren Abhängigkeiten entgegenstehen.
Bearbeiten einer alten Benutzernachricht verlangt `confirm_discard: true`:
Nachfolgende Nachrichten werden entfernt; zugehörige Ereignisse werden kontrolliert
invalidiert. Für die bearbeitete Nachrichtenrevision kann ein neuer Extraktionsauftrag
entstehen. Historisches Phase-1-Chatwissen folgt weiterhin seiner ursprünglichen
Quellenbindung. Unabhängige Weltfakten bleiben unverändert.
Quellengebundenes Chatwissen lässt sich nicht direkt in einen
Weltfakt umwandeln; dafuer bewusst einen separaten Weltfakt anlegen.
Eine Regenerierung ersetzt nur die letzte Assistentenantwort und
erst nach erfolgreichem Stream; bei Fehlern bleibt die bisherige Antwort erhalten.

Ereignislisten unterstützen `character_id`, `location_id`, `event_type`, `status`,
`conversation_id`, `from_time`, `until_time`, `limit` und `offset`.
`PUT` eines Vorschlags verlangt `?revision=...`; Aktionen verwenden
`{"revision": 1}`. Schemas und Beispiele stehen unter `/docs`. Generische
Wissenslisten liefern aktuelle Einträge; der Erinnerungsendpoint liefert auch
deren Verlauf.

Extraktion und Streaming sind getrennt. Abgeschlossene Nachrichten erzeugen nur
bei aktivierter Erkennung persistente Aufträge. Der lokale Worker verarbeitet
diese sequenziell. Ein Schlüssel aus Nachrichten-ID, Revision und Extraktorversion
verhindert wiederholte Übernahme derselben Quelle. Fehlgeschlagene Aufträge werden
nicht endlos automatisch wiederholt: höchstens drei bewusst ausgelöste Versuche.
Beim Neustart bleiben wartende Aufträge erhalten; unterbrochene laufende Aufträge
werden mit sichtbarer Fehlermeldung markiert. Erkennungsfehler entfernen keine
bereits gespeicherten Chatnachrichten.

Der OpenAI-kompatible Adapter versucht JSON-Ausgabe und fällt nur bei explizit
gemeldeter fehlender Unterstützung von `response_format` auf normales JSON im
Antworttext zurück. Auch dann bleibt vollständige Pydantic-/Referenzvalidierung
verpflichtend; es gibt keine heuristische Reparatur beschädigter JSON-Daten.

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
Der JSON-Weltexport enthält keine Providerdaten. Er enthält jedoch bewusst die
privaten fiktionalen Daten der ausgewählten Welt und muss entsprechend geschützt werden.

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

Die Phase-2-Tests prüfen die Akzeptanzfälle A–K: Geheimnisse, subjektive
Informationsübertragung, Überzeugungskorrektur, Beziehungsfreigabe, Undo und
Abhängigkeiten, lokale Erinnerungssuche, ungültige Ausgaben, Regenerierung,
Quellenbearbeitung und transaktionalen Rollback. Migrationstests vergleichen
sämtliche ursprünglichen Spalten befüllter Welten, Profile, Chats und Wissenseinträge.
Browserprüfungen decken zusätzlich Bearbeitung/Bestätigung/Rücknahme von Vorschlägen
und den persönlichen Erinnerungsverlauf ab.

Verifiziert am 4. November 2026: **161 Backendtests und 15 Browsertests bestanden**.
Ruff, TypeScript-Prüfung und Vite-Produktionsbuild sind erfolgreich.

Der Testdienst prüft die Providerintegration
und die tatsaechlich uebertragenen Kontextdaten, nicht die Antwortqualitaet eines
echten LLM. Zusätzlich wurde der grundlegende Erinnerungskreislauf mit dem tatsächlich
installierten **Qwen 3.5 9B in LM Studio** und isolierten künstlichen Daten geprüft:
Mitteilung → quellengebundenes persönliches Wissen mit 50 % Vertrauen →
Erinnerung in einem neuen Gespräch. Quellenbearbeitung nahm die alte Information
zurück; nach erneuter Antwort/Extraktion erinnerte ein weiteres Gespräch den
korrigierten Fund. Private Weltfakten und fremde Geheimnisse blieben ausgeschlossen.
Mit dem nativen Extraktionsprofil und Reasoning `off` meldete der Anbieter
**0 Reasoning-Tokens**. Chat-Reasoning wurde unabhängig per LM-Studio-Profil ausgeschaltet.

Der Praxistest zeigte außerdem zwei Kompatibilitätsprobleme, die behoben wurden:
ein erschöpftes Ausgabebudget durch Reasoning und ein Chattemplate, das mehrere
Systemnachrichten ablehnt. Der vollständige Erinnerungskreislauf funktioniert
mit der getesteten Konfiguration; daraus folgt **keine allgemeine semantische
Zertifizierung**. Im erneuten Test schlug Qwen zunächst ein neues Zustandsfeld
`Vertrauen zu Power` vor. Das Backend lehnte es ohne Teiländerungen ab. Nach genau
einer automatischen Korrekturanfrage lieferte dasselbe Modell die bestehende
gerichtete Beziehungs-ID, Ziel-ID und das Attribut `Vertrauen` mit Wert 60.
Dieser echte Beziehungsvorschlag blieb bestätigungspflichtig; Bestätigung änderte
45 auf 60, Undo stellte 45 wieder her. Kein Schattenfeld wurde angelegt.
Alle **14 Prüfungen des isolierten Modelllaufs** bestanden, einschließlich
Erinnerungskorrektur, privater Kontexttrennung und 0 gemeldeten Reasoning-Tokens.
Der Test belegt die sichere Ablehnung/Korrektur dieses Fehlers, nicht fehlerfreie
Erstversuche oder allgemeine semantische Zuverlässigkeit. Weitere Formulierungen
können bewusst abgelehnt werden; Vorschläge weiterhin inhaltlich prüfen.
Starlette meldet im TestClient eine Abkuendigungswarnung fuer dessen httpx-Integration;
die Tests funktionieren mit den fixierten Versionen.
Zusaetzlich bestehen sechs Regressionstests fuer leere, HTML-, Text- und
ungueltige JSON-Fehlerantworten, unveraenderte FastAPI-Fehlerdetails und den
sichtbaren Backend-Starthinweis. Dieselbe Fehlerbehandlung gilt fuer API und Chat.

### Mit einem echten Modell prüfen

1. In einer separaten Testwelt Lumia und Power anlegen. Ein verborgenes Weltfaktum
   und persönliches Geheimnis nur Power zuweisen.
2. Unter Einstellungen einen vertrauenswürdigen lokalen OpenAI-kompatiblen Anbieter
   (z. B. Ollama oder LM Studio) und dessen tatsächlich geladenes Modell konfigurieren.
3. Unter Einstellungen die **Ereignisextraktion** separat konfigurieren, bei LM Studio
   das native Profil und für Qwen 3.5 9B Reasoning **Aus** wählen. Ausreichendes
   Kontextfenster und 4.096–8.192 Ausgabetokens vorsehen. Unter Ereignisse die
   Erkennung bewusst einschalten.
4. Zunächst „Wie geht es dir?“ senden: kein dauerhafter Wissenseintrag erwartet.
   Danach „Power hat einen Kristall gefunden.“ senden.
5. Unter Ereignisse bzw. Erinnerungen prüfen: ausschließlich Lumia erhält eine
   quellengebundene Information mit höchstens 50 % Vertrauen. Powers Wissen und
   der verborgene Weltfakt bleiben unverändert. Extraktionsfehler stehen unter
   Ereignisse; sie sind keine erfolgreich erkannten Weltveränderungen.
6. Einen bestehenden Beziehungswert im Gespräch thematisieren. Einen plausiblen
   Vorschlag prüfen, bearbeiten/bestätigen und danach zurücknehmen.
7. Mit einer neuen Unterhaltung und einer umformulierten Frage die Erinnerung
   prüfen; anschließend Quellennachricht bearbeiten und Regenerierung testen.

Für qualitative Prüfung verschiedene Modellantworten und Formulierungen testen.
Ein Modell kann Ereignisse übersehen oder unbegründete Vorschläge erzeugen;
Quellenprüfung und Freigaben ersetzen keine Garantie semantischer Richtigkeit.

### Migration 0004

Ergänzt separate Extraktionseinstellungen, strukturierte Auftragsdiagnosen und
relationale Quellenrevisionen pro Auftrag. Bestehende Aufträge erhalten ihre alte
Einzelquelle als Verknüpfung; bereits verarbeitete Quellen werden nicht automatisch
neu analysiert. Bestehende Chat-Providerdaten, Welten, Nachrichten und Erinnerungen
werden nicht umgeschrieben. Vor dem Start `alembic upgrade head` ausführen.

### Migration 0003

`alembic upgrade head` ergänzt Ereignisse, Vorschläge, Beteiligte, Quellen, Ziele,
Mutationen, Audit, Freigaberegeln, Extraktionsaufträge, Welteinstellungen und
Wissensverknüpfungen. Nachrichten erhalten Revision/Sprecheridentität; Wissen erhält
Status, Provenienz, Ereignis-/Subjektbezug, Erlebniszeit, Wichtigkeit und Emotion.
Alte Inhalte, IDs, Quellen, Vertrauenswerte und Profilfeldschlüssel bleiben erhalten.
Bestehendes Wissen wird als `legacy` markiert und **nicht** nachträglich verifiziert.
Migrationen vor dem Start ausführen und vorher die lokale Datenbank sichern.
Ein Schema-Downgrade entfernt die neuen Phase-2-Verlaufsdaten und ist kein Daten-Undo.

## Simulationen und Gruppengespräche

Unter **Simulationen** mindestens zwei Charaktere und einen Szenenort auswählen.
Vor-Ort-Gespräche benötigen anwesende Charaktere am selben Ort. Fernkommunikation
ist eine ausdrückliche Alternative, kein stiller Ersatz für fehlende Anwesenheit.
**Eine Runde ist ein Charakterbeitrag**, nicht eine vollständige Gesprächsrunde
aller Teilnehmer. Die Auswahlreihenfolge bestimmt die zyklische Sprecherfolge.

Anlegen startet noch keine Modellaufrufe. **Starten/Fortsetzen**, **1/5/20 Runden**
oder eine eigene Zahl starten bewusst begrenzte Läufe. **Pause** unterbricht auch
laufende Anfragen; unfertige Antworten werden nicht öffentlich gespeichert.
**Abbrechen** beendet den Lauf dauerhaft. Ein Backend-Neustart pausiert laufende
Simulationen; Fortsetzung erfolgt niemals automatisch. Bereits gespeicherte Beiträge
werden nach Extraktionsfehlern nicht erneut generiert.

Im angehaltenen Gespräch sind menschliche Eingriffe, direkte Ansprache und Änderungen
der Szene/Teilnehmer möglich. Neue Teilnehmer erhalten keinen rückwirkenden Zugriff
auf ungehörte Nachrichten. Jeder Sprecher erhält nur sein eigenes Profil, Wissen,
ausgehende Beziehungen und die tatsächlich gehörte öffentliche Historie. Interne
Reasoning-Kanäle und als Denktext markierte Ausgaben werden nicht veröffentlicht.
Qwen-kompatible Erstzüge erhalten bei Bedarf einen technischen Sprechzug-Hinweis;
dieser ist keine menschliche Äußerung und wird nicht in den Verlauf geschrieben.

Nach einem Beitrag werden die persönlichen Extraktionsaufträge abgeschlossen, bevor
der nächste Sprecher generiert wird. Gehörte Behauptungen sind persönliche `received`-
Informationen mit höchstens 50 % Vertrauen, keine objektiven Fakten. **Nach Regeln**
nutzt vorhandene Freigaben; **Bestätigen** verlangt mindestens Bestätigung; **Beobachten**
erzeugt nur geschützte Vorschläge und verändert weder Wissen noch Uhr oder Zustand.
Eine Simulation aktiviert nicht nebenbei die globale Erkennung für normale Chats.

Die Gesprächsansicht zeigt die letzten 20 zugehörigen Ereignisse sowie die Gesamtzahlen
übernommener Änderungen, ausstehender Bestätigungen und geschützter Vorschläge.
Zeitfortschritte zählen ebenfalls dazu. **Details und Freigaben** öffnet die vollständige
Ereignisprüfung; Vorschläge sind nicht mit bereits übernommenen Änderungen gleichzusetzen.

Standardgrenzen: 20 Beiträge, 100 Modellanfragen, 250.000 geschätzte reservierte Tokens,
600 Sekunden kumulierte Modellzeit. Jeder tatsächlich begonnene Chat-/Extraktionsaufruf
wird vor dem Aufruf reserviert. Extraktionen verwenden keine automatische Wiederholung
und keine versteckte Format-Aushandlung. Bewusstes Fortsetzen kann fehlgeschlagene
Extraktionen innerhalb der Grenzen wiederholen, höchstens drei Versuche je Auftrag.
Tokens sind konservative Eingabe-/Maximalausgabeschätzungen, keine tatsächliche
Gesamtnutzung oder Kostenangabe. Nicht gemeldete Nutzung und Kosten bleiben unbekannt.
Pro Welt läuft höchstens eine Simulation; der lokale Dienst arbeitet zusätzlich
global sequenziell. Ein einzelner Uvicorn-Prozess bleibt Voraussetzung.

**Gruppengespräche** erlauben menschliche Beiträge und einzeln ausgelöste Antworten
ausgewählter Charaktere, ohne autonome Schleife. Normale Einzelchats bleiben separat.
Gruppen-/Simulationsnachrichten sind unveränderlich; Korrekturen als neue Beiträge
einfügen. Sichere Rücknahme eines Ereignisses wird verweigert, wenn spätere gespeicherte
Simulationsbeiträge dessen Weltzustand bereits verwendet haben. Das ist bewusst
konservativ; eine automatische Rückabwicklung ganzer Gesprächsketten gibt es nicht.

### Gegenstände, Reisen und Zeit

Übergaben verwenden ausschließlich `state["Inventar"]` als Liste exakter Gegenstandsnamen.
Alte Freitextinventare werden nicht erraten oder automatisch umgewandelt. Besitzer muss
den Gegenstand tatsächlich besitzen; Empfänger und Besitzer müssen am selben Ort
anwesend sein. Beide Inventare ändern sich atomar über die Event Engine, mit Revisionen
und Undo. Aussagen über Besitz erschaffen keine Gegenstände; Absichten führen keine
Übergabe aus. Standard ist Bestätigung, automatische Handlungen benötigen eine bewusst
gesetzte passende Freigaberegel und weiterhin gültige Belege.

Reisen sind validierte Abreise-/Ankunftsereignisse. Ankunft an einem anderen Ort setzt
eine zuvor gespeicherte Reise zu diesem Ziel voraus, keine direkte Modell-Teleportation.
Reisegeschwindigkeit, Entfernungsberechnung und automatische Wegfindung sind noch nicht
implementiert. Nicht mehr anwesende Charaktere nehmen nicht weiter am Vor-Ort-Gespräch teil.
Die Weltuhr ist fiktive Zeit, unabhängig von UTC-Protokollzeiten. Standard: 1 Weltminute
je vollständig verarbeiteter Runde; Tageslänge und Kalenderbeginn sind frei einstellbar.
Manuelle Zeitänderungen werden als Ereignis gespeichert und verlangen eine Pause.
Ein komplexes Kalender-/Termin- oder Tagesroutinensystem ist nicht enthalten.

### Portables Weltformat v1

**Welteditor → Welt exportieren** lädt JSON herunter; **Meine Welten → Welt importieren**
liest es ein. Envelope:

```json
{"format":"openworld.world","version":1,"world_id":"UUID","tables":{}}
```

`tables` enthält vollständig die im Backend explizit erlaubten weltbezogenen Tabellen:
Welt, Orte, Charaktere, Beziehungen, Wissen/Verknüpfungen, Chats/Nachrichten/Teilnehmer/
Zuhörer, Ereignisse/Vorschläge/Quellen/Ziele/Mutationen/Audit/Freigaben, Weltuhr,
Simulationen/Runden/Abhängigkeiten und Extraktionsaufträge/Quellenrevisionen.
Stabile IDs, Revisionen und ISO-8601-Zeitstempel bleiben erhalten. Providerverbindungen,
Schlüssel, lokale Modellüberschreibungen und detaillierte Laufzeitfehler bleiben lokal.
Dies ist bewusst ein Weltexport, kein Backup der Programmeinstellungen.

Export verlangt einen angehaltenen Weltbetrieb. Import prüft Formatversion, Felder,
Typen, Ortszyklen und weltinterne Referenzen, bevor in einer Transaktion geschrieben
wird. Eine vorhandene Identität wird abgelehnt, niemals überschrieben. Zum Rückimport
derselben IDs eine andere/leere Installation verwenden; automatisches Zusammenführen
oder Klonen mit neuen IDs ist nicht implementiert. Offene importierte Extraktionsaufträge
werden angehalten und müssen bewusst erneut gestartet werden. Kein automatischer
Simulationsstart nach Import. Grenzen: 100.000 Zeilen und 50 MB JSON.

### Migration 0005 und lokaler Modelltest

Die additive Migration ergänzt Gruppen, Zuhörer, Sprecherrollen, Weltzeit und persistente
Simulationen. Bestehende Gespräche bleiben Einzelchats; ursprüngliche Spalten und Inhalte
bleiben erhalten. SQLite-Referenzspalten werden ohne Neuanlage bestehender Tabellen
ergänzt, um kaskadierende Verluste von Nachrichten und Quellen zu vermeiden. Vor einem
Update lokale Daten sichern. Ein Downgrade entfernt die neuen Phase-3-Verläufe.

Der opt-in Test verwendet ausschließlich eine temporäre synthetische Welt. Er prüft
zwei echte Modellbeiträge, übertragene persönliche Erinnerung, Abruf im neuen Gespräch,
Geheimnisisolation, Weltzeit und die gemeldeten Reasoning-Tokens:

```powershell
Set-Location C:\OpenWorld\backend
& ..\.venv\Scripts\python.exe -m tests.verify_simulation_live --model openworld-local-test --output "$env:TEMP\openworld-live-result.json"
```

Vorher das gewünschte lokale Modell unter diesem Bezeichner in LM Studio laden,
16k Kontext einstellen und den lokalen Server starten (Standardport 1234).
Der Test verändert keine reguläre Datenbank und lädt/entlädt keine Modelle selbst.

## Geführte KI-Einrichtung: Migration und Prüfprotokoll

Migration `0006` ergänzt ausschließlich Verbindungsprüfungen und
Erinnerungsfreigaben. Vorhandene Providerparameter, Chats, Ereignisregeln und
Simulationsfreigaben bleiben erhalten. Alte Weltexporte der Version 1 lassen sich
weiterhin importieren. Ein Downgrade auf `0005` entfernt nur die neuen
Einrichtungsmetadaten und Freigabeoptionen, nicht die vorhandenen Weltdaten.

Lokaler Prüfstand dieser UX-Überarbeitung:

| Prüfung | Ergebnis |
|---|---|
| Vollständige Backendtests (`python -m pytest -q`) | **229 bestanden** |
| Vollständige Browsertests (`npm run test:e2e`) | **26 bestanden** |
| TypeScript und Produktionsbuild (`npm run build`) | bestanden |
| Python-Lint (`python -m ruff check app tests migrations`) | bestanden |
| Echter Qwen 3.5 9B über LM Studio | **14 Prüfungen bestanden** |
| Lokale Migration `0005` → `0006` | alle bisherigen Werte in **27 Tabellen / 482 Zeilen** unverändert |
| SQLite-Integrität und Fremdschlüssel nach Migration | bestanden |

Die Tests decken Erststart und gleichzeitige Statusabfragen, Modelllisten,
LM Studio/Ollama/Online-Einrichtung, nicht geladene Modelle, ungültige Schlüssel,
unbekannte oder nicht unterstützte Modellparameter, begrenzte Wiederholungen,
unveränderte Experteneinstellungen und quellengebundene Erinnerungen ab.
Browserprüfungen öffnen die Einrichtung aus Chat, Gruppe und Simulation,
erhalten den Chatentwurf und setzen den ursprünglichen Vorgang fort.
Speicherfehler setzen die Erinnerungsschalter sichtbar zurück; deren Bedienung
löst keine Modellanfragen aus. Abschalten während einer laufenden
Erinnerungserkennung verhindert das Anwenden des Ergebnisses.

Der echte lokale Test hat den gesamten Ablauf mit automatisch ermitteltem
16k-Kontext durchlaufen: Modell finden → eine Antwort testen → Verbindung
speichern → Charakterchat → persönliche Erinnerung → Abruf in einem neuen
Gespräch → Simulation mit derselben KI. Die Erinnerungserkennung meldete
**0 Reasoning-Tokens**. Testwelt und Datenbank waren temporär und wurden entfernt;
das eigens geladene Testmodell wurde anschließend entladen.
Ollama und Online-Anbieter wurden durch lokale Protokoll- und Browsertests
geprüft, nicht durch kostenpflichtige Cloud-Anfragen.
Die Backendtests melden zusätzlich einen bestehenden Deprecation-Hinweis
des Starlette-Testclients; es gibt keine fehlgeschlagenen Tests.

Den echten Einrichtungstest bei bewusst geladenem LM-Studio-Modell erneut ausführen:

```powershell
Set-Location C:\OpenWorld\backend
& ..\.venv\Scripts\python.exe -m tests.verify_setup_live --model openworld-local-test --output "$env:TEMP\openworld-setup-result.json"
```

Wie beim Simulationstest vorher das gewünschte Modell unter diesem Bezeichner mit
16k-Kontext laden und den lokalen Server starten. Der Test selbst installiert,
lädt oder entlädt kein Modell und verändert keine reguläre Datenbank.

## Noch nicht implementiert / nächste Schritte

Tagesroutinen, Entfernungs-/Wegfindungssystem, benutzerdefinierte numerische
Beziehungs-Effektregeln und verzweigte Simulationen bleiben spätere Erweiterungen.
Keine willkürlichen numerischen Beziehungsänderungen durch das Modell.
Konten, serverseitige Autorisierung, Mehrbenutzersynchronisierung, PostgreSQL-Zertifizierung,
Feldvorlagen, Plugins und ein separater Google-Drive-Backupadapter sind ebenfalls offen.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
