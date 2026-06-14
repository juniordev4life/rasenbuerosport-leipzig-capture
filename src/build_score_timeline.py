import cv2
import pytesseract
import re
import os
import json

from hud_profiles import HUD_PROFILES

# Pfade + Profil ueberschreibbar per Env (vom Orchestrator make_highlights.py
# gesetzt), sonst Defaults -> Standalone-Aufruf bleibt moeglich.
FRAMES_DIR = os.environ.get("FRAMES_DIR", "frames")
SCORE_TIMELINE_OUT = os.environ.get("SCORE_TIMELINE_OUT", "score_timeline.json")
GOALS_OUT = os.environ.get("GOALS_OUT", "goals.json")
PROFILE_NAME = os.environ.get("HUD_PROFILE", "bundesliga")
# Sampling-Rate der Frames: videoSecond = Frame-Index / FPS = ECHTE Sekunden.
# Default 1 (frames/ wurde mit 1 fps extrahiert -> Standalone unveraendert).
FPS = float(os.environ.get("FPS", "1"))

if PROFILE_NAME not in HUD_PROFILES:
    raise SystemExit(f"Unbekanntes HUD-Profil '{PROFILE_NAME}'. Bekannt: {list(HUD_PROFILES)}")
PROFILE = HUD_PROFILES[PROFILE_NAME]

# HUD-Praesenz-Referenz (Uhr/Score-Bug oben links) fuer die Wiederholungs-
# Erkennung — nur wenn das Profil eine "hud"-Konfig hat.
HUD = PROFILE.get("hud")
_hud_ref = cv2.imread(HUD["ref"], 0) if HUD else None
SHOOTOUT = PROFILE.get("shootout")  # Elfmeterschiessen-Erkennung (optional)
# Label-Referenz fuer den "label"-Modus (cross_nation: "ELFMETER" in der HUD-Zeile)
_label_ref = (cv2.imread(SHOOTOUT["label_ref"], 0)
              if SHOOTOUT and SHOOTOUT.get("mode") == "label" else None)

# Eine Tafel-Lesung zaehlt erst, wenn derselbe Stand >= MIN_STABLE Frames steht.
MIN_STABLE = 2


