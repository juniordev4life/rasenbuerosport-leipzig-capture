# Handoff — RasenbüroSport Leipzig Capture

Kurzer Stand zum Weitermachen in einer neuen Sitzung.
Tiefe Details: `FC26_VISION_POC_STAND.md`. Office-Rechner-Setup: `SETUP_MINIPC.md`.
API-Contract des Agents: oben im Docstring von `office_agent.py`.

## Was das ist
Computer-Vision-Pipeline für EA-FC-Spiele: liest aus der Aufnahme die
Bildschirm-Overlays (Skin, Spielstand, Minute), erkennt Tore, schneidet
Highlight-Clips mit gestyltem Banner und baut ein Reel pro Spiel. Dazu ein
Aufnahme-Agent für den Office-Rechner und ein Gerüst für KI-gestützte
Schützenerkennung.

## Repo-Landschaft
- DIESES Repo (`rasenbuerosport-leipzig-capture`) = die Office-/Aufnahme-Seite
  (Pipeline + Agent). Eigenständig, NICHT Teil der App. Jetzt git-versioniert.
- `rasenbuerosport-leipzig-app` (SvelteKit) + `rasenbuerosport-leipzig-api`
  (Fastify) = separate Repos. Daten in Postgres, Firebase = Auth + statisches
  Hosting. Highlights werden als Datei je Spiel-ID abgelegt und verlinkt.
- Der alte Ordner `~/Projects/fc26-vision-poc` existiert noch (Fallback + hat
  das eingerichtete venv). Kann weg, sobald dieses Repo bestätigt läuft.

## Stand: funktioniert
- Automatische Skin-Erkennung (Bundesliga / Cross-Nation / Premier) per
  HUD-Abgleich + Mehrheitsentscheid — kein manuelles Wählen, keine Dateinamen.
- Spielstand per Template-Matching (alle Skins; OCR war zu unzuverlässig).
- Minute per Ziffern-/Linien-Modus.
- Elfmeterschießen: Bundesliga (HUD-Lücke) + Cross-Nation (ELFMETER-Label).
- Replay-bewusster Schnitt (Tor-Moment als Anker), gestyltes Banner mit
  Schütze + Vorlage rechts daneben (baseline-bündig).
- Merge der App-Tore (Schütze/Vorlage) mit den Vision-Toren über die
  Spielstand-Reihenfolge (`merge_scorers.py`) — keine Uhrzeit-Synchronisierung.

## Stand: Gerüst (noch nicht scharf)
- `office_agent.py` — Aufnahme-Agent. Poll-Loop, ffmpeg-Aufnahme
  `game_<id>.mov`, Upload-Stub, Status-Rückmeldung. END-TO-END LOKAL VERIFIZIERT
  (2026-06-11): echte Capture-Card am Mac, App-Anpfiff → Aufnahme → Speichern →
  Stop; die games-Zeile trägt danach `recording_id` (= Dateiname) + `video_status`.
  API-Endpoints GEBAUT (Contract im Docstring). Health-Check drin: stirbt ffmpeg
  sofort (falsche Config / gesperrtes Gerät), wird das erkannt und zurückgesetzt,
  statt fälschlich „recording" zu melden. Abbruch + Fehler-Rückkanal gebaut:
  `abort` stoppt UND löscht die Datei; der Agent meldet recording/failed/stopped/
  aborted über `POST /recording/report`, damit die App einen Fehlstart erkennt
  (Migration 024). Nach dem Stop startet der Agent die Highlight-Pipeline
  (`process_highlights.py`, eigener Prozess): make_highlights → Reel → gsutil-
  Upload (public) → PATCH `video_status` (processing → ready + `highlight_url`,
  sonst failed). Vision-only MVP — Schütze-Banner ist Stufe 2 (Nächste Schritte 5).
- `detect_scorer.py` — KI-Schützenerkennung (Claude Sonnet), eval-Modus misst
  die Trefferquote gegen Wahrheits-Labels. Läuft erst mit Material + API-Key.

## Pipeline starten (Beispiel)
```bash
# venv im neuen Repo zuerst anlegen (siehe Nächste Schritte 1):
venv/bin/python make_highlights.py videos/<spiel>.mov   # genaue Flags: STAND.md
# optional mit App-Toren (Schütze/Vorlage): app_<spiel>.json daneben legen

# Agent-Test auf dem Mac (ohne API/Box, Testbild):
echo '{"action":"start","game_id":"test1"}' > command.json
LOCAL_COMMAND_FILE=command.json venv/bin/python office_agent.py
# in einem zweiten Terminal: action auf "stop" setzen
```

## Nächste Schritte
1. venv im neuen Repo neu anlegen (das alte venv ist pfadgebunden, zieht nicht um):
   `python3 -m venv venv && venv/bin/pip install -r requirements.txt`
   (System zusätzlich: ffmpeg, tesseract-ocr + -deu).
2. Wenn die Festplatte zurück ist: Ziffern-Templates auf 0-9 erweitern
   (hochstehende Spiele je Skin → samples + Builder).
3. Scorer-Eval auf Sohn-vs-CPU-Material mit Wahrheits-Labels laufen lassen
   (~10 Spiele / 30-50 Tore) → Hybrid-Trefferquote messen, dann entscheiden.
   Idee: Parallelbetrieb — die manuellen App-Taps SIND die Wahrheit, der
   Eval-Satz fällt im Normalbetrieb gratis ab; danach Hi-Konfidenz automatisieren.
