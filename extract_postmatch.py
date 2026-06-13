"""Nachspiel-Extraktion: Stats-Menü-Screens aus dem Aufnahme-Ende ziehen.

Nach dem Abpfiff blättern die Spieler durch das FC-Statistik-Menü (Übersicht /
Pässe / Abwehr / Events) — wie früher fürs Fotografieren, nur ohne Fotos. Das
Menü ist skin- und team-unabhängig (validiert an Bundesliga- und Cross-
Aufnahmen). Dieses Skript scannt das VIDEO-ENDE und liefert zwei Dinge:

  1) STATS-FRAMES: je Tab (Übersicht/Pässe/Abwehr) der schärfste Frame als
     PNG nach STATS_DIR — Futter für die bestehende Claude-Vision-Auswertung
     der API (POST /recording/stats), ersetzt den Foto-Upload.
  2) EVENTS-TORLISTE: die Events-Tab-Frames (Torschützen + Minuten) werden
     dedupliziert und an Claude Vision gegeben -> {goals: [{team, minute,
     scorer}]} nach EVENTS_OUT. Ersetzt die App-Taps als Torquelle
     (Zero-Tracking; Zuordnung zu Office-Spielern macht process_highlights).

Erkennung: Template-Match der Tab-Zeile (templates/menu/tab_strip.png,
korr >= 0.6 vs <= 0.3 bei Nicht-Menü-Frames) + hellstes Label = aktiver Tab
(mind. 1.15x so hell wie der Schnitt der übrigen).

Env:
  VIDEO            Aufnahme (.mov) — ODER FRAMES_DIR mit fertigen Frames
  FRAMES_DIR       vorhandene Frames (z.B. von make_highlights) statt VIDEO
  TAIL_SECONDS     wie weit vor dem Ende gescannt wird (Default 420)
  FPS              Frame-Rate der Quelle (Default 2)
  STATS_DIR        Zielordner für die Stats-PNGs (Default stats_postmatch)
  EVENTS_OUT       Ziel-JSON der Torliste (Default events_postmatch.json)
  SKIP_EVENTS=1    nur Stats-Frames, kein Vision-Call (z.B. wenn Taps existieren)
  ANTHROPIC_API_KEY  für den Vision-Call (Pflicht, außer SKIP_EVENTS)
  EVENTS_MODEL     Default claude-opus-4-8
  MAX_EVENT_FRAMES Obergrenze Bilder an Claude (Default 12)
"""
import base64
import glob
import json
import os
import subprocess
import sys
import tempfile

import cv2

VIDEO = os.environ.get("VIDEO")
FRAMES_DIR = os.environ.get("FRAMES_DIR")
TAIL_SECONDS = int(os.environ.get("TAIL_SECONDS", "420"))
FPS = float(os.environ.get("FPS", "2"))
STATS_DIR = os.environ.get("STATS_DIR", "stats_postmatch")
EVENTS_OUT = os.environ.get("EVENTS_OUT", "events_postmatch.json")
SKIP_EVENTS = os.environ.get("SKIP_EVENTS") == "1"
EVENTS_MODEL = os.environ.get("EVENTS_MODEL", "claude-opus-4-8")
MAX_EVENT_FRAMES = int(os.environ.get("MAX_EVENT_FRAMES", "12"))

STRIP_TEMPLATE = "templates/menu/tab_strip.png"
STRIP_SEARCH = (500, 150, 950, 110)          # x, y, w, h Suchfenster Tab-Zeile
STRIP_THRESHOLD = 0.6
ACTIVE_RATIO = 1.15                           # aktives Label vs. Schnitt der übrigen
LABELS = {                                    # Label-Boxen (1920x1080)
    "overview": (555, 185, 100, 26),          # Übersicht
    "ballbesitz": (705, 185, 100, 26),
    "schuss": (845, 185, 165, 26),
    "passes": (1055, 185, 62, 26),            # Pässe
    "defense": (1160, 185, 68, 26),           # Abwehr
    "events": (1280, 185, 72, 26),
}
STATS_TABS = ("overview", "passes", "defense")
EVENTS_ROI = (480, 260, 970, 740)             # Listen-Bereich fürs Scroll-Dedupe

EVENTS_PROMPT = """\
These screenshots show the EVENTS tab of the post-match statistics menu of an
EA Sports FC match (1920x1080, German UI). Layout:

- The header shows "HOME-TEAM  H : A  AWAY-TEAM" — useful as a checksum.
- The list below is a vertical timeline of match events in chronological
  order (top = earliest). HOME-team events sit in the LEFT column (name left
  of the icon/minute), AWAY-team events in the RIGHT column.
- GOALS carry a small football icon next to the minute (e.g. "H. Kane  (ball) 3'").
- SUBSTITUTIONS show two stacked names with up/down arrows — IGNORE them.
- Cards and other events without the football icon — IGNORE them.
- Screens with "SPIEL-STATISTIKEN WERDEN INITIALISIERT" are loading — skip.
- The screenshots come from SCROLLING through one list, so they OVERLAP:
  the same goal appears on several screenshots. Deduplicate — output every
  goal exactly ONCE.

Return every goal of the match, chronologically, with:
- team: "home" (left column) or "away" (right column)
- minute: the number before the apostrophe, as integer
- scorer: the in-game player name as printed (e.g. "H. Kane")

The final goal count per team must match the header score. If a goal seems
missing from the screenshots, still return only what is visible."""

EVENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "goals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "team": {"type": "string", "enum": ["home", "away"]},
                    "minute": {"type": "integer"},
                    "scorer": {"type": "string"},
                },
                "required": ["team", "minute", "scorer"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["goals"],
    "additionalProperties": False,
}


