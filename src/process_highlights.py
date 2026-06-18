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
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

from detect_skin import detect_skin_from_dir
from make_highlights import FPS, extract_frames
from paths import script

API_BASE = os.environ.get("API_BASE", "http://localhost:3001/api/v1")
AGENT_SECRET = os.environ.get("AGENT_SECRET", "")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
HIGHLIGHTS_PREFIX = os.environ.get("HIGHLIGHTS_PREFIX", "highlights")
GAME_ID = os.environ.get("PIPE_GAME_ID")
VIDEO = os.environ.get("PIPE_VIDEO")
# Aufraeumen nach dem Lauf. CLEANUP=0 schaltet alles ab. RECORDING_RETENTION_DAYS
# >0 loescht Aufnahmen aelter als X Tage (OPT-IN, 0 = behalten — die Aufnahme ist
# die Re-Processing-Versicherung). ORPHAN_SCRATCH_HOURS schuetzt frische bzw.
# parallel laufende Scratch-Reste vor dem Verwaist-Sweep.
CLEANUP = os.environ.get("CLEANUP", "1") != "0"
RECORDING_RETENTION_DAYS = int(os.environ.get("RECORDING_RETENTION_DAYS", "0"))
ORPHAN_SCRATCH_HOURS = int(os.environ.get("ORPHAN_SCRATCH_HOURS", "24"))


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
    result = subprocess.run([sys.executable, script("extract_postmatch.py")], env=env)
    if result.returncode != 0 or not os.path.exists(events_out):
        print("[pipeline] Nachspiel-Extraktion fehlgeschlagen — weiter ohne.")
        return None
    return json.load(open(events_out))


def build_app_timeline(goals, players):
    """Vision-Tore + Aufstellung -> App-Timeline (laufender Stand). 1v1: die
    Seite hat genau einen Spieler -> dessen player_id als scored_by (die App
    loest Schuetzen ueber die SPIELER-ID auf, nicht ueber den Namen!) plus
    scored_by_name als Anzeigename fuers Highlight-Banner. Bei mehreren
    Spielern je Seite (2v2) bleibt nur der In-Game-Name als scored_by_name —
    die Marker-Farben-Zuordnung ist Stufe 2."""
    side_players = {"home": [], "away": []}
    for p in players or []:
        side_players.setdefault(p.get("team"), []).append(p)
    timeline, h, a = [], 0, 0
    for g in sorted(goals, key=lambda e: e.get("minute") or 0):
        if g["team"] == "home":
            h += 1
        else:
            a += 1
        entry = {
            "home": h, "away": a, "team": g["team"], "minute": g["minute"],
            "period": "regular", "stoppage": 0, "event_type": "goal",
        }
        side = side_players.get(g["team"]) or []
        if len(side) == 1 and side[0].get("player_id"):
            entry["scored_by"] = side[0]["player_id"]
            entry["scored_by_name"] = side[0].get("username") or g.get("scorer")
        elif g.get("scorer"):
            entry["scored_by_name"] = g["scorer"]
        timeline.append(entry)
    return timeline


