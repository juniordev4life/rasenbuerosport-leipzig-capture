"""Elfmeterschiessen-Erkennung — laeuft IMMER, unabhaengig vom Tor-Pfad (Taps /
HUD-nativ / Events / klassisch), damit das Schiessen sowohl ins Reel (eigener
Clip) als auch ins Ergebnis (result_type=penalty + Endstand + Sieger) kommt.

Cue: das Recap-Banner "TEAM  X:Y  TEAM" mit dem dunklen Score-Kasten, das
waehrend des Schiessens dauerhaft eingeblendet ist und den laufenden Stand
traegt. Pro Frame wird die "X:Y"-Box per Connected-Components in zwei Ziffern
getrennt (grosse Komponenten = Ziffern, kleine = Doppelpunkt-Punkte) und gegen
kalibrierte Ziffern-Templates gematcht — Pixel-Uebereinstimmung statt OCR, weil
OCR die stilisierten Ziffern verliest (gleiche Lehre wie beim score-Template des
normalen Spielstands). Der Endstand wird monoton rekonstruiert (Staende steigen
nur), der Sieger ist die hoehere Seite.

Robustheit: nur der groesste zusammenhaengende Lese-Block (Luecke <= max_gap_sec)
zaehlt als Schiessen — Streu-Lesungen ausserhalb fallen weg.

Ausgabe (JSON nach OUT):
  {"detected": true, "start_sec": 653, "end_sec": 794,
   "home": 6, "away": 7, "winner": "away", "label": "Elfmeterschießen"}
oder {"detected": false}.

Env:
  FRAMES_DIR   Verzeichnis mit frame_*.png
  HUD_PROFILE  Skin (Default bundesliga)
  FPS          Frames pro Sekunde (Default 2)
  OUT          Ziel-JSON (Default shootout_<skin>.json)

HINWEIS Kalibrierung: tally.box ist auf das Bundesliga-Recap-Banner kalibriert
(Heimname-abhaengige Lage wie beim Skin). Andere Skins/Layouts brauchen eigene
box-Region + Templates (wie bei der Skin-Erkennung schrittweise erweitert).
"""
import json
import os
import sys

import cv2
from hud_profiles import HUD_PROFILES

FRAMES_DIR = os.environ.get("FRAMES_DIR")
SKIN = os.environ.get("HUD_PROFILE", "bundesliga")
FPS = float(os.environ.get("FPS", "2"))
OUT = os.environ.get("OUT", f"shootout_{SKIN}.json")

PROFILE = HUD_PROFILES.get(SKIN, {})
SHOOTOUT = PROFILE.get("shootout") or {}
TALLY = SHOOTOUT.get("tally")


def _load_templates(path):
    """Ziffern-Templates 0-9 (binaer, 28x40) aus dem Verzeichnis laden (fehlende
    Ziffern sind ok — ein Stand mit unbekannter Ziffer wird einfach nicht gelesen)."""
    tpl = {}
    for v in range(10):
        f = os.path.join(path, f"{v}.png")
        if not os.path.exists(f):
            continue  # nicht kalibrierte Ziffer (z.B. 8/9) -> einfach auslassen
        img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            tpl[v] = img
    return tpl


_TEMPLATES = _load_templates(TALLY["templates"]) if TALLY else {}


def _split_digits(img):
    """"X:Y"-Box in Einzelziffern trennen. Liefert [home, away] als 28x40-
    Binaerbilder (links->rechts) oder [] wenn nicht genau zwei Ziffern gefunden."""
    x, y, w, h = TALLY["box"]
    crop = img[y:y + h, x:x + w]
    if crop.size == 0:
        return []
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    count, _, stats, _ = cv2.connectedComponentsWithStats(th, 8)
    min_h = TALLY.get("min_digit_h", 14)
    min_area = TALLY.get("min_digit_area", 40)
    digits = []
    for k in range(1, count):  # 0 = Hintergrund
        cx, cy, cw, ch, area = stats[k]
        if ch >= min_h and area >= min_area:
            d = th[cy:cy + ch, cx:cx + cw]
            digits.append((cx, cv2.resize(d, (28, 40), interpolation=cv2.INTER_NEAREST)))
    digits.sort(key=lambda c: c[0])
    return [d for _, d in digits] if len(digits) == 2 else []


