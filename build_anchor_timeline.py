"""Anker-basierte Tor-Erkennung (PROTOTYP) — Tafel-Präsenz statt Ziffern-Lesen.

Motivation (bl-11-10): Ziffern-Templates decken nur niedrige Stände ab, und ab
zweistelligen Ständen (11 - 10) verschieben sich die Ziffern — Template-Lesen
hat dort eine strukturelle Decke. Dieser Ansatz dreht die Logik um:

  1) WAS gefallen ist, weiß die App-Timeline (Taps bzw. Events-Screen):
     Seite + Minute je Tor — autoritativ, kommt als APP_TIMELINE rein.
  2) WO im Video die Tore liegen, verraten die Anstoß-Tafeln. Die müssen nur
     ERKANNT werden (Präsenz), nicht GELESEN — und das geht selbstkalibrierend:
     Jedes Spiel beginnt 0:0, die existierenden Ziffern-Templates finden die
     Anstoß-Tafel sicher. Von dort croppt sich das Skript seinen Anker selbst
     (linke Team-Box — innerhalb des Spiels konstant, egal wie hoch der Stand
     steigt). Kein neues Template je Spiel/Team nötig.
  3) Zuordnung Tafel -> Tor über die MINUTE in der Tafel-Kopfzeile (OCR der
     Schützenzeile, wie read_minute): Tafeln ohne Minute (Anstoß "LIVE: ...",
     Halbzeit) und Tafeln, deren Minute zu keinem Tor passt (Einwechslungen),
     fallen automatisch raus. Reihenfolge dient als Fallback bei OCR-Lücken.

Ausgabe ist das normale goals_*.json-Schema (cut_highlights-kompatibel).
goalMoment bleibt None: die HUD-Referenz ist team-spezifisch (BAY/SVW) und
matcht andere Paarungen nicht — bekannter Folgeschritt.
Elfmeterschießen behandelt dieser Prototyp NICHT.

Aufruf (Frames müssen extrahiert sein, FPS passend zur Extraktion):
    FRAMES_DIR=frames_bl-11-10 FPS=2 APP_TIMELINE=app_bl-11-10.json \
    GOALS_OUT=goals_anchor_bl-11-10.json venv/bin/python build_anchor_timeline.py
"""
import json
import os
import re

import cv2
import pytesseract

from hud_profiles import HUD_PROFILES

FRAMES_DIR = os.environ.get("FRAMES_DIR", "frames")
FPS = float(os.environ.get("FPS", "2"))
PROFILE_NAME = os.environ.get("HUD_PROFILE", "bundesliga")
APP_TIMELINE = os.environ.get("APP_TIMELINE")
GOALS_OUT = os.environ.get("GOALS_OUT", "goals_anchor.json")
BOARDS_OUT = os.environ.get("BOARDS_OUT", "")          # optional: Debug-Liste aller Tafeln
MINUTE_TOLERANCE = int(os.environ.get("MINUTE_TOLERANCE", "1"))
BOARD_THRESHOLD = float(os.environ.get("BOARD_THRESHOLD", "0.7"))
MIN_STABLE = int(os.environ.get("MIN_STABLE", "2"))
KICKOFF_SCAN_SECONDS = int(os.environ.get("KICKOFF_SCAN_SECONDS", "240"))

# Anker-Kalibrierung je Skin: Region der linken Team-Box (wird aus der
# 0:0-Anstoßtafel gecroppt) + Suchfenster mit Lage-Toleranz + Kopfzeilen-Strip
# fuer die Minuten-OCR. Bei Uebernahme in den Normalbetrieb -> hud_profiles.
BOARD_CALIB = {
    "bundesliga": {
        "anchor_region": (560, 920, 320, 50),
        "search_region": (520, 890, 420, 115),
        "header_strip": (600, 880, 740, 38),
    },
}

if PROFILE_NAME not in HUD_PROFILES:
    raise SystemExit(f"Unbekanntes HUD-Profil '{PROFILE_NAME}'. Bekannt: {list(HUD_PROFILES)}")
if PROFILE_NAME not in BOARD_CALIB:
    raise SystemExit(f"Kein Board-Anker fuer '{PROFILE_NAME}' kalibriert. Bekannt: {list(BOARD_CALIB)}")
if not APP_TIMELINE or not os.path.exists(APP_TIMELINE):
    raise SystemExit("APP_TIMELINE fehlt — die autoritative Torliste (App-Format) ist Pflicht.")

PROFILE = HUD_PROFILES[PROFILE_NAME]
CALIB = BOARD_CALIB[PROFILE_NAME]

TPL_SIZE = (50, 70)


def _norm_glyph(im):
    """Wie build_score_timeline: Einheitsgroesse + Kontrast-Normalisierung."""
    return cv2.normalize(cv2.resize(im, TPL_SIZE), None, 0, 255, cv2.NORM_MINMAX)


