"""Office-Aufnahme-Agent (GERÜST).

Läuft auf dem Office-Rechner (i7/N100) NEBEN der Pipeline. Pollt die API nach
Start/Stop-Kommandos, nimmt per ffmpeg auf (`game_<id>.mov`), und meldet den
Status zurück. Bewusst klein + austauschbar:

  - get_next_command(): heute Polling der API ODER eine lokale Datei (Dev ohne
    API). Später leicht auf Pub/Sub-Pull umstellbar — nur diese Funktion tauschen.
  - Capture-Quelle plattformabhängig: macOS = Testbild (Entwicklung), Linux =
    v4l2 / `/dev/video0` (Office). Override per CAPTURE_INPUT. Drumherum identisch.
  - API-Auth wie euer Scheduler: Shared Secret im Header (X-Agent-Secret) —
    KEIN Firebase-User-Token, der Agent ist eine Maschine.

Auf dem Mac testbar gegen eine lokale Kommando-Datei + Testbild (siehe unten).
Umzug auf den i7 = nur die Capture-/Encoder-Zeilen.

============================= API-CONTRACT (GEBAUT) ==========================
Alle Endpoints existieren in der API (Migration 023 + 024). Auth für die
Agent-Endpoints: Shared Secret im Header `X-Agent-Secret`, api-seitig env
`AGENT_SECRET` (`requireAgentSecret`, analog Scheduler-Muster):

  GET  /api/v1/recording/next
       -> data: { "action": "start"|"stop"|"abort"|"idle", "game_id": "<id>" }
       Die App setzt das Kommando via POST /api/v1/recording/command
       (Firebase-Auth): "start" beim Anpfiff mit PROVISORISCHER recording_id
       (Client-UUID — das Spiel existiert erst nach Abpfiff), "stop" nach dem
       Speichern mit der ECHTEN game_id, "abort" beim Abbrechen (Zurück /
       Fehler-Dialog) — Agent stoppt UND löscht die Datei. Einzeiler-Slot,
       wird überschrieben, nie konsumiert. Ein "start" älter als 3 h kommt
       als "idle" zurück (Stale-Guard).

  POST /api/v1/recording/report
       body: { "recording_id": "<provisorisch>",
               "status": "recording"|"failed"|"stopped"|"aborted" }
       Rückkanal: sagt der App (die ihn via GET /recording/status pollt), ob
       die Aufnahme wirklich läuft. LÄUFT ÜBER DIE PROVISORISCHE recording_id,
       nicht über die echte game_id.

  PATCH /api/v1/games/:gameId
       body: { "video_status": "processing"|"ready"|"failed",
               "highlight_url"?: "..." }
       :gameId ist die ECHTE Spiel-UUID. Nach dem Stop: "processing" (Reel
       wird erzeugt), dann "ready" + highlight_url (Reel im Bucket) oder
       "failed". Der laufende Aufnahme-Status geht NICHT hierüber, sondern
       über /recording/report.

Nach dem Stop startet der Agent die Highlight-Pipeline als eigenen Prozess
(process_highlights.py): make_highlights -> Reel -> gsutil-Upload (public) ->
PATCH ready/failed. Sie läuft mit dem venv-Python (cv2) — den Agent daher mit
`venv/bin/python office_agent.py` starten, sobald Highlights aktiv sind.
=============================================================================
"""
import json
import os
import platform
import shlex
import signal
import subprocess
import sys
import time
import urllib.request

# --- Konfiguration (env) ----------------------------------------------------
API_BASE = os.environ.get("API_BASE", "http://localhost:3001/api/v1")
AGENT_SECRET = os.environ.get("AGENT_SECRET", "")          # X-Agent-Secret
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "3"))
REC_DIR = os.environ.get("REC_DIR", "recordings")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")               # Reel-Bucket (von process_highlights genutzt)
MAX_REC_SECONDS = int(os.environ.get("MAX_REC_SECONDS", str(3 * 3600)))  # Auto-Stop-Schutz
LOCAL_COMMAND_FILE = os.environ.get("LOCAL_COMMAND_FILE")   # Dev: ohne API testen
START_GRACE_SECONDS = float(os.environ.get("START_GRACE_SECONDS", "1.5"))  # Health-Check-Fenster

_proc = None
_rec_path = None
_rec_started = 0.0
_failed_start_gid = None   # gegen Retry-Spam: gid, deren Start schon scheiterte
_rec_id = None             # provisorische recording_id der laufenden Aufnahme (Rückkanal)
_handled_abort_gid = None  # gegen Abbruch-Spam: zuletzt bearbeitete abort-gid