def tail_frames():
    """Liefert die zu scannenden Frame-Pfade (Video-Ende)."""
    count = int(TAIL_SECONDS * FPS)
    if FRAMES_DIR:
        frames = sorted(glob.glob(os.path.join(FRAMES_DIR, "*.png")))
        return frames[-count:]
    if not VIDEO or not os.path.exists(VIDEO):
        raise SystemExit("VIDEO oder FRAMES_DIR muss gesetzt sein.")
    tmp = tempfile.mkdtemp(prefix="postmatch_")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-sseof", f"-{TAIL_SECONDS}",
         "-i", VIDEO, "-vf", f"fps={FPS}", os.path.join(tmp, "tail_%05d.png")],
        check=True)
    return sorted(glob.glob(os.path.join(tmp, "*.png")))


def classify(img, strip_ref):
    """(praesent, aktiver_tab) für einen Frame."""
    sx, sy, sw, sh = STRIP_SEARCH
    win = cv2.cvtColor(img[sy:sy + sh, sx:sx + sw], cv2.COLOR_BGR2GRAY)
    corr = float(cv2.matchTemplate(win, strip_ref, cv2.TM_CCOEFF_NORMED).max())
    if corr < STRIP_THRESHOLD:
        return False, None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bright = {k: float(gray[y:y + h, x:x + w].mean()) for k, (x, y, w, h) in LABELS.items()}
    active = max(bright, key=bright.get)
    others = [v for k, v in bright.items() if k != active]
    if bright[active] < ACTIVE_RATIO * (sum(others) / len(others)):
        return True, None   # Menü offen, aber kein Tab klar aktiv (Übergang)
    return True, active


def sharpness(img):
    """Schärfemaß (Varianz des Laplace) — wählt den besten Stats-Frame."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def dedupe_events(paths):
    """Distinkte Scroll-Positionen der Events-Liste (ROI-Differenz)."""
    distinct, prev = [], None
    for p in paths:
        img = cv2.imread(p, 0)
        x, y, w, h = EVENTS_ROI
        roi = cv2.resize(img[y:y + h, x:x + w], (200, 160))
        if prev is None or abs(roi.astype(int) - prev.astype(int)).mean() > 6:
            distinct.append(p)
            prev = roi
    return distinct


def ask_claude(paths):
    """Schickt die Events-Frames an Claude Vision, gibt die Torliste zurück."""
    import anthropic  # lazy: Modul bleibt ohne Paket/Key importierbar

    content = []
    for p in paths:
        img = cv2.imread(p)
        scale = 1280 / img.shape[1]
        small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            continue
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(buf.tobytes()).decode(),
            },
        })
    content.append({"type": "text", "text": EVENTS_PROMPT})

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=EVENTS_MODEL,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": EVENTS_SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["goals"]


def main():
    strip_ref = cv2.imread(STRIP_TEMPLATE, 0)
    if strip_ref is None:
        raise SystemExit(f"Tab-Template fehlt: {STRIP_TEMPLATE}")

    frames = tail_frames()
    print(f"[postmatch] Scanne {len(frames)} Frames (letzte {TAIL_SECONDS}s) ...")

    by_tab = {k: [] for k in LABELS}
    for p in frames:
        img = cv2.imread(p)
        if img is None:
            continue
        present, tab = classify(img, strip_ref)
        if present and tab:
            by_tab[tab].append((p, img))

    # 1) Stats-Frames: schärfster Frame je Tab
    os.makedirs(STATS_DIR, exist_ok=True)
    stats_files = {}
    for tab in STATS_TABS:
        if not by_tab[tab]:
            continue
        best_path, best_img = max(by_tab[tab], key=lambda e: sharpness(e[1]))
        out = os.path.join(STATS_DIR, f"{tab}.png")
        cv2.imwrite(out, best_img)
        stats_files[tab] = out
        print(f"[postmatch] Stats-Frame {tab}: {os.path.basename(best_path)} -> {out}")
    if not stats_files:
        print("[postmatch] Keine Stats-Tabs (Übersicht/Pässe/Abwehr) im Abspann gefunden.")

    # 2) Events-Torliste
    goals = []
    event_paths = [p for p, _ in by_tab["events"]]
    if SKIP_EVENTS:
        print("[postmatch] SKIP_EVENTS=1 — Torliste übersprungen.")
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        print("[postmatch] ANTHROPIC_API_KEY fehlt im Env — Events-Torliste "
              "uebersprungen. Key ins Agent-Env legen (gleicher Wert wie in "
              "der API-.env), dann liest Claude Vision den Events-Tab.")
    elif not event_paths:
        print("[postmatch] Kein Events-Tab im Abspann gefunden — keine Torliste.")
    else:
        distinct = dedupe_events(event_paths)
        if len(distinct) > MAX_EVENT_FRAMES:
            step = len(distinct) / MAX_EVENT_FRAMES
            distinct = [distinct[int(i * step)] for i in range(MAX_EVENT_FRAMES)]
        print(f"[postmatch] Events: {len(event_paths)} Frames, {len(distinct)} distinkt -> Claude ({EVENTS_MODEL})")
        try:
            goals = ask_claude(distinct)
            print(f"[postmatch] {len(goals)} Tore extrahiert.")
        except Exception as e:
            print(f"[postmatch] Vision-Extraktion fehlgeschlagen: {e}")

    with open(EVENTS_OUT, "w") as f:
        json.dump({"goals": goals, "stats_files": stats_files}, f, indent=2)
    print(f"[postmatch] Ergebnis -> {EVENTS_OUT}")


if __name__ == "__main__":
    main()
