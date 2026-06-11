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
  `game_<id>.mov`, Upload-Stub, Status-Rückmeldung. Auf dem Mac getestet:
  Kommando-Datei UND voller Poll-Loop gegen Mock-API (Secret-Header,
  recording/uploaded-PATCHes, saubere 1080p-Datei). Die API-Endpoints sind
  GEBAUT (api: Branch `feat/recording-agent-endpoints` + Migration 023,
  app: Branch `feat/recording-trigger`) — Contract-Stand im Docstring.
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
4. Browser-Flow lokal testen (Endpoints sind gebaut, PRs mergen + Migration
   023 einspielen). Drei Terminals + Capture-Card am Mac:
   - API: `npm run db:local`, Migration anwenden, `AGENT_SECRET=<secret>` in
     .env, `npm run dev` (Port 3001)
   - App: `npm run dev`, Browser `localhost:5173`
   - Agent: `AGENT_SECRET=<secret> CAPTURE_INPUT="-f avfoundation -framerate 30
     -video_size 1920x1080 -i 1:0" python3 office_agent.py`
     (Geräte-Index via `ffmpeg -f avfoundation -list_devices true -i ""`;
     API_BASE-Default zeigt jetzt auf 3001)
   - In der App: Spiel anlegen → Anpfiff (= start) → speichern (= stop).
     Danach hat die games-Zeile `video_status='uploaded'`.
5. Auf dem geliehenen i7 deployen (Ubuntu Server, headless) — nur die
   Capture-Zeile (v4l2/`/dev/video0`) + Encoder (`ENCODE_ARGS=-c:v h264_qsv …`).
   Unter systemd `PYTHONUNBUFFERED=1` setzen, sonst verschluckt der
   stdout-Buffer die Agent-Logs (auf dem Mac schon beobachtet).

## Gotchas
- pytesseract läuft NICHT in Claudes Sandbox (kann TMPDIR nicht lesen) — OCR-
  Skripte führt Marco selbst aus. cv2/Template-Matching geht in der Sandbox.
- Aufnahme per ffmpeg DIREKT, nicht OBS (leichter, headless-tauglich).
- Maschinen-Auth = Shared Secret im Header (`X-Agent-Secret`), wie das
  Scheduler-Muster der API — KEIN Firebase-User-Token für den Agent.
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
