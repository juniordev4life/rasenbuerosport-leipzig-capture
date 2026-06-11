"""Extrahiert Score-Ziffern-Templates fuer den cross_nation-Skin (beIN-Optik).

Die Score-Ziffern sind dunkel auf weiss. Fuer 1-3 sehen Heim und Gast gleich
aus -> ein Glyph als home_N UND away_N. Ausnahme "0": Das HEIM-"0" steht nur
beim Anstoss (0:0) auf der Tafel und wird vom Gast-"0"-Glyph nur schwach
getroffen (~0.63) -> verwechselbar mit "3" (das Anstoss-Board wurde sonst als
3:0 gelesen und vergiftete die Tor-Folge). Darum bekommt die Heim-Position ein
eigenes "0" aus dem Anstoss-Board. Quellen: vier Board-Samples (0:0, 1:0, 2:1, 3:1).

    source venv/bin/activate && python build_templates_cross.py
"""
import os
import cv2

HOME = (850, 888, 60, 74)
AWAY = (1005, 888, 85, 74)
SIZE = (50, 70)
TPL = "templates/cross_nation"

os.makedirs(TPL, exist_ok=True)


def crop(src, region):
    x, y, w, h = region
    return cv2.cvtColor(cv2.imread(src)[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)


# 1-3: identisch fuer beide Seiten. 0: positionsabhaengig (s.o.).
shared = {
    1: crop("samples/cn_sample_board.png", HOME),       # home von 1:0 -> "1"
    2: crop("samples/cn_sample_board_away.png", HOME),  # home von 2:1 -> "2"
    3: crop("samples/cn_sample_board_3_1.png", HOME),   # home von 3:1 -> "3" (cross-3-1.mov)
}
home_glyphs = {**shared, 0: crop("samples/cn_sample_board_open.png", HOME)}  # Anstoss-Heim-"0"
away_glyphs = {**shared, 0: crop("samples/cn_sample_board.png", AWAY)}       # Gast-"0" vom 1:0
for d, g in home_glyphs.items():
    cv2.imwrite(f"{TPL}/home_{d}.png", g)
for d, g in away_glyphs.items():
    cv2.imwrite(f"{TPL}/away_{d}.png", g)
print(f"Templates gespeichert in {TPL}/: home {sorted(home_glyphs)}, away {sorted(away_glyphs)} "
      f"(0 positionsabhaengig, 1-3 geteilt)")


def norm(im):
    return cv2.normalize(cv2.resize(im, SIZE), None, 0, 255, cv2.NORM_MINMAX)


HT = {d: norm(g) for d, g in home_glyphs.items()}
AT = {d: norm(g) for d, g in away_glyphs.items()}


def match(im, T):
    c = norm(im)
    return max(T, key=lambda d: cv2.matchTemplate(c, T[d], cv2.TM_CCOEFF_NORMED)[0][0])


print("\nValidierung auf den Samples:")
for src, exp in [("samples/cn_sample_board_open.png", "0:0"), ("samples/cn_sample_board.png", "1:0"),
                 ("samples/cn_sample_board_away.png", "2:1"), ("samples/cn_sample_board_3_1.png", "3:1")]:
    got = f"{match(crop(src, HOME), HT)}:{match(crop(src, AWAY), AT)}"
    print(f"  {src}: gelesen {got}  (erwartet {exp})  {'OK' if got == exp else '<-- FALSCH'}")