def reconcile_to_final_score(timeline, final_score, players):
    """Fuellt die Vision-Timeline auf den massgeblichen Endstand auf.

    Die Events-Liste kann durchs Scrollen ein Tor verpassen (beobachtet: 2 von
    3) — der Kopfzeilen-Score (`final_score` aus extract_postmatch) ist dagegen
    immer sichtbar und damit autoritativ. Pro Team werden fehlende Tore als
    Platzhalter ANGEHAENGT: laufender Stand bis zum Endstand, `minute=None`
    (die API-Chronologiepruefung ueberspringt minutenlose Eintraege). 1v1: der
    Platzhalter bekommt den einzigen Spieler der Seite als Schuetzen (richtiger
    Schuetze, nur die Minute fehlt); bei mehreren bleibt der Schuetze offen.

    Gibt eine NEUE Liste zurueck — das Original bleibt unangetastet, damit die
    Highlights die unaufgefuellte Timeline nutzen (der Anker-Modus ordnet Tore
    ueber Tafel-Reihenfolge + Minute zu; ein minutenloser Platzhalter wuerde das
    stoeren). Kein/kleinerer Endstand -> Timeline unveraendert.

    @param {object[]} timeline - App-Timeline der erkannten Tore
    @param {object|null} final_score - {home, away} aus der Kopfzeile, oder None
    @param {object[]} players - Aufstellung (fuer die 1v1-Schuetzen-Zuordnung)
    @returns {object[]} ggf. aufgefuellte Kopie der Timeline
    @example
    // zwei erkannte Heimtore, Kopfzeile sagt 3:0 -> drei Eintraege, letzter {home:3, away:0}
    reconcile_to_final_score(two_home_goals, {"home": 3, "away": 0}, players)
    """
    if not final_score:
        return timeline
    identified = {
        "home": sum(1 for e in timeline if e.get("team") == "home"),
        "away": sum(1 for e in timeline if e.get("team") == "away"),
    }
    missing = {
        t: max(0, int(final_score.get(t, 0)) - identified[t]) for t in ("home", "away")
    }
    if not (missing["home"] or missing["away"]):
        return timeline  # Vision deckt den Endstand ab (oder fand sogar mehr)

    side_players = {"home": [], "away": []}
    for p in players or []:
        side_players.setdefault(p.get("team"), []).append(p)

    padded = [dict(e) for e in timeline]
    h = padded[-1]["home"] if padded else 0
    a = padded[-1]["away"] if padded else 0
    for team in ("home", "away"):
        for _ in range(missing[team]):
            if team == "home":
                h += 1
            else:
                a += 1
            entry = {
                "home": h, "away": a, "team": team, "minute": None,
                "period": "regular", "stoppage": 0, "event_type": "goal",
            }
            side = side_players.get(team) or []
            if len(side) == 1 and side[0].get("player_id"):
                entry["scored_by"] = side[0]["player_id"]
                entry["scored_by_name"] = side[0].get("username")
            padded.append(entry)
    return padded


def enrich_tap_timeline(timeline, players):
    """Tap-Timelines tragen in scored_by/assist_by SPIELER-IDs. Fuer das
    Highlight-Banner werden die Anzeigenamen ergaenzt (scored_by_name/
    assist_by_name) — die DB bleibt unberuehrt, nur app_<base>.json."""
    by_id = {p.get("player_id"): p.get("username") for p in players or []}
    enriched = []
    for e in timeline:
        entry = dict(e)
        for key in ("scored_by", "assist_by"):
            name = by_id.get(entry.get(key))
            if name:
                entry[f"{key}_name"] = name
        enriched.append(entry)
    return enriched


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


def finalize_if_pending(timeline, data, post):
    """Pending-Spiel mit der Timeline finalisieren, auf den Kopfzeilen-Endstand
    abgeglichen (Weg B). Die Highlights nutzen die unaufgefuellte `timeline`; nur
    die Finalize-Kopie wird ggf. aufgefuellt. No-op, wenn nicht pending.

    @param {object[]} timeline - erkannte Tore (App-Format), unaufgefuellt
    @param {object|null} data - /recording/timeline-Antwort (pending, players, ...)
    @param {object|null} post - Nachspiel-Extraktion (liefert final_score)
    @returns {void}
    @example
    finalize_if_pending(hud_timeline, data, post)  # finalisiert 3:0, auch wenn nur 2 erkannt
    """
    if not (data and data.get("pending")):
        if data:
            print("[pipeline] Spiel ist nicht pending — Timeline nur fuer Highlights, kein Finalize.")
        return
    players = (data or {}).get("players")
    final_score = post.get("final_score") if post else None
    finalize_timeline = reconcile_to_final_score(timeline, final_score, players)
    if len(finalize_timeline) != len(timeline) and final_score:
        print(f"[pipeline] Endstand laut Kopfzeile {final_score['home']}:{final_score['away']} > "
              f"{len(timeline)} erkannte Tore — Finalize-Timeline auf {len(finalize_timeline)} "
              f"aufgefuellt (Score autoritativ, Highlights best-effort).")
    finalized = api_post("/recording/finalize", {"game_id": GAME_ID, "score_timeline": finalize_timeline})
    if finalized:
        print(f"[pipeline] Spiel finalisiert: {finalized.get('score_home')}:{finalized.get('score_away')}")


