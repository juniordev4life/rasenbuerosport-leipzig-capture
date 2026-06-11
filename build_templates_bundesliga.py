"""Extrahiert Score-Ziffern-Templates fuer den Bundesliga-Skin.

Warum Template-Abgleich statt OCR: Die Anstoss-Tafel zeigt den Stand als
"H - A" (helle Ziffern auf dunklem Band). Tesseract liest das unzuverlaessig
in BEIDE Richtungen — den Bindestrich laesst es auf einem gestochen scharfen
"2 - 0" oft weg (kommt als "20"), und im laufenden Spiel verliest es
Marker-Dreiecke/Ball zu zufaelligen zweistelligen "Staenden" (4:4, 8:8, ...).
So ging in bundesliga-2-2-5_3 das 2:0 verloren (nur 1 von ~8 Tafel-Frames
sauber gelesen) UND ein Fehl-"2:4" im Spiel wurde als Tor bestaetigt.

Loesung wie bei Premier/cross_nation: die zwei Einzelziffern (links vom Strich
= Heim, rechts = Gast) per Graustufen-Korrelation gegen Referenz-Glyphen
abgleichen. Robust gegen den Bindestrich UND gegen Live-Play-Rauschen (das
korreliert <0.3 mit echten Ziffern). Die Glyphen sehen fuer Heim und Gast
gleich aus -> EIN Satz, als home_N und away_N abgelegt.

Ziffern-Subregionen (datengetrieben gemessen, Spaltenprojektion):
  Heim-Ziffer x935-948, Gast-Ziffer x970-984, beide y939-957.

    source venv/bin/activate && python build_templates_bundesliga.py
"""
import os
import cv2

HOME = (931, 936, 22, 24)   # umschliesst die Heim-Ziffer mit kleinem Rand
AWAY = (967, 936, 22, 24)   # umschliesst die Gast-Ziffer mit kleinem Rand
SIZE = (50, 70)
TPL = "templates/bundesliga"

os.makedirs(TPL, exist_ok=True)


def crop(src, region):
    x, y, w, h = region
    return cv2.cvtColor(cv2.imread(src)[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)


# Glyphen aus den vier Board-Samples dieses Spiels (max. Stand 2 -> Ziffern 0-2).
# Weitere Ziffern (3-9) ergaenzen, sobald hoehere Staende auftauchen.
glyphs = {
    0: crop("samples/bl_board_1_0.png", AWAY),   # Gast von 1:0 -> "0"
    1: crop("samples/bl_board_1_0.png", HOME),   # Heim von 1:0 -> "1"
    2: crop("samples/bl_board_2_0.png", HOME),   # Heim von 2:0 -> "2"
}
for d, g in glyphs.items():
    cv2.imwrite(f"{TPL}/home_{d}.png", g)
    cv2.imwrite(f"{TPL}/away_{d}.png", g)
print(f"Templates gespeichert in {TPL}/: Ziffern {sorted(glyphs)} (home_ = away_)")


def norm(im):
    return cv2.normalize(cv2.resize(im, SIZE), None, 0, 255, cv2.NORM_MINMAX)


T = {d: norm(g) for d, g in glyphs.items()}


def match(im):
    c = norm(im)
    return max(T, key=lambda d: cv2.matchTemplate(c, T[d], cv2.TM_CCOEFF_NORMED)[0][0])


print("\nValidierung auf den Samples:")
for src, exp in [("samples/bl_board_1_0.png", "1:0"), ("samples/bl_board_2_0.png", "2:0"),
                 ("samples/bl_board_2_1.png", "2:1"), ("samples/bl_board_2_2.png", "2:2")]:
    got = f"{match(crop(src, HOME))}:{match(crop(src, AWAY))}"
    print(f"  {src}: gelesen {got}  (erwartet {exp})  {'OK' if got == exp else '<-- FALSCH'}")