def _load_templates(tpl_dir):
    home, away = {}, {}
    for fn in os.listdir(tpl_dir):
        if not (fn.startswith("home_") or fn.startswith("away_")):
            continue
        digit = int(fn.split("_")[1].split(".")[0])
        glyph = _norm_glyph(cv2.imread(os.path.join(tpl_dir, fn), 0))
        (home if fn.startswith("home") else away)[digit] = glyph
    return home, away


def _match_digit(crop_gray, templates, threshold):
    best, score = None, -2.0
    for digit, tpl in templates.items():
        s = cv2.matchTemplate(_norm_glyph(crop_gray), tpl, cv2.TM_CCOEFF_NORMED)[0][0]
        if s > score:
            score, best = s, digit
    return best if score >= threshold else None


def read_score_00(img):
    """True, wenn der Stand sicher als 0:0 gelesen wird (Anstoßtafel)."""
    sc = PROFILE["score"]
    home_t, away_t = _TEMPLATES
    hx, hy, hw, hh = sc["home_region"]
    ax, ay, aw, ah = sc["away_region"]
    h = _match_digit(cv2.cvtColor(img[hy:hy + hh, hx:hx + hw], cv2.COLOR_BGR2GRAY), home_t, sc["threshold"])
    a = _match_digit(cv2.cvtColor(img[ay:ay + ah, ax:ax + aw], cv2.COLOR_BGR2GRAY), away_t, sc["threshold"])
    return h == 0 and a == 0


def board_presence(img, anchor):
    """Korrelation des Spiel-Ankers im Suchfenster (Lage-tolerant)."""
    sx, sy, sw, sh = CALIB["search_region"]
    win = cv2.cvtColor(img[sy:sy + sh, sx:sx + sw], cv2.COLOR_BGR2GRAY)
    return float(cv2.matchTemplate(win, anchor, cv2.TM_CCOEFF_NORMED).max())


