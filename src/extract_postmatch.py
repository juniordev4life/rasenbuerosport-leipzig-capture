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

Erkennung: jedes der sechs Tab-Labels wird einzeln per Template gesucht
(templates/menu/labels/<tab>.png), jeweils in einem kleinen Fenster um seine
Soll-Position. Einzeln, weil sich die Abstände zwischen den Labels von
FC-Version zu FC-Version um ein paar Pixel verschieben (FC26 -> FC27: 1-3 px);
ein Template der ganzen Zeile bricht daran. Menü offen = mind. 5 von 6 Labels
>= 0.7 (das aktive, fett gesetzte Label korreliert schwächer; Spielszenen
erreichen höchstens 0.45). Aktiver Tab = hellste Textpixel (98. Perzentil),
nicht der Flächen-Mittelwert: die Zeile ist halbtransparent, und ein heller
Hintergrund liess sonst ein inaktives Label gewinnen.

Env:
  VIDEO            Aufnahme (.mov) — ODER FRAMES_DIR mit fertigen Frames
  FRAMES_DIR       vorhandene Frames (z.B. von make_highlights) statt VIDEO
  TAIL_SECONDS     wie weit vor dem Ende gescannt wird (Default 420)
  FPS              Frame-Rate der Quelle (Default 2)
  STATS_DIR        Zielordner für die Stats-PNGs (Default stats_postmatch)
  EVENTS_OUT       Ziel-JSON der Torliste (Default events_postmatch.json)
  SKIP_EVENTS=1    nur Stats-Frames, kein Vision-Call (z.B. wenn Taps existieren)
  ANTHROPIC_API_KEY  für den Vision-Call (Pflicht, außer SKIP_EVENTS)
  EVENTS_MODEL     Default claude-sonnet-4-6 (validiert: bl-11-10 21/21 Tore)
  MAX_EVENT_FRAMES Obergrenze Bilder an Claude (Default 12)
"""
import atexit
import base64
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np

from paths import TEMPLATES

VIDEO = os.environ.get("VIDEO")
FRAMES_DIR = os.environ.get("FRAMES_DIR")
TAIL_SECONDS = int(os.environ.get("TAIL_SECONDS", "420"))
FPS = float(os.environ.get("FPS", "2"))
STATS_DIR = os.environ.get("STATS_DIR", "stats_postmatch")
EVENTS_OUT = os.environ.get("EVENTS_OUT", "events_postmatch.json")
SKIP_EVENTS = os.environ.get("SKIP_EVENTS") == "1"
EVENTS_MODEL = os.environ.get("EVENTS_MODEL", "claude-sonnet-4-6")
MAX_EVENT_FRAMES = int(os.environ.get("MAX_EVENT_FRAMES", "12"))

LABEL_DIR = os.path.join(TEMPLATES, "menu", "labels")
LABELS = {                                    # Soll-Position (x, y) je Label-Template, 1920x1080
    "overview": (556, 183),                   # Übersicht
    "ballbesitz": (699, 188),
    "schuss": (840, 188),                     # Schussverhalten
    "passes": (1052, 188),                    # Pässe
    "defense": (1152, 188),                   # Abwehr
    "events": (1276, 188),
}
LABEL_SLACK = (10, 6)                         # Suchspielraum je Label (x, y) in px
LABEL_THRESHOLD = 0.7
MIN_LABELS = 5
ACTIVE_RATIO = 1.3                            # Textpixel aktives Label vs. Median der übrigen
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

Return TWO things:

1. final_score: an object {home, away} read from the HEADER "H : A" at the
   very top (home = the LEFT/home team's number, away = the RIGHT/away
   team's number). The header is ALWAYS fully visible and does NOT scroll,
   so read it directly — it is the authoritative final result even when the
   list below is mid-scroll or a goal is not visible in any screenshot.

2. goals: every goal of the match, chronologically, each with:
   - team: "home" (left column) or "away" (right column)
   - minute: the number before the apostrophe, as integer
   - scorer: the in-game player name as printed (e.g. "H. Kane")

If a goal seems missing from the scrolled list, still return only the goals
that ARE visible — but always return the true final_score from the header
(it may legitimately exceed the number of goals you can see in the list)."""

EVENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "final_score": {
            "type": "object",
            "properties": {
                "home": {"type": "integer"},
                "away": {"type": "integer"},
            },
            "required": ["home", "away"],
            "additionalProperties": False,
        },
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
    "required": ["final_score", "goals"],
    "additionalProperties": False,
}


