"""HUD-native Tor-Erkennung (Option B) — Tor-Timeline rein aus dem Live-Bild,
OHNE die scroll-abhaengige Events-Seite. Fuer 1v1 voll automatisch.

Idee: Nach jedem Tor erscheint die Anstoss-Tafel. Wir erkennen sie ueber
Praesenz (selbstkalibrierter Anker, wie build_anchor_timeline) und bestimmen,
WELCHE Seite getroffen hat, NICHT durch Ziffern-Lesen, sondern durch die
DIFFERENZ der Stand-Region gegenueber der vorigen Tafel: die Region, die sich
veraendert hat, ist die Torseite. Das hat kein Ziffern-Limit (auch zweistellig)
und filtert Zusammenfassungs-/Halbzeit-Tafeln automatisch (kein Diff -> kein Tor).

Der laufende Stand wird durch Hochzaehlen der getroffenen Seite rekonstruiert
(Start 0:0). Die Minute kommt aus der Tafel (Rezept wie build_anchor_timeline).
Der Schuetze ist bei 1v1 der EINZIGE Spieler der Seite (aus PLAYERS); bei
mehreren bleibt er offen (dann ist Option B nicht zustaendig — 2v2 nutzt weiter
die Events-Seite).

Ausgabe: App-Timeline (wie build_app_timeline/Taps), die process_highlights
sowohl ans Finalize gibt als auch als app_<base>.json fuer den Anker-Modus
schreibt.

Env:
  FRAMES_DIR   Frames des GANZEN Spiels (Pflicht)
  FPS          Frame-Rate der Extraktion (Default 2)
  HUD_PROFILE  Skin (Default bundesliga); muss in BOARD_CALIB kalibriert sein
  PLAYERS      Aufstellung als JSON: [{team, player_id, username}, ...]
  OUT          Ziel-JSON der App-Timeline (Default hud_timeline.json)
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
PLAYERS = json.loads(os.environ.get("PLAYERS", "[]"))
OUT = os.environ.get("OUT", "hud_timeline.json")

BOARD_THRESHOLD = float(os.environ.get("BOARD_THRESHOLD", "0.7"))
MIN_STABLE = int(os.environ.get("MIN_STABLE", "2"))
KICKOFF_SCAN_SECONDS = int(os.environ.get("KICKOFF_SCAN_SECONDS", "240"))
# Mittlere Abweichung der Stand-Region, ab der sie als "veraendert" gilt. Empirie
# (cross_nation): echtes Tor 27-75, unveraenderte Seite ~0.9, Summary-Tafel ~1.3.
SIDE_DIFF_MIN = float(os.environ.get("SIDE_DIFF_MIN", "8.0"))
TPL_SIZE = (50, 70)

# Board-Anker je Skin (linke Team-Box der Anstosstafel) — wie build_anchor_timeline.
BOARD_CALIB = {
    "bundesliga": {"anchor_region": (560, 920, 320, 50), "search_region": (520, 890, 420, 115)},
    "premier": {"anchor_region": (560, 832, 250, 56), "search_region": (520, 800, 360, 120)},
    "cross_nation": {"anchor_region": (595, 885, 210, 60), "search_region": (550, 855, 320, 120)},
}

if PROFILE_NAME not in HUD_PROFILES:
    raise SystemExit(f"Unbekanntes HUD-Profil '{PROFILE_NAME}'. Bekannt: {list(HUD_PROFILES)}")
if PROFILE_NAME not in BOARD_CALIB:
    raise SystemExit(f"Kein Board-Anker fuer '{PROFILE_NAME}' kalibriert. Bekannt: {list(BOARD_CALIB)}")

PROFILE = HUD_PROFILES[PROFILE_NAME]
SCORE = PROFILE["score"]
CALIB = BOARD_CALIB[PROFILE_NAME]


def _norm_glyph(im):
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
    c = _norm_glyph(crop_gray)
    best, score = None, -2.0
    for digit, tpl in templates.items():
        s = cv2.matchTemplate(c, tpl, cv2.TM_CCOEFF_NORMED)[0][0]
        if s > score:
            score, best = s, digit
    return best if score >= threshold else None


_TEMPLATES = _load_templates(SCORE["templates"])


def read_score_00(img):
    """True, wenn der Stand sicher 0:0 ist (Anstosstafel zur Selbstkalibrierung)."""
    home_t, away_t = _TEMPLATES
    hx, hy, hw, hh = SCORE["home_region"]
    ax, ay, aw, ah = SCORE["away_region"]
    h = _match_digit(cv2.cvtColor(img[hy:hy + hh, hx:hx + hw], cv2.COLOR_BGR2GRAY), home_t, SCORE["threshold"])
    a = _match_digit(cv2.cvtColor(img[ay:ay + ah, ax:ax + aw], cv2.COLOR_BGR2GRAY), away_t, SCORE["threshold"])
    return h == 0 and a == 0


def score_region_gray(img, side):
    """Graustufen-Crop der Stand-Region einer Seite ('home'/'away')."""
    x, y, w, h = SCORE[f"{side}_region"]
    return cv2.cvtColor(img[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)


def board_presence(img, anchor):
    sx, sy, sw, sh = CALIB["search_region"]
    win = cv2.cvtColor(img[sy:sy + sh, sx:sx + sw], cv2.COLOR_BGR2GRAY)
    return float(cv2.matchTemplate(win, anchor, cv2.TM_CCOEFF_NORMED).max())


# --- Minute von der Tafel lesen — Rezept wie build_anchor_timeline -----------
def _threshold(crop, method):
    if method == "white":
        b, g, r = cv2.split(crop)
        mask = ((b > 150) & (g > 150) & (r > 150)).astype("uint8") * 255
        return cv2.bitwise_not(cv2.resize(mask, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
    gray = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
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
    """Tor-Minute der Tafel (Heim- und Gast-Region, je Otsu + Roh-Fallback)."""
    mn = PROFILE["minute"]
    mode = mn.get("mode", "digit")
    whitelist = None if mode == "line" else "0123456789"
    for side in ("home", "away"):
        region = mn.get(side)
        if region is None:
            continue
        x, y, w, h, method, psm = region
        crop = img[y:y + h, x:x + w]
        if crop.size == 0:  # Region ausserhalb des Frames
            continue
        try:
            raw = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            for text in (_read(_threshold(crop, method), psm, whitelist),
                         pytesseract.image_to_string(raw, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789").strip()):
                nums = re.findall(r"\d+", text)
                if nums:
                    value = int(nums[-1] if mode == "line" else nums[0])
                    if 1 <= value <= 120:
                        return value
        except Exception:  # OCR/Tesseract-Fehler -> Minute unbekannt, nicht crashen
            continue
    return None


def lone_player(team):
    """Bei genau einem Spieler auf der Seite: (player_id, username); sonst (None, None)."""
    side = [p for p in PLAYERS if p.get("team") == team]
    if len(side) == 1:
        return side[0].get("player_id"), side[0].get("username")
    return None, None


# --- Ablauf -----------------------------------------------------------------
frames = sorted(f for f in os.listdir(FRAMES_DIR) if f.endswith(".png"))
if not frames:
    raise SystemExit(f"Keine Frames in {FRAMES_DIR}.")

# 1) Kickoff 0:0 finden -> Anker selbstkalibrieren
kickoff_idx, streak = None, 0
for i in range(min(len(frames), int(KICKOFF_SCAN_SECONDS * FPS))):
    img = cv2.imread(os.path.join(FRAMES_DIR, frames[i]))
    if img is not None and read_score_00(img):
        streak += 1
        if streak >= MIN_STABLE:
            kickoff_idx = i - streak + 1
            break
    else:
        streak = 0
if kickoff_idx is None:
    raise SystemExit(f"Keine stabile 0:0-Anstosstafel in den ersten {KICKOFF_SCAN_SECONDS}s — "
                     "Anker nicht kalibrierbar (HUD_PROFILE korrekt?).")

ax, ay, aw, ah = CALIB["anchor_region"]
anchor = cv2.cvtColor(cv2.imread(os.path.join(FRAMES_DIR, frames[kickoff_idx]))[ay:ay + ah, ax:ax + aw],
                      cv2.COLOR_BGR2GRAY)

# 2) Tafel-Bloecke ueber Praesenz erkennen
presence = []
for f in frames:
    img = cv2.imread(os.path.join(FRAMES_DIR, f))
    presence.append(board_presence(img, anchor) if img is not None else 0.0)

boards, i = [], 0
while i < len(presence):
    if presence[i] < BOARD_THRESHOLD:
        i += 1
        continue
    j = i
    while j < len(presence) and presence[j] >= BOARD_THRESHOLD:
        j += 1
    if j - i >= MIN_STABLE:
        boards.append({"i": i, "j": j, "mid": i + (j - i) // 2, "videoSecond": round(i / FPS),
                       "isKickoff": i <= kickoff_idx < j})
    i = j

# 3) Diff der Stand-Region -> Torseite, laufenden Stand hochzaehlen
#    Baseline = Kickoff-Tafel (0:0). Tafeln davor ignorieren.
start = next((k for k, b in enumerate(boards) if b["isKickoff"]), 0)
timeline, skipped = [], []
prev_home_reg = score_region_gray(cv2.imread(os.path.join(FRAMES_DIR, frames[boards[start]["mid"]])), "home")
prev_away_reg = score_region_gray(cv2.imread(os.path.join(FRAMES_DIR, frames[boards[start]["mid"]])), "away")
h, a = 0, 0

for b in boards[start + 1:]:
    img = cv2.imread(os.path.join(FRAMES_DIR, frames[b["mid"]]))
    home_reg = score_region_gray(img, "home")
    away_reg = score_region_gray(img, "away")
    hd = float(cv2.absdiff(home_reg, prev_home_reg).mean())
    ad = float(cv2.absdiff(away_reg, prev_away_reg).mean())
    prev_home_reg, prev_away_reg = home_reg, away_reg
    if max(hd, ad) < SIDE_DIFF_MIN:
        skipped.append({**b, "reason": f"keine Stand-Aenderung (h={hd:.1f} a={ad:.1f}) — Summary/Halbzeit"})
        continue
    team = "home" if hd >= ad else "away"
    if team == "home":
        h += 1
    else:
        a += 1
    # Minute ueber den Block verteilt lesen, haeufigster Wert
    minutes = []
    for k in sorted({b["i"], b["i"] + 1, b["mid"], max(b["i"], b["j"] - 2), max(b["i"], b["j"] - 1)}):
        if k >= b["j"]:
            continue
        m = read_board_minute(cv2.imread(os.path.join(FRAMES_DIR, frames[k])))
        if m is not None:
            minutes.append(m)
    minute = max(set(minutes), key=minutes.count) if minutes else None
    pid, name = lone_player(team)
    entry = {"home": h, "away": a, "team": team, "minute": minute,
             "period": "regular", "stoppage": 0, "event_type": "goal",
             "videoSecond": b["videoSecond"], "diff": {"home": round(hd, 1), "away": round(ad, 1)}}
    if pid:
        entry["scored_by"] = pid
    if name:
        entry["scored_by_name"] = name
    timeline.append(entry)

# Minuten plausibilisieren: streng aufsteigend, Ausreisser auf None. Schuetzt das
# Finalize (validateScoreTimeline verlangt Chronologie fuer Eintraege MIT Minute)
# und wirft OCR-Faulleser raus. Die Minute ist nur Deko — ein Tor ohne Minute
# zaehlt weiter fuer Stand/ELO; im Overlay/Timeline bleibt die Minute dann leer.
last_min = 0
for e in timeline:
    m = e["minute"]
    if m is not None and m > last_min:
        last_min = m
    else:
        e["minute"] = None

with open(OUT, "w") as f:
    json.dump(timeline, f, indent=2)

# --- Report -----------------------------------------------------------------
print(f"HUD-Profil:        {PROFILE_NAME}")
print(f"Kickoff:           Sek {round(kickoff_idx / FPS)} (selbstkalibriert)")
print(f"Tafel-Bloecke:     {len(boards)} (Schwelle {BOARD_THRESHOLD}, >= {MIN_STABLE} Frames)")
print(f"Tore erkannt:      {len(timeline)} -> Endstand {h}:{a}")
print(f"Aussortiert:       {len(skipped)} (Summary/Halbzeit/keine Aenderung)")
print(f"Ausgabe:           {OUT}\n")
print(f"{'Sek':>5} {'Stand':>6} {'Seite':>5} {'Min':>4} {'home-diff':>9} {'away-diff':>9}  Schuetze")
for e in timeline:
    mn = f"{e['minute']}'" if e["minute"] is not None else "?'"
    print(f"{e['videoSecond']:>5} {e['home']}:{e['away']:>3} {e['team']:>5} {mn:>4} "
          f"{e['diff']['home']:>9} {e['diff']['away']:>9}  {e.get('scored_by_name', '(offen)')}")
for b in skipped:
    print(f"  uebersprungen Sek {b['videoSecond']}: {b['reason']}")
