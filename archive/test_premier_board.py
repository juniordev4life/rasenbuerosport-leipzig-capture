"""Kalibrier-Test fuer den Premier-League-Skin (Anstoß-Tafel).

Tesseract scheitert an einer ISOLIERTEN Ziffer (v.a. "0"), liest aber
Mehrziffern problemlos. Darum werden die beiden Score-Ziffern (home + away)
zu EINEM Bild zusammengeklebt und als zweistellige Zahl gelesen ("1"+"0" ->
"10"). Die Minute bleibt einzeln (zwei Ziffern, psm 8).

Erwartet: Kombi-Score -> [1, 0] (= 1:0), minute -> 36. Ausfuehren:
    source venv/bin/activate && python test_premier_board.py
"""
import cv2
import numpy as np
import pytesseract
import re

FRAME = "premier_sample_board.png"
HOME = (864, 831, 45, 88, "otsu", 10)
AWAY = (1008, 822, 62, 92, "white", 10)
MINUTE = (684, 916, 64, 38, "otsu", 8)


def prep(img, region):
    """Region -> schwarz-auf-weiss (ohne Rand)."""
    x, y, w, h, method, _psm = region
    crop = img[y:y + h, x:x + w]
    if method == "white":
        b, g, r = cv2.split(crop)
        mask = ((b > 150) & (g > 150) & (r > 150)).astype("uint8") * 255
        return cv2.bitwise_not(cv2.resize(mask, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    mode = cv2.THRESH_BINARY_INV if method == "otsu_inv" else cv2.THRESH_BINARY
    _, thresh = cv2.threshold(gray, 0, 255, mode + cv2.THRESH_OTSU)
    return thresh


def ocr(thresh, psm):
    thresh = cv2.copyMakeBorder(thresh, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
    return pytesseract.image_to_string(
        thresh, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789"
    ).strip()


def to_height(im, height):
    h, w = im.shape[:2]
    return cv2.resize(im, (int(w * height / h), height), interpolation=cv2.INTER_CUBIC)


img = cv2.imread(FRAME)
if img is None:
    raise SystemExit(f"Frame fehlt: {FRAME}")

print("Einzel-Lesungen (zur Kontrolle):")
for name, region in [("home", HOME), ("away", AWAY), ("minute", MINUTE)]:
    raw = ocr(prep(img, region), region[5])
    print(f"  {name:7s}: roh='{raw}'  ->  {re.findall(r'\d+', raw)}")

# Kombi: beide Score-Ziffern nebeneinander -> als zweistellige Zahl lesen
hp = to_height(prep(img, HOME), 160)
ap = to_height(prep(img, AWAY), 160)
combined = np.hstack([hp, np.full((160, 40), 255, "uint8"), ap])
raw = ocr(combined, 8)
digits = re.findall(r"\d", raw)
print(f"\nKombi-Score (home+away): roh='{raw}'  ->  Ziffern {digits}")
print("Erwartet: Kombi -> ['1', '0'] (= 1:0), minute -> 36.")