# Aufraeumen der Temp-Verzeichnisse aus tail_frames(). Jeder Lauf zieht ~2 GB
# Frames vom Video-Ende; ohne Loeschen summiert sich das (auf der Buero-Box waren
# es 75 Verzeichnisse / 134 GB in /tmp, bis die Platte volllief und die gesamte
# Pipeline kippte). CLEANUP=0 behaelt sie zum Debuggen — gleiche Konvention wie
# in process_highlights.py.
CLEANUP = os.environ.get("CLEANUP", "1") != "0"
_TMP_DIRS = []


def _rm_tmp_dirs():
    """Loescht die von tail_frames() angelegten Temp-Verzeichnisse.

    Laeuft per atexit, damit auch ein Abbruch mitten im Lauf (Exception,
    SystemExit) nichts liegen laesst. Die Frames sind aus der Aufnahme jederzeit
    reproduzierbar; die Stats-Frames liegen bereits in STATS_DIR.

    @returns {void}
    @example
    _rm_tmp_dirs()  # per atexit registriert, kein manueller Aufruf noetig
    """
    if not CLEANUP:
        if _TMP_DIRS:
            print(f"[postmatch] CLEANUP=0 — Temp behalten: {', '.join(_TMP_DIRS)}")
        return
    for d in _TMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)
    _TMP_DIRS.clear()


atexit.register(_rm_tmp_dirs)


def tail_frames():
    """Liefert die zu scannenden Frame-Pfade (Video-Ende)."""
    count = int(TAIL_SECONDS * FPS)
    if FRAMES_DIR:
        frames = sorted(glob.glob(os.path.join(FRAMES_DIR, "*.png")))
        return frames[-count:]
    if not VIDEO or not os.path.exists(VIDEO):
        raise SystemExit("VIDEO oder FRAMES_DIR muss gesetzt sein.")
    tmp = tempfile.mkdtemp(prefix="postmatch_")
    _TMP_DIRS.append(tmp)   # -> _rm_tmp_dirs() am Prozessende
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-sseof", f"-{TAIL_SECONDS}",
         "-i", VIDEO, "-vf", f"fps={FPS}", os.path.join(tmp, "tail_%05d.png")],
        check=True)
    return sorted(glob.glob(os.path.join(tmp, "*.png")))


def load_label_refs():
    """Lädt die sechs Label-Templates (Graustufen); bricht ab, wenn eins fehlt.

    @returns {dict} Tab-Key -> Template
    @example
    refs = load_label_refs()  # {"overview": array(...), "ballbesitz": ..., ...}
    """
    refs = {}
    for tab in LABELS:
        path = os.path.join(LABEL_DIR, f"{tab}.png")
        ref = cv2.imread(path, 0)
        if ref is None:
            raise SystemExit(f"Label-Template fehlt: {path}")
        refs[tab] = ref
    return refs