4. ERLEDIGT (2026-06-11): Browser-Flow lokal verifiziert. Aufbau, drei Terminals
   + Capture-Card am Mac:
   - API: `npm run db:local`, Migration 023 anwenden, `AGENT_SECRET=<secret>` in
     .env, `npm run dev` (Port 3001). Achtung: `node --watch` lädt `.env`-
     Änderungen NICHT neu — nach einem Edit den API-Prozess neu starten.
   - App: `npm run dev`, Browser `localhost:5173`
   - Agent: `AGENT_SECRET=<secret> CAPTURE_INPUT='-f avfoundation -framerate 30
     -video_size 1920x1080 -pixel_format uyvy422 -i "USB3.0 Video:USB3.0 Audio"'
     python3 office_agent.py`
     (Gerätenamen via `ffmpeg -f avfoundation -list_devices true -i ""` —
     NAMEN nutzen, nicht Indizes: nicht stabil. `-pixel_format uyvy422` nötig,
     die Karte kann kein yuv420p; sonst `nv12`. OBS/QuickTime/Teams VORHER
     schließen — sie sperren die Karte. API_BASE-Default zeigt auf 3001.)
   - In der App: Spiel anlegen → Anpfiff (= start) → speichern (= stop).
5. ERLEDIGT (MVP, Vision-only): Highlights verdrahtet. Nach dem Stop startet der
   Agent `process_highlights.py` (eigener Prozess): `make_highlights` → Reel →
   `gsutil cp -a public-read` nach `gs://$GCS_BUCKET/$HIGHLIGHTS_PREFIX/<gameId>.mp4`
   → PATCH (processing → ready + `highlight_url`, sonst failed). Voraussetzungen:
   venv mit cv2 (Agent daher mit `venv/bin/python office_agent.py` starten, weil
   die Pipeline cv2 braucht), `gcloud`-Login für gsutil, und die env-Variablen
   `GCS_BUCKET=<FIREBASE_STORAGE_BUCKET>` + `HIGHLIGHTS_PREFIX` (Prod: `highlights`,
   lokal: `highlights-dev`). Test am Mac braucht ein echtes Spielvideo (Testbild
   hat kein HUD → keine Tore → `failed`).
   OFFEN (Stufe 2): Schütze/Vorlage-Banner aus den App-Toren (`merge_scorers`) —
   dafür müsste der Agent die Timeline + Usernames von der API holen und ein
   `app_<base>.json` bauen; aktuell läuft die Pipeline rein über die Vision-Tore.
6. Auf dem geliehenen i7 deployen (Ubuntu Server, headless) — nur die
   Capture-Zeile (v4l2/`/dev/video0`) + Encoder (`ENCODE_ARGS=-c:v h264_qsv …`).
   Unter systemd `PYTHONUNBUFFERED=1` setzen, sonst verschluckt der
   stdout-Buffer die Agent-Logs (auf dem Mac schon beobachtet).

## Gotchas
- pytesseract läuft NICHT in Claudes Sandbox (kann TMPDIR nicht lesen) — OCR-
  Skripte führt Marco selbst aus. cv2/Template-Matching geht in der Sandbox.
- Aufnahme per ffmpeg DIREKT, nicht OBS (leichter, headless-tauglich).
- macOS-Capture (Dev): Geräte per NAME ansprechen (`CAPTURE_INPUT` mit shlex-
  Quoting), avfoundation-Indizes sind zwischen Aufrufen instabil. Die USB3.0-
  Karte braucht `-pixel_format uyvy422` (sonst `nv12`), kann kein yuv420p.
  ffmpeg `Could not lock device for configuration` = Karte von OBS/QuickTime/
  Teams belegt → App schließen.
- Status-Semantik (noch unfertig): `uploaded` ist aktuell optimistisch (Upload
  ist Stub, Datei bleibt lokal); `recording` wird beim Start nie persistiert
  (Spiel existiert noch nicht → 404). Erst mit echtem Upload + `ready` wird die
  Statusspalte aussagekräftig (Nächste Schritte 5).
- Maschinen-Auth = Shared Secret im Header (`X-Agent-Secret`), wie das
  Scheduler-Muster der API — KEIN Firebase-User-Token für den Agent. Wert in
  der API-`.env` (`AGENT_SECRET`) und im Agent-Env muss identisch sein, sonst 401.
- In dieser Umgebung nur `python3` (nicht `python`); cv2 über `venv/bin/python`.
- Git künftig: Feature-Branch + PR. Der Initial-Commit auf `main` ist die
  Bootstrap-Ausnahme.

## Wichtigste Dateien
- `make_highlights.py` — Orchestrator (Frames → Skin → Timeline → optional
  Merge → Schnitt → Reel).
- `build_score_timeline.py` / `detect_skin.py` / `hud_profiles.py` — Erkennung.
- `cut_highlights.py` — Schnitt + Banner. `merge_scorers.py` — App-Merge.
- `office_agent.py` / `detect_scorer.py` — Office-Agent / Scorer-Gerüst.
- `build_templates*.py` — Templates aus `samples/` erzeugen.