def capture_input_args():
    """ffmpeg-Eingang je nach Plattform. CAPTURE_INPUT übersteuert komplett.

    shlex-Quoting: avfoundation-GERÄTENAMEN statt Indizes verwenden — die
    Indizes sind zwischen Enumerationen nicht stabil (Continuity-Kameras!).
    Namen mit Leerzeichen in Anführungszeichen:
      CAPTURE_INPUT='-f avfoundation ... -i "USB3.0 Video:USB3.0 Audio"'
    """
    override = os.environ.get("CAPTURE_INPUT")
    if override:
        return shlex.split(override)
    if platform.system() == "Linux":   # Office-i7: echte Capture-Box
        dev = os.environ.get("CAPTURE_DEV", "/dev/video0")
        return ["-f", "v4l2", "-framerate", "30", "-video_size", "1920x1080", "-i", dev]
    # Mac/Dev: Testbild statt echter Box. -re = in Echtzeit (wie eine echte
    # Capture-Box), damit Start/Stop-Timing beim Entwickeln realistisch ist.
    return ["-re", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30"]


def encode_args():
    """Encoder. Portabel: libx264. Auf dem i7 später ENCODE_ARGS='-c:v h264_qsv ...'."""
    return shlex.split(os.environ.get("ENCODE_ARGS", "-c:v libx264 -preset veryfast -crf 23"))


def _api(method, path, body=None):
    """API-Aufruf mit Shared-Secret-Header. Gibt das `data`-Feld der Antwort zurück."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API_BASE + path, data=data, method=method,
        headers={"X-Agent-Secret": AGENT_SECRET, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        payload = json.loads(r.read() or "{}")
    return payload.get("data", payload)


def get_next_command():
    """Nächstes Kommando holen. AUSTAUSCHBAR. Dev: lokale Datei; sonst API-Polling.
    Erwartet {action: 'start'|'stop'|'idle', game_id}."""
    if LOCAL_COMMAND_FILE and os.path.exists(LOCAL_COMMAND_FILE):
        try:
            return json.load(open(LOCAL_COMMAND_FILE))
        except Exception:
            return {"action": "idle"}
    try:
        return _api("GET", "/recording/next") or {"action": "idle"}
    except Exception as e:
        print("  Poll-Fehler:", e)
        return {"action": "idle"}


def start_recording(game_id):
    global _proc, _rec_path, _rec_started, _failed_start_gid, _rec_id
    if _proc or game_id == _failed_start_gid:
        return
    os.makedirs(REC_DIR, exist_ok=True)
    rec_path = os.path.join(REC_DIR, f"game_{game_id}.mov")
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           *capture_input_args(), *encode_args(), "-c:a", "aac", rec_path]
    proc = subprocess.Popen(cmd)

    # Health-Check: eine kaputte Capture-Config (falsches -pixel_format, durch OBS
    # gesperrtes Gerät) lässt ffmpeg binnen Millisekunden sterben. Ohne diese
    # Prüfung bliebe das tote Prozess-Handle gesetzt und würde den Agent
    # verklemmen — jeder spätere Start würde still ignoriert. Kurz warten, dann
    # prüfen, ob ffmpeg noch lebt, bevor wir den „recording"-Zustand zusagen.
    time.sleep(START_GRACE_SECONDS)
    if proc.poll() is not None:
        _failed_start_gid = game_id   # diese gid nicht im Sekundentakt neu versuchen
        print(f"  FEHLER: ffmpeg sofort beendet (Code {proc.returncode}). Aufnahme "
              f"NICHT aktiv — ffmpeg-Fehler oben prüfen (Pixelformat? Gerät belegt?).")
        report_recording_status(game_id, "failed")   # App zeigt daraufhin den Fehler-Dialog
        return

    _failed_start_gid = None
    _proc = proc
    _rec_path = rec_path
    _rec_id = game_id   # provisorische ID merken: der Status-Rückkanal läuft darüber
    _rec_started = time.monotonic()
    print(f"  Aufnahme gestartet: {_rec_path}")
    report_recording_status(game_id, "recording")


def stop_recording(game_id):
    global _proc, _rec_path, _rec_id
    if not _proc:
        return
    _proc.send_signal(signal.SIGINT)   # ffmpeg sauber beenden -> Datei finalisieren
    try:
        _proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        _proc.kill()
    path = _rec_path
    rec_id = _rec_id
    _proc, _rec_path, _rec_id = None, None, None
    print(f"  Aufnahme gestoppt: {path}")
    if rec_id:
        report_recording_status(rec_id, "stopped")   # Rückkanal über die provisorische ID
    # Highlight-Pipeline als eigener Prozess: erzeugt das Reel, lädt es hoch und
    # PATCHt am Ende ready/failed. Status zunächst "processing" (App: „wird erstellt").
    report_status(game_id, "processing")              # video_status an der echten game_id
    start_highlight_pipeline(game_id, path)


def start_highlight_pipeline(game_id, video_path):
    """Startet die Highlight-Pipeline als losgelösten Prozess (process_highlights.py):
    make_highlights -> Reel -> Upload -> PATCH ready/failed. Fire-and-forget, damit
    der Poll-Loop frei bleibt (die Verarbeitung dauert Minuten). Läuft mit demselben
    Interpreter wie der Agent (venv-Python für cv2)."""
    if not video_path or not os.path.exists(video_path):
        print("  Kein Aufnahme-Video — Highlight-Pipeline übersprungen.")
        report_status(game_id, "failed")
        return
    env = {**os.environ, "PIPE_GAME_ID": game_id, "PIPE_VIDEO": video_path}
    try:
        subprocess.Popen([sys.executable, "process_highlights.py"],
                         env=env, start_new_session=True)
        print(f"  Highlight-Pipeline gestartet (Spiel {game_id}).")
    except Exception as e:
        print(f"  Highlight-Pipeline-Start fehlgeschlagen: {e}")
        report_status(game_id, "failed")


def report_status(game_id, status, **extra):
    """video_status an die echte Spiel-Zeile melden (PATCH /games/:id). Erst ab
    Upload genutzt. Fehler nicht fatal."""
    try:
        _api("PATCH", f"/games/{game_id}", {"video_status": status, **extra})
    except Exception as e:
        print(f"  Status-Meldung ({status}) fehlgeschlagen:", e)


def report_recording_status(recording_id, status):
    """Capture-Status in den recording_status-Rückkanal melden, damit die App
    weiß, ob die Aufnahme wirklich läuft (recording/failed) bzw. wie sie endete
    (stopped/aborted). Läuft über die PROVISORISCHE recording_id (die die App
    pollt), nicht über die echte game_id. Fehler nicht fatal."""
    try:
        _api("POST", "/recording/report",
             {"recording_id": recording_id, "status": status})
    except Exception as e:
        print(f"  Status-Report ({status}) fehlgeschlagen:", e)


def abort_recording(game_id):
    """Abbruch: laufende Aufnahme stoppen UND die Datei verwerfen (im Gegensatz
    zu stop, das sie für den Highlight-Schnitt behält). Auch dann sinnvoll, wenn
    gerade nicht aufgenommen wird (z.B. nach fehlgeschlagenem Start) — räumt dann
    eine evtl. angefangene Datei weg. Wird gesetzt, wenn der User im Live-Step
    zurückgeht oder den Fehler-Dialog schließt."""
    global _proc, _rec_path, _rec_id, _failed_start_gid
    if _proc:
        _proc.send_signal(signal.SIGINT)
        try:
            _proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _proc.kill()
    # Pfad rekonstruieren — gilt auch, wenn _rec_path nie gesetzt wurde (failed).
    path = _rec_path or os.path.join(REC_DIR, f"game_{game_id}.mov")
    _proc, _rec_path, _rec_id = None, None, None
    if game_id == _failed_start_gid:
        _failed_start_gid = None
    if os.path.exists(path):
        try:
            os.remove(path)
            print(f"  Aufnahme abgebrochen + Datei gelöscht: {path}")
        except OSError as e:
            print(f"  Abbruch: Datei konnte nicht gelöscht werden ({e}).")
    else:
        print("  Aufnahme abgebrochen (keine Datei zu löschen).")
    report_recording_status(game_id, "aborted")


def main():
    global _proc, _rec_path, _handled_abort_gid
    print(f"Office-Agent läuft. API={API_BASE}  Capture-Plattform={platform.system()}"
          f"{'  [Dev: lokale Kommando-Datei]' if LOCAL_COMMAND_FILE else ''}")
    while True:
        cmd = get_next_command()
        action, gid = cmd.get("action"), cmd.get("game_id")
        if action == "start" and not _proc:
            start_recording(gid)
        elif action == "stop" and _proc:
            stop_recording(gid)
        elif action == "abort" and gid != _handled_abort_gid:
            abort_recording(gid)         # stoppt + löscht; greift auch ohne laufende Aufnahme
            _handled_abort_gid = gid     # Slot wird nie konsumiert -> nur einmal je gid abbrechen
        # ffmpeg unerwartet gestorben (Kabel raus, Encoder-Fehler)? Nicht
        # weiter „recording" vorgaukeln — melden und zurücksetzen, damit der
        # nächste Start wieder greift.
        if _proc and _proc.poll() is not None:
            print(f"  FEHLER: ffmpeg während der Aufnahme beendet (Code {_proc.returncode}).")
            _proc, _rec_path = None, None
        elif _proc and time.monotonic() - _rec_started > MAX_REC_SECONDS:
            print("  Auto-Stop (Maximaldauer erreicht).")
            stop_recording(gid)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        if _proc:
            _proc.send_signal(signal.SIGINT)
        print("\nAgent beendet.")
