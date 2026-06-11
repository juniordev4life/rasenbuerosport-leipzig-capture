import cv2
import pytesseract
import re

# Frame laden
img = cv2.imread("frames/frame_00200.png")

# Uhr-Region — Höhe reduziert von 45 auf 30
x, y, w, h = 110, 55, 74, 30
crop = img[y:y+h, x:x+w]

# Vorverarbeitung: Graustufen, 4x hochskalieren, Otsu-Schwellwert
gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
# THRESH_BINARY_INV invertiert: dunkle Ziffern auf hellem Grund
_, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

# Vorverarbeitetes Bild speichern, damit wir sehen was die OCR "sieht"
cv2.imwrite("clock_processed.png", thresh)

# OCR — nur Ziffern und Doppelpunkt erlauben
config = "--psm 7 -c tessedit_char_whitelist=0123456789:"
text = pytesseract.image_to_string(thresh, config=config).strip()

print(f"Roh erkannt: '{text}'")

# Plausibilitätscheck: Format MM:SS
match = re.search(r"(\d{1,3}):(\d{2})", text)
if match:
    print(f"✓ Spielzeit erkannt: {match.group(0)}")
else:
    print("✗ Keine gültige Zeit erkannt")