def _threshold(crop, method):
    """Crop -> schwarz-auf-weiss (ohne Rand).

    method: "otsu_inv" (helle Schrift auf dunkel), "otsu" (dunkel auf hell),
    "white" (nur weisse Ziffer behalten, gegen gemischten Hintergrund —
    z.B. Premier-"0", die in den gruenen Rasen ragt).
    """
    if method == "white":
        b, g, r = cv2.split(crop)
        mask = ((b > 150) & (g > 150) & (r > 150)).astype("uint8") * 255
        return cv2.bitwise_not(cv2.resize(mask, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    otsu = cv2.THRESH_BINARY_INV if method == "otsu_inv" else cv2.THRESH_BINARY
    _, thresh = cv2.threshold(gray, 0, 255, otsu + cv2.THRESH_OTSU)
    return thresh


def _region_thresh(img, region):
    """schwarz-auf-weiss eines Region-Crops (x, y, w, h, method, psm)."""
    x, y, w, h, method, _psm = region
    return _threshold(img[y:y + h, x:x + w], method)


def _read(thresh, psm, whitelist="0123456789"):
    """OCR eines schwarz-auf-weiss Bildes; weisser Rand wird ergaenzt.
    whitelist=None -> ohne Whitelist (z.B. um eine ganze 'NAME MM'-Zeile zu lesen)."""
    thresh = cv2.copyMakeBorder(thresh, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
    config = f"--psm {psm}"
    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"
    return pytesseract.image_to_string(thresh, config=config).strip()


# --- Template-Abgleich fuer Score-Ziffern (robust gegen niedrigen Kontrast) -
TPL_SIZE = (50, 70)
_TEMPLATE_CACHE = {}


def _norm_glyph(im):
    """Auf Einheitsgroesse + Kontrast auf vollen Bereich (gegen hell-auf-hell)."""
    return cv2.normalize(cv2.resize(im, TPL_SIZE), None, 0, 255, cv2.NORM_MINMAX)


def _load_templates(tpl_dir):
    """Laedt home_/away_-Referenzziffern aus tpl_dir (gecached)."""
    if tpl_dir not in _TEMPLATE_CACHE:
        home, away = {}, {}
        for fn in os.listdir(tpl_dir):
            if not (fn.startswith("home_") or fn.startswith("away_")):
                continue  # andere Dateien (z.B. hud_ref.png) ueberspringen
            digit = int(fn.split("_")[1].split(".")[0])
            glyph = _norm_glyph(cv2.imread(os.path.join(tpl_dir, fn), 0))
            (home if fn.startswith("home") else away)[digit] = glyph
        _TEMPLATE_CACHE[tpl_dir] = (home, away)
    return _TEMPLATE_CACHE[tpl_dir]


def _match_digit(crop_gray, templates, threshold):
    """Beste Ziffer per Graustufen-Korrelation, oder None wenn < threshold."""
    c = _norm_glyph(crop_gray)
    best, score = None, -2.0
    for digit, tpl in templates.items():
        s = cv2.matchTemplate(c, tpl, cv2.TM_CCOEFF_NORMED)[0][0]
        if s > score:
            score, best = s, digit
    return best if score >= threshold else None


def read_score(img):
    """Liest den Spielstand gemaess Profil. Gibt (heim, gast) oder None."""
    sc = PROFILE["score"]
    if sc["mode"] == "dash":
        # Strikt "Ziffer - Ziffer". (Bundesliga nutzt inzwischen "template" —
        # dash-OCR war hier in BEIDE Richtungen unzuverlaessig, siehe
        # hud_profiles. Der strikte Pfad bleibt fuer kuenftige Dash-Skins.)
        region = sc["region"]
        text = _read(_region_thresh(img, region), region[5], "0123456789-")
        match = re.search(r"(\d)\s*-\s*(\d)", text)
        return (int(match.group(1)), int(match.group(2))) if match else None
    # mode "template": je eine Ziffer per Graustufen-Abgleich (OCR verliest die
    # kontrastarme Heim-Ziffer). Beide muessen sicher matchen.
    home_t, away_t = _load_templates(sc["templates"])
    hx, hy, hw, hh = sc["home_region"]
    ax, ay, aw, ah = sc["away_region"]
    h = _match_digit(cv2.cvtColor(img[hy:hy + hh, hx:hx + hw], cv2.COLOR_BGR2GRAY), home_t, sc["threshold"])
    a = _match_digit(cv2.cvtColor(img[ay:ay + ah, ax:ax + aw], cv2.COLOR_BGR2GRAY), away_t, sc["threshold"])
    return (h, a) if h is not None and a is not None else None


def read_minute(img, side):
    """Liest die Minute aus der Region der Tor-Seite (home/away). int oder None.

    mode "digit": enge Region, nur Ziffern, ERSTE Zahl (Bundesliga).
    mode "line": ganze Schuetzen-Zeile "NAME ... MM'" scannen, OHNE Whitelist,
    LETZTE Zahl nehmen. Die Minute steht je nach Namenslaenge an anderer
    X-Position, ist aber immer die letzte Zahl der Zeile (Premier).
    """
    mn = PROFILE["minute"]
    region = mn.get(side)
    if region is None:
        return None
    mode = mn.get("mode", "digit")
    whitelist = None if mode == "line" else "0123456789"
    nums = re.findall(r"\d+", _read(_region_thresh(img, region), region[5], whitelist))
    if not nums:
        return None
    value = int(nums[-1] if mode == "line" else nums[0])
    return value if 1 <= value <= 120 else None


def hud_present(img):
    """True, wenn das Live-HUD (Uhr/Score-Bug oben links) sichtbar ist; waehrend
    Jubel/Wiederholung ist es weg. None, falls das Profil keine HUD-Region hat."""
    if HUD is None or _hud_ref is None or img is None:
        return None
    x, y, w, h = HUD["region"]
    crop = cv2.cvtColor(img[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
    score = cv2.matchTemplate(crop, _hud_ref, cv2.TM_CCOEFF_NORMED)[0][0]
    return bool(score >= HUD["threshold"])


def green_present(img):
    """True, wenn im Mittel-/Unterbild gruene Wiese dominiert. Das Schiessen
    laeuft auf dem Platz; die End-Screen-Menues danach haben kein Gruen.
    None ohne shootout-Konfig."""
    if SHOOTOUT is None or img is None:
        return None
    x, y, w, h = SHOOTOUT["green_region"]
    g = img[y:y + h, x:x + w].astype(int)
    frac = ((g[:, :, 1] > g[:, :, 2] + 15) & (g[:, :, 1] > g[:, :, 0] + 15)).mean()
    return bool(frac >= SHOOTOUT["green_min"])


def label_present(img):
    """True, wenn das Schiessen-Label (cross: 'ELFMETER') in der HUD-Zeile steht.
    Per Template-Abgleich gegen die untere HUD-Zeile (im normalen Spiel steht dort
    die Uhr -> niedriger Match). Nur im shootout-Modus 'label'; sonst None."""
    if _label_ref is None or img is None:
        return None
    x, y, w, h = SHOOTOUT["label_region"]
    crop = cv2.cvtColor(img[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
    return bool(cv2.matchTemplate(crop, _label_ref, cv2.TM_CCOEFF_NORMED)[0][0] >= SHOOTOUT["label_threshold"])


# --- Schritt 1: Spielstand ueber alle Frames lesen -------------------------
frames = sorted(f for f in os.listdir(FRAMES_DIR) if f.endswith(".png"))
timeline = []
raw_hits = 0

for i, fname in enumerate(frames):
    img = cv2.imread(os.path.join(FRAMES_DIR, fname))
    score = read_score(img) if img is not None else None
    if score:
        raw_hits += 1
    timeline.append({
        "videoSecond": round(i / FPS),
        "frame": fname,
        "score": f"{score[0]}:{score[1]}" if score else None,
        "home": score[0] if score else None,
        "away": score[1] if score else None,
        "hud": hud_present(img),
        "green": green_present(img),
        "label": label_present(img),
    })


# --- Schritt 2: stabile Tafel-Lesungen bestaetigen -------------------------
def run_length(start):
    """Wie viele Frames ab start denselben Stand zeigen."""
    base = timeline[start]["score"]
    n = 0
    while start + n < len(timeline) and timeline[start + n]["score"] == base:
        n += 1
    return n


i = 0
while i < len(timeline):
    score = timeline[i]["score"]
    if score is None:
        timeline[i]["confirmed"] = False
        i += 1
        continue
    length = run_length(i)
    confirmed = length >= MIN_STABLE
    for j in range(i, i + length):
        timeline[j]["confirmed"] = confirmed
    i += length


# --- Schritt 3: Tore = Aenderung des bestaetigten Spielstands --------------
def minute_for_segment(start_idx, side):
    """Minute ueber die ganze Tafel-Phase lesen, haeufigsten Wert nehmen."""
    values = []
    for j in range(start_idx, start_idx + run_length(start_idx)):
        img = cv2.imread(os.path.join(FRAMES_DIR, timeline[j]["frame"]))
        if img is None:
            continue
        m = read_minute(img, side)
        if m is not None:
            values.append(m)
    return max(set(values), key=values.count) if values else None


def goal_moment_second(board_idx):
    """Video-Sekunde des Tor-Moments = letzter Frame mit Live-HUD VOR der Luecke
    (Jubel/Wiederholung), die zur Tafel fuehrt. So findet der Schnitt das Tor
    selbst zurueck, egal wie lang eine Wiederholung lief. None ohne HUD-Info."""
    if HUD is None:
        return None
    i = board_idx - 1
    while i >= 1:
        if timeline[i].get("hud") and timeline[i - 1].get("hud"):
            return timeline[i]["videoSecond"]
        i -= 1
    return None


goals = []
prev_home, prev_away = 0, 0  # Spielstart 0:0
last_confirmed = None
for idx, entry in enumerate(timeline):
    if not entry.get("confirmed"):
        continue
    h, a = entry["home"], entry["away"]
    if last_confirmed == (h, a):
        continue
    last_confirmed = (h, a)
    if h + a > prev_home + prev_away:
        side = "home" if h > prev_home else "away"
        goals.append({
            "videoSecond": entry["videoSecond"],
            "frame": entry["frame"],
            "score": entry["score"],
            "scoredBy": side,
            "minute": minute_for_segment(idx, side),
            "goalMoment": goal_moment_second(idx),
        })
        prev_home, prev_away = h, a

# --- Elfmeterschiessen: als eigenes Event (type "shootout") anhaengen.
# Zwei Erkennungs-Modi, je nach Skin (siehe hud_profiles "shootout"):
#   "hud_gap" (Bundesliga): das Schiessen ersetzt das HUD komplett -> langer
#       HUD-weg-Block am Spielende; End-Screens via Gruen-Check abgeschnitten.
#   "label" (cross_nation): das Schiessen behaelt ein HUD (matcht das normale
#       noch teilweise) -> stattdessen das "ELFMETER"-Label in der HUD-Zeile
#       erkennen. Block = erster Label-Frame bis letzter Gruen-Frame (Sieger-
#       Jubel), bevor die End-Screens kommen.
if SHOOTOUT and timeline:
    mode = SHOOTOUT.get("mode", "hud_gap")
    start_sec = end_sec = None
    if mode == "hud_gap" and HUD is not None:
        end = len(timeline) - 1
        while end >= 0 and timeline[end].get("hud"):
            end -= 1
        if end >= 0:
            i = end
            while i >= 0 and not timeline[i].get("hud"):
                i -= 1
            start_idx = i + 1
            j = end
            while j >= start_idx and not timeline[j].get("green"):
                j -= 1
            start_sec = timeline[start_idx]["videoSecond"]
            end_sec = timeline[j]["videoSecond"] if j >= start_idx else start_sec
    elif mode == "label":
        labels = [k for k, e in enumerate(timeline) if e.get("label")]
        if labels:
            j = labels[-1]
            while j + 1 < len(timeline) and timeline[j + 1].get("green"):
                j += 1  # bis ans Ende des Sieger-Jubels (gruene Wiese) verlaengern
            start_sec = timeline[labels[0]]["videoSecond"]
            end_sec = timeline[j]["videoSecond"]
    if start_sec is not None and end_sec - start_sec >= SHOOTOUT["min_length"]:
        goals.append({
            "type": "shootout",
            "clipStart": start_sec,
            "clipEnd": end_sec,
            "label": SHOOTOUT["label"],
        })

# --- Schritt 4: speichern + Zusammenfassung --------------------------------
with open(SCORE_TIMELINE_OUT, "w") as f:
    json.dump(timeline, f, indent=2)
with open(GOALS_OUT, "w") as f:
    json.dump(goals, f, indent=2)

confirmed_hits = sum(1 for e in timeline if e.get("confirmed"))
print(f"HUD-Profil:           {PROFILE_NAME}")
print(f"Frames gesamt:        {len(frames)}")
print(f"Stand roh erkannt:    {raw_hits}")
print(f"Stand bestaetigt:     {confirmed_hits} (>= {MIN_STABLE} Frames stabil)")
real_goals = [g for g in goals if g.get("type") != "shootout"]
print(f"Tore erkannt:         {len(real_goals)}")
print(f"Gespeichert: {SCORE_TIMELINE_OUT}, {GOALS_OUT}")

print("\nTor-Events:")
if real_goals:
    for g in real_goals:
        minute = f"{g['minute']}'" if g["minute"] is not None else "?'"
        print(f"  Sek {g['videoSecond']:4d}: {g['score']}  Min {minute}  ({g['scoredBy']})  [{g['frame']}]")
else:
    print("  (keine)")
for g in goals:
    if g.get("type") == "shootout":
        print(f"  Elfmeterschiessen: {g['clipStart']}s .. {g['clipEnd']}s")

print("\nBestaetigte Tafel-Phasen (zusammengefasst):")
i = 0
while i < len(timeline):
    e = timeline[i]
    if e.get("confirmed"):
        length = run_length(i)
        end = i + length - 1
        print(f"  Sek {e['videoSecond']:4d}-{timeline[end]['videoSecond']:4d}: {e['score']}")
        i += length
    else:
        i += 1
