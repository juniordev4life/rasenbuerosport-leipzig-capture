"""Highlight-Pipeline (losgelöster Prozess, vom office_agent nach dem Stop gestartet).

Ablauf für ein Spiel:
  0) Torliste + Aufstellung von der API holen (GET /recording/timeline).
  1) Nachspiel-Extraktion (extract_postmatch.py) auf dem Video-Ende:
     - Stats-Screens (Übersicht/Pässe/Abwehr) -> Bucket -> POST /recording/stats
       (ersetzt den Foto-Upload, schaltet den Match-Report frei)
     - OHNE Taps zusätzlich: Events-Tab -> Claude Vision -> Torliste
       (Zero-Tracking). 1v1: Seite == einziger Spieler der Seite. Bei
       pending-Spielen wird die Timeline per POST /recording/finalize
       nachgetragen (Ergebnis + nachgelagerte ELO).
  2) make_highlights.py -> Reel (ANKER-MODUS, sobald eine Torliste existiert —
     aus Taps ODER aus dem Events-Screen; sonst klassische Erkennung)
  3) Reel per gsutil öffentlich in den Bucket laden
  4) video_status + highlight_url ans Spiel PATCHen (ready / failed)

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


def api_post(path, body, timeout=120):
    """POST an die API (X-Agent-Secret). Fehler nicht fatal — data oder None."""
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API_BASE}{path}", data=payload, method="POST",
        headers={"X-Agent-Secret": AGENT_SECRET, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or "{}").get("data")
    except Exception as e:
        print(f"[pipeline] POST {path} fehlgeschlagen: {e}")
        return None


def fetch_timeline():
    """Spieldaten von der API: {score_timeline, players, pending, result_type}.
    None bei Fehler (API nicht erreichbar o.ae.)."""
    try:
        req = urllib.request.Request(
            f"{API_BASE}/recording/timeline?game_id={GAME_ID}",
            headers={"X-Agent-Secret": AGENT_SECRET})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read() or "{}").get("data") or {}
    except Exception as e:
        print(f"[pipeline] Timeline-Abruf fehlgeschlagen ({e}).")
        return None


def run_postmatch(base, skip_events):
    """Nachspiel-Extraktion (extract_postmatch.py) auf dem Video-Ende:
    Stats-Screens immer, Events-Torliste nur ohne Taps (skip_events=False).
    Gibt {goals, stats_files} zurueck oder None bei Fehlschlag."""
    events_out = f"events_{base}.json"
    env = {**os.environ, "VIDEO": VIDEO, "STATS_DIR": f"stats_{base}",
           "EVENTS_OUT": events_out}
    if skip_events:
        env["SKIP_EVENTS"] = "1"
    result = subprocess.run([sys.executable, "extract_postmatch.py"], env=env)
    if result.returncode != 0 or not os.path.exists(events_out):
        print("[pipeline] Nachspiel-Extraktion fehlgeschlagen — weiter ohne.")
        return None
    return json.load(open(events_out))


def build_app_timeline(goals, players):
    """Vision-Tore + Aufstellung -> App-Timeline (laufender Stand). 1v1: die
    Seite hat genau einen Spieler -> dessen Username als Schuetze; sonst
    bleibt der In-Game-Name aus dem Events-Screen im Banner stehen."""
    side_names = {"home": [], "away": []}
    for p in players or []:
        side_names.setdefault(p.get("team"), []).append(p.get("username"))
    timeline, h, a = [], 0, 0
    for g in sorted(goals, key=lambda e: e.get("minute") or 0):
        if g["team"] == "home":
            h += 1
        else:
            a += 1
        names = side_names.get(g["team"]) or []
        scored_by = names[0] if len(names) == 1 and names[0] else g.get("scorer")
        timeline.append({
            "home": h, "away": a, "team": g["team"], "minute": g["minute"],
            "period": "regular", "stoppage": 0, "scored_by": scored_by,
            "event_type": "goal",
        })
    return timeline


def submit_stats(stats_files):
    """Stats-PNGs oeffentlich in den Bucket laden und der API melden — gleiche
    Claude-Vision-Auswertung wie beim Foto-Upload, schaltet den Report frei."""
    if not stats_files:
        return
    if not GCS_BUCKET:
        print("[pipeline] GCS_BUCKET nicht gesetzt — Stats-Upload uebersprungen.")
        return
    images = {}
    for tab, path in stats_files.items():
        obj = f"{HIGHLIGHTS_PREFIX}/stats/{GAME_ID}/{tab}.png"
        up = subprocess.run(
            ["gsutil", "-h", "Content-Type:image/png", "cp", "-a", "public-read",
             path, f"gs://{GCS_BUCKET}/{obj}"])
        if up.returncode == 0:
            images[tab] = f"https://storage.googleapis.com/{GCS_BUCKET}/{obj}"
    if not images:
        print("[pipeline] Kein Stats-Bild hochgeladen.")
        return
    result = api_post("/recording/stats", {"game_id": GAME_ID, "images": images})
    if result:
        print(f"[pipeline] Match-Stats angewendet: {result.get('applied')}")


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

    # 0) Spieldaten holen: Taps, Aufstellung, pending-Status.
    data = fetch_timeline()
    tap_goals = [e for e in (data.get("score_timeline") if data else []) or []
                 if e.get("event_type", "goal") == "goal"]
    if data and data.get("result_type") == "penalty":
        print("[pipeline] HINWEIS: Spiel ging ins Elfmeterschiessen — der "
              "Schiessen-Clip wird im Anker-Modus noch nicht erzeugt.")

    # 1) Nachspiel-Extraktion: Stats-Screens immer; Events-Torliste nur ohne Taps.
    post = run_postmatch(base, skip_events=bool(tap_goals))
    if post:
        submit_stats(post.get("stats_files"))

    # Torliste fuer den Anker-Modus: Taps gewinnen; sonst die Vision-Tore.
    app_path = f"app_{base}.json"
    if tap_goals:
        with open(app_path, "w") as f:
            json.dump(data["score_timeline"], f)
        print(f"[pipeline] App-Timeline (Taps): {len(tap_goals)} Tore -> {app_path}")
    elif post and post.get("goals"):
        timeline = build_app_timeline(post["goals"], (data or {}).get("players"))
        with open(app_path, "w") as f:
            json.dump(timeline, f)
        print(f"[pipeline] Vision-Timeline (Events-Screen): {len(timeline)} Tore -> {app_path}")
        if data and data.get("pending"):
            finalized = api_post("/recording/finalize",
                                 {"game_id": GAME_ID, "score_timeline": timeline})
            if finalized:
                print(f"[pipeline] Spiel finalisiert: "
                      f"{finalized.get('score_home')}:{finalized.get('score_away')}")
        elif data:
            print("[pipeline] Spiel ist nicht pending — Timeline nur fuer die "
                  "Highlights genutzt, kein Finalize.")
    else:
        print("[pipeline] Keine Torliste (weder Taps noch Events-Screen) — "
              "klassische Ziffern-Erkennung.")

    # 2) Reel erzeugen.
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
