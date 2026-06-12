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
  3) Zuordnung Tafel -> Tor primär über die REIHENFOLGE (beide chronologisch).
     Die Minute aus der Tafel (OCR der Schützenzeile, Rezept wie read_minute
     in build_score_timeline) dient als Filter + Validierung: Tafeln, deren
     Minute eine FRÜHERE Tafel wiederholt, sind Halbzeit-/Zusammenfassungs-
     Tafeln (alle drei Skins zeigen dort die bisherigen Schützen) und fliegen
     raus. App-TAP-Minuten weichen real bis zu ~8 Minuten von den Tafel-Minuten
     ab (premier-4-2: Tap 28' vs. Tafel 36') — darum ist die Minute bewusst
     NICHT das primäre Zuordnungssignal.

Gelernte Stolperfallen, die dieses Skript abdeckt:
  - Premier-Tafeln ANIMIEREN (~1.5s): Score/Schützenzeile erscheinen erst nach
    dem Band -> OCR liest aus der BLOCKMITTE, nicht den ersten Frames.
  - Schützen-Badge sitzt seitlich (Heim-Tor links, Gast-Tor rechts) -> die
    engen Seiten-Regionen aus PROFILE['minute'] nutzen (validiertes Rezept),
    nicht einen breiten Strip.

Ausgabe ist das normale goals_*.json-Schema (cut_highlights-kompatibel, inkl.
scorer/assist fürs Banner). goalMoment bleibt None: die HUD-Referenz ist
team-spezifisch — bekannter Folgeschritt. Elfmeterschießen behandelt dieser
Prototyp NICHT.

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
MINUTE_TOLERANCE = int(os.environ.get("MINUTE_TOLERANCE", "10"))  # Taps sind unscharf!
BOARD_THRESHOLD = float(os.environ.get("BOARD_THRESHOLD", "0.7"))
MIN_STABLE = int(os.environ.get("MIN_STABLE", "2"))
KICKOFF_SCAN_SECONDS = int(os.environ.get("KICKOFF_SCAN_SECONDS", "240"))