def detect_hud_goals(base, app_path, players):
    """1v1 HUD-native Tor-Erkennung (Option B): Frames ziehen, Skin erkennen,
    build_hud_timeline -> App-Timeline nach app_path. Scroll-unabhaengig — jedes
    Tor wird ueber die Live-Anstosstafeln erfasst, nicht ueber die Events-Seite.
    Gibt (timeline, skin) zurueck oder ([], None) bei Fehlschlag (dann greift der
    Events-/Klassik-Fallback). Der Skin wird an make_highlights durchgereicht.

    @param {string} base - Datei-Basisname (z.B. game_<recId>)
    @param {string} app_path - Ziel der App-Timeline (app_<base>.json)
    @param {object[]} players - Aufstellung (1v1: je ein Spieler pro Seite)
    @returns {[object[], string|null]} (Timeline, erkannter Skin)
    @example
    timeline, skin = detect_hud_goals("game_abc", "app_game_abc.json", players)
    """
    frames_dir = f"frames_{base}"
    try:
        extract_frames(VIDEO, frames_dir)
        skin, info = detect_skin_from_dir(frames_dir)
        skin = skin or "bundesliga"
        print(f"[pipeline] 1v1 HUD-Modus — Skin {skin} "
              f"(Konfidenz {info.get('confidence') if info else '?'})")
        env = {**os.environ, "FRAMES_DIR": frames_dir, "FPS": str(FPS),
               "HUD_PROFILE": skin, "PLAYERS": json.dumps(players or []), "OUT": app_path}
        rc = subprocess.run([sys.executable, script("build_hud_timeline.py")], env=env)
        if rc.returncode == 0 and os.path.exists(app_path):
            return json.load(open(app_path)), skin
        print(f"[pipeline] build_hud_timeline rc={rc.returncode} — Fallback.")
    except Exception as e:
        print(f"[pipeline] HUD-Erkennung fehlgeschlagen ({e}) — Fallback.")
    return [], None


def _rm(path):
    """Datei ODER Verzeichnis entfernen (idempotent). True bei tatsaechlichem Loeschen."""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
        else:
            return False
        return True
    except OSError as e:
        print(f"[cleanup] {path} nicht entfernbar: {e}")
        return False


def cleanup_run_artifacts(base):
    """Nach ERFOLGREICHEM Lauf: Scratch (Frames/Stats/Zwischen-JSONs) + lokales
    Reel + Clips dieses Spiels loeschen — alles regenerierbar bzw. schon im
    Bucket. Die Aufnahme (.mov) bleibt; ihre Retention laeuft separat. CLEANUP=0
    schaltet ab.

    @param {string} base - Datei-Basisname (z.B. game_<recId>)
    @returns {void}
    @example
    cleanup_run_artifacts("game_abc")  # entfernt frames_game_abc/, das Reel etc.
    """
    if not CLEANUP:
        return
    targets = [
        f"frames_{base}", f"stats_{base}", f"highlights_{base}",
        f"events_{base}.json", f"goals_{base}.json", f"app_{base}.json",
        f"score_timeline_{base}.json", f"{base}_highlights.mp4",
    ]
    removed = sum(1 for t in targets if _rm(t))
    print(f"[cleanup] {removed} Artefakt(e) von {base} entfernt (Aufnahme bleibt).")


def housekeeping():
    """Vor dem Lauf aufraeumen: (1) verwaiste Scratch-Reste frueherer (oft
    fehlgeschlagener) Laeufe — NUR `game_*` und aelter als ORPHAN_SCRATCH_HOURS,
    damit weder Sample-Daten noch ein parallel laufender Lauf getroffen werden;
    (2) Aufnahmen aelter als RECORDING_RETENTION_DAYS (opt-in, 0 = aus). Reels/
    Clips werden NICHT verwaist-geloescht — ein nicht hochgeladenes Reel muss fuer
    einen manuellen Retry erhalten bleiben.

    @returns {void}
    @example
    housekeeping()  # am Anfang von main()
    """
    if not CLEANUP:
        return
    current = os.path.splitext(os.path.basename(VIDEO))[0] if VIDEO else ""
    cutoff = time.time() - ORPHAN_SCRATCH_HOURS * 3600
    patterns = ["frames_game_*", "stats_game_*", "events_game_*.json",
                "goals_game_*.json", "app_game_*.json", "score_timeline_game_*.json"]
    swept = 0
    for pat in patterns:
        for path in glob.glob(pat):
            if current and current in path:
                continue  # den aktuellen Lauf nie anfassen
            try:
                if os.path.getmtime(path) < cutoff and _rm(path):
                    swept += 1
            except OSError:
                pass
    if swept:
        print(f"[cleanup] {swept} verwaiste Scratch-Rest(e) frueherer Laeufe entfernt.")
    if RECORDING_RETENTION_DAYS > 0 and VIDEO:
        rec_dir = os.path.dirname(VIDEO) or "."
        rec_cutoff = time.time() - RECORDING_RETENTION_DAYS * 86400
        pruned = 0
        for mov in glob.glob(os.path.join(rec_dir, "*.mov")):
            try:
                if os.path.getmtime(mov) < rec_cutoff and _rm(mov):
                    pruned += 1
                    print(f"[cleanup] Alte Aufnahme entfernt (>{RECORDING_RETENTION_DAYS}d): {mov}")
            except OSError:
                pass
        if pruned:
            print(f"[cleanup] {pruned} Aufnahme(n) aelter als {RECORDING_RETENTION_DAYS} Tage entfernt.")