def _match_digit(digit):
    """Beste Ziffer per Pixel-Uebereinstimmung gegen die Templates; None unter Schwelle."""
    best, value = -1.0, None
    for v, t in _TEMPLATES.items():
        score = float((digit == t).mean())
        if score > best:
            best, value = score, v
    return value if best >= TALLY.get("match_min", 0.82) else None


def read_tally(img):
    """(home, away) aus dem Schiessen-Score-Kasten lesen, oder None.

    @param {numpy.ndarray|None} img - BGR-Frame
    @returns {tuple[int,int]|None}
    @example
    read_tally(cv2.imread("frame_01588.png"))  # -> (6, 7)
    """
    if img is None or not TALLY or not _TEMPLATES:
        return None
    ds = _split_digits(img)
    if len(ds) != 2:
        return None
    home, away = _match_digit(ds[0]), _match_digit(ds[1])
    return (home, away) if home is not None and away is not None else None


def _largest_block(reads, max_gap_sec):
    """Groessten zusammenhaengenden Lese-Block zurueckgeben (Luecke <= max_gap_sec).
    Streu-Lesungen ausserhalb des Schiessens fallen so weg."""
    if not reads:
        return []
    blocks, current = [], [reads[0]]
    for prev, item in zip(reads, reads[1:]):
        if item[0] - prev[0] <= max_gap_sec:
            current.append(item)
        else:
            blocks.append(current)
            current = [item]
    blocks.append(current)
    return max(blocks, key=len)


def detect(frames_dir):
    """Elfmeterschiessen aus den Frames erkennen.

    @param {string} frames_dir - Verzeichnis mit frame_*.png
    @returns {object} {detected, start_sec, end_sec, home, away, winner, label}
    @example
    detect("frames_game_abc")  # -> {"detected": True, "home": 6, "away": 7, ...}
    """
    if not TALLY or not _TEMPLATES:
        return {"detected": False, "reason": "kein shootout-tally-Profil/Templates"}
    frames = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
    reads = []
    for i, fname in enumerate(frames):
        tally = read_tally(cv2.imread(os.path.join(frames_dir, fname)))
        if tally is not None:
            reads.append((round(i / FPS), tally[0], tally[1]))
    block = _largest_block(reads, SHOOTOUT.get("max_gap_sec", 20))
    if len(block) < SHOOTOUT.get("min_reads", 8):
        return {"detected": False}
    # Monotone Rekonstruktion: Staende steigen nur (akzeptiere +1-Schritte; so
    # zaehlen einzelne Fehl-Lesungen nicht und der entscheidende letzte Elfmeter
    # wird mitgenommen, auch wenn er nur in 1-2 Frames steht).
    ch = ca = 0
    for _, home, away in block:
        if home == ch + 1:
            ch = home
        if away == ca + 1:
            ca = away
    winner = "home" if ch > ca else ("away" if ca > ch else "tie")
    return {
        "detected": True,
        "start_sec": block[0][0],
        "end_sec": block[-1][0],
        "home": ch,
        "away": ca,
        "winner": winner,
        "label": SHOOTOUT.get("label", "Elfmeterschießen"),
    }


def main():
    if not FRAMES_DIR or not os.path.isdir(FRAMES_DIR):
        print("[shootout] FRAMES_DIR fehlt/ungueltig — Abbruch.")
        sys.exit(1)
    result = detect(FRAMES_DIR)
    with open(OUT, "w") as f:
        json.dump(result, f)
    if result.get("detected"):
        print(f"[shootout] erkannt: Sek {result['start_sec']}..{result['end_sec']}  "
              f"Endstand {result['home']}:{result['away']}  Sieger {result['winner']} -> {OUT}")
    else:
        print(f"[shootout] kein Elfmeterschiessen erkannt -> {OUT}")


if __name__ == "__main__":
    main()