def classify(img, refs):
    """(praesent, aktiver_tab) für einen Frame.

    @param {ndarray} img - BGR-Frame in 1920x1080
    @param {dict} refs - Label-Templates aus load_label_refs()
    @returns {tuple} (True, tab) bei offenem Menü, (True, None) im Übergang
        ohne klar aktiven Tab, (False, None) ohne Menü
    @example
    classify(cv2.imread("tail_00823.png"), refs)  # (True, "passes")
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dx, dy = LABEL_SLACK
    found, text = 0, {}
    for tab, (x, y) in LABELS.items():
        h, w = refs[tab].shape
        win = gray[y - dy:y + h + dy, x - dx:x + w + dx]
        res = cv2.matchTemplate(win, refs[tab], cv2.TM_CCOEFF_NORMED)
        _, corr, _, (mx, my) = cv2.minMaxLoc(res)
        if corr >= LABEL_THRESHOLD:
            found += 1
        text[tab] = float(np.percentile(win[my:my + h, mx:mx + w], 98))
    if found < MIN_LABELS:
        return False, None
    active = max(text, key=text.get)
    others = [v for k, v in text.items() if k != active]
    if text[active] < ACTIVE_RATIO * max(1.0, float(np.median(others))):
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
    """Schickt die Events-Frames an Claude Vision, gibt das geparste Ergebnis
    zurueck: {final_score: {home, away}, goals: [{team, minute, scorer}]}.
    final_score kommt aus der (immer sichtbaren) Kopfzeile und ist
    massgeblich — die goals-Liste kann durchs Scrollen ein Tor verpassen."""
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
    return json.loads(text)


PENALTY_PROMPT = """\
Diese Bilder sind Post-Match-Screens eines EA Sports FC (FC26) Spiels (deutsche UI).
FC26 zeigt nach JEDEM Spiel den Endstand. Wenn die Partie im ELFMETERSCHIESSEN
entschieden wurde, ist das markiert — entweder:
- in der oberen Ergebnis-Leiste als "ELF | X - Y"  (X = Heim/links, Y = Gast/rechts), ODER
- als Zusatz unter dem Endstand als "(X:YE)"  — das "E" steht fuer Elfmeterschiessen.
Gib zurueck:
- shootout: true NUR wenn so ein Marker (ELF bzw. ...E) KLAR lesbar ist, sonst false.
- home, away: die verwandelten Elfmeter von Heim (X) und Gast (Y), wenn shootout true.
Erfinde keine Zahlen. Ohne klar lesbaren Marker -> shootout=false, home/away null."""

PENALTY_SCHEMA = {
    "type": "object",
    "properties": {
        "shootout": {"type": "boolean"},
        "home": {"type": ["integer", "null"]},
        "away": {"type": ["integer", "null"]},
    },
    "required": ["shootout"],
    "additionalProperties": False,
}


def read_penalty_shootout(paths):
    """Sucht in den Ergebnis-/Menue-Screens am Spielende den Elfmeterschiessen-
    Marker ("ELF X - Y" bzw. Score-Zusatz "(X:YE)") und liest den Endstand. Per
    Claude Vision — robust und skin-/teamunabhaengig (anders als das Live-Banner-
    Lesen, das pro Skin kalibriert werden muss).

    @param {string[]} paths - Frame-Pfade vom Spielende (Ergebnis-/Menue-Screens)
    @returns {object|null} {home, away, winner} oder None (kein Schiessen erkannt)
    @example
    read_penalty_shootout(end_frames)  # -> {"home": 6, "away": 7, "winner": "away"}
    """
    if not paths:
        return None
    import anthropic  # lazy: ohne Paket/Key importierbar

    content = []
    for p in paths:
        img = cv2.imread(p)
        if img is None:
            continue
        scale = 1280 / img.shape[1]
        small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(buf.tobytes()).decode()}})
    if not content:
        return None
    content.append({"type": "text", "text": PENALTY_PROMPT})
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=EVENTS_MODEL, max_tokens=1000, thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": PENALTY_SCHEMA}},
            messages=[{"role": "user", "content": content}])
        text = next(b.text for b in response.content if b.type == "text")
        result = json.loads(text)
    except Exception as e:
        print(f"[postmatch] Elfmeter-Lesung fehlgeschlagen: {e}")
        return None
    if not result.get("shootout") or result.get("home") is None or result.get("away") is None:
        return None
    home, away = int(result["home"]), int(result["away"])
    return {"home": home, "away": away,
            "winner": "home" if home > away else ("away" if away > home else "tie")}


def main():
    refs = load_label_refs()

    frames = tail_frames()
    print(f"[postmatch] Scanne {len(frames)} Frames (letzte {TAIL_SECONDS}s) ...")

    by_tab = {k: [] for k in LABELS}
    for p in frames:
        img = cv2.imread(p)
        if img is None:
            continue
        present, tab = classify(img, refs)
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

    # 2) Events-Torliste + massgeblicher Endstand (Kopfzeile)
    goals = []
    final_score = None
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
            result = ask_claude(distinct)
            goals = result.get("goals", [])
            final_score = result.get("final_score")
            fs = f"{final_score['home']}:{final_score['away']}" if final_score else "?"
            print(f"[postmatch] {len(goals)} Tore extrahiert, Endstand laut Kopfzeile {fs}.")
        except Exception as e:
            print(f"[postmatch] Vision-Extraktion fehlgeschlagen: {e}")

    # 3) Elfmeterschiessen-Ergebnis vom Endstand-/Menue-Screen lesen. FC26 zeigt
    # den Marker "ELF X-Y" / "(X:YE)" nach JEDEM Spiel — skin-/teamunabhaengig.
    # Ein paar Frames vom Spielende reichen; Claude Vision findet den Marker dort.
    penalty_shootout = None
    if not SKIP_EVENTS and os.environ.get("ANTHROPIC_API_KEY"):
        end = frames[-int(30 * FPS):]
        step = max(1, len(end) // 4)
        result_frames = end[::step][:4]
        penalty_shootout = read_penalty_shootout(result_frames)
        if penalty_shootout:
            print(f"[postmatch] Elfmeterschiessen erkannt: {penalty_shootout['home']}:"
                  f"{penalty_shootout['away']} (Sieger {penalty_shootout['winner']}).")
        else:
            print("[postmatch] kein Elfmeterschiessen-Marker im Abspann.")

    with open(EVENTS_OUT, "w") as f:
        json.dump({"goals": goals, "final_score": final_score,
                   "stats_files": stats_files, "penalty_shootout": penalty_shootout}, f, indent=2)
    print(f"[postmatch] Ergebnis -> {EVENTS_OUT}")


if __name__ == "__main__":
    main()