# Anker-Kalibrierung je Skin: Region der linken Team-Box (wird aus der
# 0:0-Anstoßtafel gecroppt) + Suchfenster mit Lage-Toleranz. Die Minuten-
# Regionen kommen aus PROFILE['minute'] (dort bereits je Skin validiert).
# Bei Uebernahme in den Normalbetrieb -> hud_profiles.
BOARD_CALIB = {
    "bundesliga": {
        "anchor_region": (560, 920, 320, 50),
        "search_region": (520, 890, 420, 115),
    },
    "premier": {
        "anchor_region": (560, 832, 250, 56),
        "search_region": (520, 800, 360, 120),
    },
    "cross_nation": {
        "anchor_region": (595, 885, 210, 60),
        "search_region": (550, 855, 320, 120),
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


# --- Minute von der Tafel lesen — Rezept wie read_minute/build_score_timeline:
# enge Seiten-Region, methodengerechte Binarisierung, x4-Upscale, psm/Whitelist
# je Modus ("line": ganze Schuetzenzeile, LETZTE Zahl; "digit": Box, ERSTE Zahl).
def _threshold(crop, method):
    if method == "white":
        b, g, r = cv2.split(crop)
        mask = ((b > 150) & (g > 150) & (r > 150)).astype("uint8") * 255
        return cv2.bitwise_not(cv2.resize(mask, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    otsu = cv2.THRESH_BINARY_INV if method == "otsu_inv" else cv2.THRESH_BINARY
    _, thresh = cv2.threshold(gray, 0, 255, otsu + cv2.THRESH_OTSU)
    return thresh


def _read(thresh, psm, whitelist="0123456789"):
    thresh = cv2.copyMakeBorder(thresh, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
    config = f"--psm {psm}"
    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"
    return pytesseract.image_to_string(thresh, config=config).strip()


def read_board_minute(img):
    """Tor-Minute der Tafel: probiert Heim- und Gast-Region (nur die Schuetzen-
    Seite ist belegt), je Region zwei Lese-Wege: (1) Binarisierung nach Profil-
    Methode (Premier 'otsu', Bundesliga 'otsu_inv'), (2) ROH-Graustufen-Fallback
    — die Cross-Minutenbox (weiss auf gruen) liest NUR roh, beide Otsu-Pfade
    versagen dort (empirisch geprueft). None bei Anstoß-Tafeln (keine Zahl)."""
    mn = PROFILE["minute"]
    mode = mn.get("mode", "digit")
    whitelist = None if mode == "line" else "0123456789"
    for side in ("home", "away"):
        region = mn.get(side)
        if region is None:
            continue
        x, y, w, h, method, psm = region
        crop = img[y:y + h, x:x + w]
        raw = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None,
                         fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        for text in (
            _read(_threshold(crop, method), psm, whitelist),
            pytesseract.image_to_string(
                raw, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789").strip(),
        ):
            nums = re.findall(r"\d+", text)
            if not nums:
                continue
            value = int(nums[-1] if mode == "line" else nums[0])
            if 1 <= value <= 120:
                return value
    return None


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
        # Minute ueber den GANZEN Block verteilt lesen (Anfang/Mitte/Ende),
        # haeufigster Wert gewinnt. Grund: die Skins timen unterschiedlich —
        # Premier animiert die Schuetzenzeile erst REIN (Blockanfang leer),
        # beim Cross-Skin verschwindet das Schuetzenfoto samt Minute VOR dem
        # Bandende (Blockende leer). Verteilte Samples decken beides ab.
        mid = i + max(0, (j - i) // 2 - 1)
        sample_idx = sorted({i, i + 1, mid, mid + 1, max(i, j - 2), max(i, j - 1)})
        values = []
        for k in sample_idx:
            if k >= j:
                continue
            img = cv2.imread(os.path.join(FRAMES_DIR, frames[k]))
            m = read_board_minute(img)
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

# --- Nicht-Tor-Tafeln filtern --------------------------------------------------
# 1) Anstoß-Tafel (Kalibrierquelle). 2) Halbzeit-/Zusammenfassungs-Tafeln: alle
# drei Skins zeigen dort die BISHERIGEN Schuetzen -> ihre Minute wiederholt eine
# fruehere Tafel-Minute. Nur anwenden, solange Tafel-Ueberschuss besteht (zwei
# echte Tore in derselben Minute sollen nicht rausfallen).
candidates = [b for b in boards if not b["isKickoff"]]
filtered = []
seen_minutes = set()
surplus = len(candidates) - len(goal_list)
for b in candidates:
    m = b["headerMinute"]
    if surplus > 0 and m is not None and m in seen_minutes:
        b["reason"] = f"Minute {m} wiederholt sich (Halbzeit-/Summary-Tafel)"
        filtered.append(b)
        surplus -= 1
        continue
    if m is not None:
        seen_minutes.add(m)
    b["goalCandidate"] = True
goal_boards = [b for b in candidates if b.get("goalCandidate")]

# --- Zuordnung: Reihenfolge primaer, Minute als Validierung -------------------
# Tap-Minuten der App weichen real bis zu ~8 Minuten von den Tafel-Minuten ab —
# darum NICHT minutengenau zuordnen. Bei Gleichstand der Anzahlen wird in
# Reihenfolge gezippt; Ueberschuss-Tafeln ohne Minuten-Naehe zu irgendeinem Tor
# (±MINUTE_TOLERANCE) fliegen zuerst, danach vom Ende (Abpfiff-Tafeln).
assignments = []
skipped_boards = list(filtered)
work = list(goal_boards)

while len(work) > len(goal_list):
    no_match = [b for b in work
                if b["headerMinute"] is None
                or not any(abs(b["headerMinute"] - g["minute"]) <= MINUTE_TOLERANCE
                           for g in goal_list)]
    drop = no_match[0] if no_match else work[-1]
    drop["reason"] = drop.get("reason") or "Ueberschuss (keine Minuten-Naehe zu einem Tor)"
    skipped_boards.append(drop)
    work.remove(drop)

for g, b in zip(goal_list, work):
    assignments.append((g, b))

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
print(f"\n{'Stand':>6} {'Tap-Min':>7} {'Seite':>5} | {'Tafel-Sek':>9} {'Tafel-Min':>9}"
      f"  {'Abw.':>5}  Frame")
for g, b in assignments:
    dev = "" if b["headerMinute"] is None else f"{b['headerMinute'] - g['minute']:+d}"
    warn = ""
    if b["headerMinute"] is not None and abs(b["headerMinute"] - g["minute"]) > MINUTE_TOLERANCE:
        warn = "  <-- Abweichung > Toleranz, Zuordnung pruefen!"
    print(f"{g['home']}:{g['away']:>2} {g['minute']:>7} {g['team']:>5} | "
          f"{b['videoSecond']:>9} {str(b['headerMinute']):>9}  {dev:>5}  {b['frame']}{warn}")

if len(assignments) < len(goal_list):
    print(f"\nWARNUNG: {len(goal_list) - len(assignments)} Tor(e) OHNE Tafel — kein Clip moeglich:")
    for g in goal_list[len(assignments):]:
        print(f"  Minute {g['minute']} ({g['team']}, {g.get('scored_by')})")
if skipped_boards:
    print(f"\nAussortierte Tafeln ({len(skipped_boards)}):")
    for b in skipped_boards:
        print(f"  Sek {b['videoSecond']:>4}  Minute {str(b['headerMinute']):>4}  "
              f"{b['frame']}  [{b.get('reason', '?')}]")

secs = [b["videoSecond"] for _, b in assignments]
if secs != sorted(secs):
    print("\nWARNUNG: Tafel-Sekunden nicht monoton — Zuordnung pruefen!")
print(f"\n{len(assignments)}/{len(goal_list)} Tore verankert -> {GOALS_OUT}")