def main():
    if not GAME_ID or not VIDEO:
        print("[pipeline] PIPE_GAME_ID / PIPE_VIDEO fehlen — Abbruch.")
        return
    penalty_fields = {}  # nach run_postmatch ggf. mit dem Elfmeter-Ergebnis befuellt
    if not os.path.exists(VIDEO):
        print(f"[pipeline] Aufnahme nicht gefunden: {VIDEO}")
        patch_status("failed", **penalty_fields)
        return
    # Klassische Fehlkonfiguration abfangen: GCS_BUCKET muss der Firebase-
    # Bucket sein (FIREBASE_STORAGE_BUCKET der API), NICHT der Ordnername —
    # sonst laufen alle Uploads gegen einen fremden/nicht existenten Bucket.
    if GCS_BUCKET and GCS_BUCKET == HIGHLIGHTS_PREFIX:
        print(f"[pipeline] WARNUNG: GCS_BUCKET == HIGHLIGHTS_PREFIX "
              f"('{GCS_BUCKET}') — das ist sehr wahrscheinlich vertauscht. "
              f"GCS_BUCKET = Firebase-Bucket (z.B. <projekt>.firebasestorage.app), "
              f"HIGHLIGHTS_PREFIX = Ordner darin.")

    base = os.path.splitext(os.path.basename(VIDEO))[0]
    reel = f"{base}_highlights.mp4"   # make_highlights legt das Reel im CWD ab

    # Vor dem Lauf aufraeumen (verwaiste Scratch-Reste + Aufnahmen-Retention).
    housekeeping()

    # 0) Spieldaten holen: Taps, Aufstellung, pending-Status.
    data = fetch_timeline()
    tap_goals = [e for e in (data.get("score_timeline") if data else []) or []
                 if e.get("event_type", "goal") == "goal"]
    # 1) Nachspiel-Extraktion: Stats-Screens immer; Events-Torliste nur ohne Taps;
    #    zusaetzlich das Elfmeterschiessen-Ergebnis vom Post-Match-Screen.
    post = run_postmatch(base, skip_events=bool(tap_goals))
    if post:
        submit_stats(post.get("stats_files"))

    # Elfmeterschiessen-Ergebnis: FC26 zeigt nach JEDEM Spiel "ELF X-Y" / "(X:YE)"
    # (extract_postmatch liest es per Vision — robust, skin-/teamunabhaengig).
    # -> result_type=penalty + ergebnis-only penalty_shootout (kein shots[],
    # source "auto"), per Status-PATCH gemeldet. Den Clip liefert detect_shootout.
    pen = (post or {}).get("penalty_shootout")
    if pen and pen.get("winner") in ("home", "away"):
        reg = (post or {}).get("final_score") or {}
        penalty_fields = {
            "result_type": "penalty",
            "penalty_shootout": {
                "score_before": {"home": reg.get("home", 0), "away": reg.get("away", 0)},
                "final_score": {"home": pen["home"], "away": pen["away"]},
                "winner_side": pen["winner"],
                "source": "auto",
            },
        }
        print(f"[pipeline] Elfmeterschiessen {pen['home']}:{pen['away']} "
              f"(Sieger {pen['winner']}) -> result_type=penalty.")

    # Spieler + 1v1-Erkennung (steuert die Torquelle).
    players = (data or {}).get("players") or []
    is_1v1 = (sum(1 for p in players if p.get("team") == "home") == 1
              and sum(1 for p in players if p.get("team") == "away") == 1)

    # Torquelle nach Prioritaet: Taps (autoritativ) > 1v1 HUD-nativ (Option B,
    # scroll-unabhaengig, jedes Tor ueber die Live-Anstosstafeln) > Events-Screen-
    # Vision (2v2-Fallback) > klassische Ziffern-Erkennung. hud_profile wird
    # gesetzt, wenn der HUD-Modus lief -> make_highlights bekommt die schon
    # gezogenen Frames (REUSE_FRAMES) und den Skin (--hud) durchgereicht.
    app_path = f"app_{base}.json"
    hud_profile = None
    if tap_goals:
        enriched = enrich_tap_timeline(data["score_timeline"], players)
        with open(app_path, "w") as f:
            json.dump(enriched, f)
        print(f"[pipeline] App-Timeline (Taps): {len(tap_goals)} Tore -> {app_path}")
    elif is_1v1:
        timeline, hud_profile = detect_hud_goals(base, app_path, players)
        if timeline:
            print(f"[pipeline] HUD-native Timeline (1v1, Option B): {len(timeline)} Tore -> {app_path}")
            finalize_if_pending(timeline, data, post)
        elif post and post.get("goals"):
            timeline = build_app_timeline(post["goals"], players)
            with open(app_path, "w") as f:
                json.dump(timeline, f)
            print(f"[pipeline] HUD-Erkennung leer — Fallback Events-Screen: {len(timeline)} Tore -> {app_path}")
            finalize_if_pending(timeline, data, post)
        else:
            print("[pipeline] Weder HUD noch Events-Screen lieferten Tore — klassische Erkennung.")
    elif post and post.get("goals"):
        timeline = build_app_timeline(post["goals"], players)
        with open(app_path, "w") as f:
            json.dump(timeline, f)   # unaufgefuellt -> Highlights/Anker-Modus
        print(f"[pipeline] Vision-Timeline (Events-Screen, 2v2): {len(timeline)} Tore -> {app_path}")
        finalize_if_pending(timeline, data, post)
    else:
        print("[pipeline] Keine Torliste (weder Taps, HUD noch Events-Screen) — "
              "klassische Ziffern-Erkennung.")

    # 2) Reel erzeugen. Lief der 1v1-HUD-Modus, reichen wir die schon gezogenen
    #    Frames (REUSE_FRAMES) und den erkannten Skin (--hud) durch — sonst
    #    extrahiert/erkennt make_highlights wie gehabt selbst.
    print(f"[pipeline] make_highlights für {VIDEO} ...")
    hl_cmd = [sys.executable, script("make_highlights.py"), VIDEO]
    hl_env = {**os.environ}
    if hud_profile:
        hl_cmd += ["--hud", hud_profile]
        hl_env["REUSE_FRAMES"] = "1"
    result = subprocess.run(hl_cmd, env=hl_env)
    if result.returncode != 0 or not os.path.exists(reel):
        # Häufigster gutartiger Fall: keine Tore erkannt -> kein Reel.
        print(f"[pipeline] Kein Reel erzeugt (rc={result.returncode}, reel da: {os.path.exists(reel)}).")
        patch_status("failed", **penalty_fields)
        return

    # 2) Reel öffentlich in den Bucket laden (Pendant zu file.save()+makePublic() der API).
    if not GCS_BUCKET:
        print("[pipeline] GCS_BUCKET nicht gesetzt — Upload übersprungen, Reel bleibt lokal.")
        patch_status("failed", **penalty_fields)
        return
    obj = f"{HIGHLIGHTS_PREFIX}/{GAME_ID}.mp4"
    dest = f"gs://{GCS_BUCKET}/{obj}"
    print(f"[pipeline] Upload {reel} -> {dest}")
    up = subprocess.run(
        ["gsutil", "-h", "Content-Type:video/mp4", "cp", "-a", "public-read", reel, dest])
    if up.returncode != 0:
        print(f"[pipeline] Upload fehlgeschlagen (rc={up.returncode}).")
        patch_status("failed", **penalty_fields)
        return

    # 3) Verknüpfen — die App rendert genau diese URL.
    url = f"https://storage.googleapis.com/{GCS_BUCKET}/{obj}"
    patch_status("ready", highlight_url=url, **penalty_fields)
    print(f"[pipeline] Fertig: {url}")

    # Erfolgreich hochgeladen -> Scratch + lokales Reel/Clips dieses Spiels weg.
    cleanup_run_artifacts(base)


if __name__ == "__main__":
    main()
