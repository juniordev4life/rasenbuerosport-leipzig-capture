"""Prueft die Stats-Menue-Erkennung (extract_postmatch.classify) an echten
Tab-Zeilen aus FC26- und FC27-Aufnahmen: jeder Stats-Tab wird erkannt, ein
Events-Screen mit hellem Hintergrund wird NICHT als Uebersicht gelesen, und
Spielszenen gelten nicht als Menue — auch nicht eine Bande mit Text genau auf
Hoehe der Tab-Zeile.

Die Fixtures sind nur der Streifen um die Tab-Zeile (x 480-1440, y 170-230);
der Test setzt ihn in einen schwarzen 1920x1080-Frame ein.

Aufruf: venv/bin/python tests/test_menu_detection.py
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import extract_postmatch as ep          # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "menu")
BAND_ORIGIN = (480, 170)
CASES = {
    "fc27_overview": (True, "overview"),
    "fc27_passes": (True, "passes"),
    "fc27_defense": (True, "defense"),
    "fc27_events_bright_bg": (True, "events"),
    "fc26_overview": (True, "overview"),
    "fc26_defense": (True, "defense"),
    "gameplay": (False, None),
    "hardest_negative": (False, None),
}
FAILED = []


def frame_from_band(name):
    band = cv2.imread(os.path.join(FIXTURES, f"{name}.png"), 0)
    frame = np.zeros((1080, 1920), np.uint8)
    x, y = BAND_ORIGIN
    frame[y:y + band.shape[0], x:x + band.shape[1]] = band
    return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)


def check(condition, label):
    print(f"  {'ok  ' if condition else 'FAIL'} — {label}")
    if not condition:
        FAILED.append(label)


refs = ep.load_label_refs()
print("T1: classify() an echten Tab-Zeilen")
for name, expected in CASES.items():
    got = ep.classify(frame_from_band(name), refs)
    check(got == expected, f"{name}: erwartet {expected}, erkannt {got}")

if FAILED:
    print(f"TESTS FEHLGESCHLAGEN: {len(FAILED)}")
    sys.exit(1)
print("ALLE TESTS OK")
