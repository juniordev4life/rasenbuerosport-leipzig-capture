"""Highlight-Pipeline (losgelöster Prozess, vom office_agent nach dem Stop gestartet).

Drei Schritte für ein Spiel:
  1) make_highlights.py auf die Aufnahme -> Reel `<base>_highlights.mp4`
  2) Reel per gsutil öffentlich in den Bucket laden
  3) video_status + highlight_url ans Spiel PATCHen (ready / failed)

Bewusst eigenständig statt im Agent: make_highlights braucht cv2 (venv) und
läuft Minuten — der Agent-Poll-Loop bleibt so frei. Konfiguration kommt
komplett aus dem Environment (der Agent vererbt es):

  PIPE_GAME_ID       echte Spiel-UUID (Ziel des PATCH)
  PIPE_VIDEO         Pfad der Aufnahme (z.B. recordings/game_<recId>.mov)
  API_BASE           z.B. http://localhost:3001/api/v1
  AGENT_SECRET       X-Agent-Secret
  GCS_BUCKET         Storage-Bucket (= FIREBASE_STORAGE_BUCKET)
  HIGHLIGHTS_PREFIX  Ordner im Bucket (Prod: "highlights", Dev: "highlights-dev")

Der Reel wird unter <prefix>/<gameId>.mp4 abgelegt; die App rendert die
zurückgemeldete highlight_url direkt in einem <video>-Tag.
"""
import json
import os
import subprocess
import sys
import urllib.request

API_BASE = os.environ.get("API_BASE", "http://localhost:3001/api/v1")
AGENT_SECRET = os.environ.get("AGENT_SECRET", "")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
HIGHLIGHTS_PREFIX = os.environ.get("HIGHLIGHTS_PREFIX", "highlights")
GAME_ID = os.environ.get("PIPE_GAME_ID")
VIDEO = os.environ.get("PIPE_VIDEO")


def patch_status(status, **extra):
    """video_status (+ optional highlight_url) ans Spiel melden. Fehler nicht fatal."""
    body = json.dumps({"video_status": status, **extra}).encode()
    req = urllib.request.Request(
        f"{API_BASE}/games/{GAME_ID}", data=body, method="PATCH",
        headers={"X-Agent-Secret": AGENT_SECRET, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        print(f"[pipeline] video_status={status} gemeldet.")
    except Exception as e:
        print(f"[pipeline] PATCH ({status}) fehlgeschlagen: {e}")


def main():
    if not GAME_ID or not VIDEO:
        print("[pipeline] PIPE_GAME_ID / PIPE_VIDEO fehlen — Abbruch.")
        return
    if not os.path.exists(VIDEO):
        print(f"[pipeline] Aufnahme nicht gefunden: {VIDEO}")
        patch_status("failed")
        return

    base = os.path.splitext(os.path.basename(VIDEO))[0]
    reel = f"{base}_highlights.mp4"   # make_highlights legt das Reel im CWD ab

    # 1) Reel erzeugen (Vision-only; App-Tore/Schütze-Banner kommen als Stufe 2).
    print(f"[pipeline] make_highlights für {VIDEO} ...")
    result = subprocess.run([sys.executable, "make_highlights.py", VIDEO])
    if result.returncode != 0 or not os.path.exists(reel):
        # Häufigster gutartiger Fall: keine Tore erkannt -> kein Reel.
        print(f"[pipeline] Kein Reel erzeugt (rc={result.returncode}, reel da: {os.path.exists(reel)}).")
        patch_status("failed")
        return

    # 2) Reel öffentlich in den Bucket laden (Pendant zu file.save()+makePublic() der API).
    if not GCS_BUCKET:
        print("[pipeline] GCS_BUCKET nicht gesetzt — Upload übersprungen, Reel bleibt lokal.")
        patch_status("failed")
        return
    obj = f"{HIGHLIGHTS_PREFIX}/{GAME_ID}.mp4"
    dest = f"gs://{GCS_BUCKET}/{obj}"
    print(f"[pipeline] Upload {reel} -> {dest}")
    up = subprocess.run(
        ["gsutil", "-h", "Content-Type:video/mp4", "cp", "-a", "public-read", reel, dest])
    if up.returncode != 0:
        print(f"[pipeline] Upload fehlgeschlagen (rc={up.returncode}).")
        patch_status("failed")
        return

    # 3) Verknüpfen — die App rendert genau diese URL.
    url = f"https://storage.googleapis.com/{GCS_BUCKET}/{obj}"
    patch_status("ready", highlight_url=url)
    print(f"[pipeline] Fertig: {url}")


if __name__ == "__main__":
    main()
