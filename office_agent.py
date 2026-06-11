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

========================= API-CONTRACT (GEBAUT) ==============================
Beide Endpoints existieren in der API (Branch feat/recording-agent-endpoints,
Migration 023). Auth: Shared Secret im Header `X-Agent-Secret`, api-seitig
env `AGENT_SECRET` (`requireAgentSecret`, analog Scheduler-Muster):

  GET  /api/v1/recording/next
       -> data: { "action": "start"|"stop"|"idle", "game_id": "<id>" }
       Die App setzt das Kommando via POST /api/v1/recording/command
       (Firebase-Auth): "start" beim Anpfiff mit PROVISORISCHER recording_id
       (Client-UUID — das Spiel existiert erst nach Abpfiff), "stop" nach dem
       Speichern mit der ECHTEN game_id. Einzeiler-Slot, wird überschrieben,
       nie konsumiert. Ein "start" älter als 3 h kommt als "idle" zurück
       (Stale-Guard gegen verspätete Agent-Starts).

  PATCH /api/v1/games/:gameId
       body: { "video_status": "recording"|"uploaded"|"ready",
               "highlight_url"?: "..." }
       (Antwortformat wie üblich: { code, title, message, data, error })
       :gameId muss eine echte Spiel-UUID sein. Der "recording"-Report nach
       dem Start läuft mit der provisorischen ID auf 404 — bewusst, nicht
       fatal (das Spiel existiert da noch nicht). Der "uploaded"-Report nach
       dem Stop trägt die echte ID aus dem Stop-Kommando und sitzt.
=============================================================================
"""
import json
import os
import platform
import shlex
import signal
import subprocess
import time
import urllib.request

# --- Konfiguration (env) ----------------------------------------------------
API_BASE = os.environ.get("API_BASE", "http://localhost:3001/api/v1")
AGENT_SECRET = os.environ.get("AGENT_SECRET", "")          # X-Agent-Secret
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "3"))
REC_DIR = os.environ.get("REC_DIR", "recordings")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")               # für den Upload-Stub
MAX_REC_SECONDS = int(os.environ.get("MAX_REC_SECONDS", str(3 * 3600)))  # Auto-Stop-Schutz
LOCAL_COMMAND_FILE = os.environ.get("LOCAL_COMMAND_FILE")   # Dev: ohne API testen

_proc = None
_rec_path = None
_rec_started = 0.0


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
    global _proc, _rec_path, _rec_started
    if _proc:
        return
    os.makedirs(REC_DIR, exist_ok=True)
    _rec_path = os.path.join(REC_DIR, f"game_{game_id}.mov")
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           *capture_input_args(), *encode_args(), "-c:a", "aac", _rec_path]
    _proc = subprocess.Popen(cmd)
    _rec_started = time.monotonic()
    print(f"  Aufnahme gestartet: {_rec_path}")
    report_status(game_id, "recording")


def stop_recording(game_id):
    global _proc, _rec_path
    if not _proc:
        return
    _proc.send_signal(signal.SIGINT)   # ffmpeg sauber beenden -> Datei finalisieren
    try:
        _proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        _proc.kill()
    path = _rec_path
    _proc, _rec_path = None, None
    print(f"  Aufnahme gestoppt: {path}")
    upload(game_id, path)
    report_status(game_id, "uploaded")


def upload(game_id, path):
    """STUB: Video (bzw. später die fertigen Highlights) in den Bucket laden."""
    if not GCS_BUCKET:
        print(f"  [Upload-Stub] würde {path} nach gs://<bucket>/game_{game_id}/ laden")
        return
    subprocess.run(["gsutil", "cp", path, f"gs://{GCS_BUCKET}/game_{game_id}/"], check=False)


def report_status(game_id, status, **extra):
    """Status an die API melden (Endpoint laut Contract). Fehler nicht fatal."""
    try:
        _api("PATCH", f"/games/{game_id}", {"video_status": status, **extra})
    except Exception as e:
        print(f"  Status-Meldung ({status}) fehlgeschlagen:", e)


def main():
    print(f"Office-Agent läuft. API={API_BASE}  Capture-Plattform={platform.system()}"
          f"{'  [Dev: lokale Kommando-Datei]' if LOCAL_COMMAND_FILE else ''}")
    while True:
        cmd = get_next_command()
        action, gid = cmd.get("action"), cmd.get("game_id")
        if action == "start" and not _proc:
            start_recording(gid)
        elif action == "stop" and _proc:
            stop_recording(gid)
        if _proc and time.monotonic() - _rec_started > MAX_REC_SECONDS:
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