def read_header_minute(img):
    """Letzte Zahl der Tafel-Kopfzeile (Schuetzenzeile 'NAME MM''). None, wenn
    keine Zahl lesbar — z.B. Anstoß-/Halbzeit-Tafel ('LIVE: <Stadion>')."""
    x, y, w, h = CALIB["header_strip"]
    gray = cv2.cvtColor(img[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    text = pytesseract.image_to_string(gray, config="--psm 7").strip()
    nums = re.findall(r"\d+", text)
    if not nums:
        return None
    value = int(nums[-1])
    return value if 1 <= value <= 120 else None


# --- Torliste laden ---------------------------------------------------------
raw = json.load(open(APP_TIMELINE))
goal_list = [e for e in raw if e.get("event_type", "goal") == "goal"]
goal_list.sort(key=lambda e: e.get("minute") or 0)
print(f"Torliste: {len(goal_list)} Tore aus {APP_TIMELINE}")

# --- Frames + Selbstkalibrierung --------------------------------------------
frames = sorted(f for f in os.listdir(FRAMES_DIR) if f.endswith(".png"))
_TEMPLATES = _load_templates(PROFILE["score"]["templates"])

kickoff_idx = None
scan_limit = min(len(frames), int(KICKOFF_SCAN_SECONDS * FPS))
streak = 0
for i in range(scan_limit):
    img = cv2.imread(os.path.join(FRAMES_DIR, frames[i]))
    if img is not None and read_score_00(img):
        streak += 1
        if streak >= MIN_STABLE:
            kickoff_idx = i - streak + 1
            break
    else:
        streak = 0
if kickoff_idx is None:
    raise SystemExit("Keine stabile 0:0-Anstoßtafel in den ersten "
                     f"{KICKOFF_SCAN_SECONDS}s gefunden — Anker nicht kalibrierbar.")

ax, ay, aw, ah = CALIB["anchor_region"]
calib_img = cv2.imread(os.path.join(FRAMES_DIR, frames[kickoff_idx]))
anchor = cv2.cvtColor(calib_img[ay:ay + ah, ax:ax + aw], cv2.COLOR_BGR2GRAY)
print(f"Anker selbstkalibriert aus {frames[kickoff_idx]} (0:0-Anstoßtafel, "
      f"Sekunde {round(kickoff_idx / FPS)})")

# --- Tafel-Praesenz ueber alle Frames ----------------------------------------
presence = []
for fname in frames:
    img = cv2.imread(os.path.join(FRAMES_DIR, fname))
    presence.append(board_presence(img, anchor) if img is not None else 0.0)

boards = []
i = 0
while i < len(presence):
    if presence[i] < BOARD_THRESHOLD:
        i += 1
        continue
    j = i
    while j < len(presence) and presence[j] >= BOARD_THRESHOLD:
        j += 1
    if j - i >= MIN_STABLE:
        # Minute ueber bis zu 4 Frames der Tafel lesen, haeufigster Wert
        values = []
        for k in range(i, min(i + 4, j)):
            img = cv2.imread(os.path.join(FRAMES_DIR, frames[k]))
            m = read_header_minute(img)
            if m is not None:
                values.append(m)
        minute = max(set(values), key=values.count) if values else None
        boards.append({
            "startIdx": i,
            "videoSecond": round(i / FPS),
            "frame": frames[i],
            "frames": j - i,
            "headerMinute": minute,
            "isKickoff": i <= kickoff_idx < j,
        })
    i = j

print(f"Tafeln erkannt: {len(boards)} (stabil >= {MIN_STABLE} Frames, "
      f"Schwelle {BOARD_THRESHOLD})")

# --- Zuordnung Tafel -> Tor ---------------------------------------------------
# Minute-first: exakte Minute, dann ±Toleranz. Tafeln ohne passende Minute
# (Anstoß, Halbzeit, Einwechslung) bleiben unzugeordnet. Faellt die OCR fuer
# eine Tafel aus (None), greift die Reihenfolge als Fallback — aber nur, wenn
# dadurch kein spaeteres Tor seine Minuten-Tafel verliert.
candidates = [b for b in boards if not b["isKickoff"]]
assignments = []      # (goal, board)
unmatched_boards = []
gi = 0
for b in candidates:
    if gi >= len(goal_list):
        unmatched_boards.append(b)
        continue
    g = goal_list[gi]
    bm = b["headerMinute"]
    if bm is not None:
        if abs(bm - g["minute"]) <= MINUTE_TOLERANCE:
            assignments.append((g, b))
            gi += 1
            continue
        # passt die Tafel zu einem SPAETEREN Tor? Dann wurde fuer g keine
        # Tafel gefunden -> Tor ueberspringen (lauter Hinweis am Ende).
        later = [k for k in range(gi + 1, len(goal_list))
                 if abs(goal_list[k]["minute"] - bm) <= MINUTE_TOLERANCE]
        if later:
            while gi < later[0]:
                gi += 1
            assignments.append((goal_list[gi], b))
            gi += 1
        else:
            unmatched_boards.append(b)   # z.B. Einwechslungs-Tafel
        continue
    # OCR-Luecke: nur per Reihenfolge zuordnen, wenn genug Tafeln uebrig sind
    remaining_boards = len(candidates) - candidates.index(b)
    remaining_goals = len(goal_list) - gi
    if remaining_boards > remaining_goals:
        unmatched_boards.append(b)       # vermutlich Halbzeit/Abpfiff-Tafel
    else:
        assignments.append((g, b))
        gi += 1

# --- goals.json schreiben -----------------------------------------------------
goals = []
for g, b in assignments:
    goals.append({
        "videoSecond": b["videoSecond"],
        "frame": b["frame"],
        "score": f"{g['home']}:{g['away']}",
        "scoredBy": g["team"],
        "minute": g["minute"],
        "goalMoment": None,
        "scorer": g.get("scored_by"),
        "assist": g.get("assist_by"),
    })
with open(GOALS_OUT, "w") as f:
    json.dump(goals, f, indent=2)
if BOARDS_OUT:
    with open(BOARDS_OUT, "w") as f:
        json.dump(boards, f, indent=2)

# --- Report -------------------------------------------------------------------
print(f"\n{'Tor':>4} {'Min':>4} {'Seite':>5} {'Stand':>6} | {'Tafel-Sek':>9} "
      f"{'Tafel-Min':>9}  Frame")
for g, b in assignments:
    flag = "" if (b["headerMinute"] is not None
                  and abs(b["headerMinute"] - g["minute"]) <= MINUTE_TOLERANCE) else "  <-- per Reihenfolge"
    print(f"{g['home']}:{g['away']:>2} {g['minute']:>4} {g['team']:>5} "
          f"{g['home']}:{g['away']:>3}  | {b['videoSecond']:>9} "
          f"{str(b['headerMinute']):>9}  {b['frame']}{flag}")

missed = [g for g in goal_list if g not in [a[0] for a in assignments]]
if missed:
    print(f"\nWARNUNG: {len(missed)} Tor(e) OHNE Tafel — kein Clip moeglich:")
    for g in missed:
        print(f"  Minute {g['minute']} ({g['team']}, {g.get('scored_by')})")
if unmatched_boards:
    print(f"\nUnzugeordnete Tafeln ({len(unmatched_boards)}) — erwartet: Halbzeit/"
          f"Einwechslungen/Abpfiff:")
    for b in unmatched_boards:
        print(f"  Sek {b['videoSecond']:>4}  Kopfzeilen-Minute {b['headerMinute']}  {b['frame']}")

# Plausibilitaet: Video-Reihenfolge muss der Minuten-Reihenfolge entsprechen
secs = [b["videoSecond"] for _, b in assignments]
if secs != sorted(secs):
    print("\nWARNUNG: Tafel-Sekunden nicht monoton — Zuordnung pruefen!")
print(f"\n{len(assignments)}/{len(goal_list)} Tore verankert -> {GOALS_OUT}")
