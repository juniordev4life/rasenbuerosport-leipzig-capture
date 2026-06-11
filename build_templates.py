"""Extrahiert Referenz-Ziffern (Templates) fuer den Premier-Score und
validiert den Graustufen-Matcher auf mehreren Tafel-Frames.

Template-Abgleich statt OCR fuer die Score-Ziffern: robust gegen den niedrigen
Kontrast der Heim-Ziffer (hell auf hellem Chevron), weil in Graustufen
kontrast-normalisiert verglichen wird. Reines cv2 — kein Tesseract.

    source venv/bin/activate && python build_templates.py
"""
import os
import cv2
import numpy as np

D = "frames_premier-league-4-2"
HOME = (864, 831, 45, 88)
AWAY = (1008, 822, 62, 92)
TPL_DIR = "templates/premier"
SIZE = (50, 70)  # einheitliche Vergleichsgroesse

# Verifizierte Quell-Frames pro Ziffer (aus der Montage gelabelt)
HOME_SRC = {0: "frame_00024", 1: "frame_00474", 2: "frame_00574", 3: "frame_01194", 4: "frame_01309"}
AWAY_SRC = {0: "frame_00024", 1: "frame_01015", 2: "frame_01309"}


def gray_crop(frame, region):
    x, y, w, h = region
    img = cv2.imread(f"{D}/{frame}.png")
    return cv2.cvtColor(img[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)


def norm(im):
    """Auf Einheitsgroesse + Kontrast auf vollen Bereich (gegen hell-auf-hell)."""
    return cv2.normalize(cv2.resize(im, SIZE), None, 0, 255, cv2.NORM_MINMAX)


# --- Templates extrahieren + speichern ------------------------------------
os.makedirs(TPL_DIR, exist_ok=True)
for d, f in HOME_SRC.items():
    cv2.imwrite(f"{TPL_DIR}/home_{d}.png", gray_crop(f, HOME))
for d, f in AWAY_SRC.items():
    cv2.imwrite(f"{TPL_DIR}/away_{d}.png", gray_crop(f, AWAY))
print(f"Templates gespeichert in {TPL_DIR}/ (home {sorted(HOME_SRC)}, away {sorted(AWAY_SRC)})")


def load(side):
    out = {}
    for fn in os.listdir(TPL_DIR):
        if fn.startswith(side):
            out[int(fn.split("_")[1].split(".")[0])] = norm(cv2.imread(f"{TPL_DIR}/{fn}", 0))
    return out


HT, AT = load("home"), load("away")


def match(crop, templates):
    c = norm(crop)
    best, score = None, -2.0
    for d, t in templates.items():
        s = cv2.matchTemplate(c, t, cv2.TM_CCOEFF_NORMED)[0][0]
        if s > score:
            score, best = s, d
    return best, score


# --- Validierung auf mehreren Frames (auch Nicht-Quell-Frames) ------------
tests = [
    ("frame_00024", "0:0"), ("frame_00026", "0:0"),
    ("frame_00474", "1:0"), ("frame_00476", "1:0"),
    ("frame_00574", "2:0"), ("frame_00576", "2:0"),
    ("frame_01015", "3:1"),
    ("frame_01194", "3:2"), ("frame_01196", "3:2"),
    ("frame_01309", "4:2"), ("frame_01311", "4:2"),
]
print("\nValidierung:")
ok = 0
for f, exp in tests:
    h, hs = match(gray_crop(f, HOME), HT)
    a, as_ = match(gray_crop(f, AWAY), AT)
    got = f"{h}:{a}"
    flag = "OK" if got == exp else "<-- FALSCH"
    if got == exp:
        ok += 1
    print(f"  {f}: erwartet {exp}, gelesen {got}  (h={hs:.2f} a={as_:.2f})  {flag}")
print(f"\n{ok}/{len(tests)} korrekt.")

print("\nNicht-Tafel-Frames (Live-Bild; sollten NIEDRIG korrelieren -> None):")
for f in ["frame_00200", "frame_00700", "frame_00900", "frame_01100", "frame_01250"]:
    h, hs = match(gray_crop(f, HOME), HT)
    a, as_ = match(gray_crop(f, AWAY), AT)
    print(f"  {f}: home {h}({hs:.2f})  away {a}({as_:.2f})")
