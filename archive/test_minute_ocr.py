import cv2
import pytesseract
import re

# Frame laden
img = cv2.imread("frames/frame_00045.png")

# Minuten-Region (deine justierten Werte)
x, y, w, h = 860, 875, 40, 40
crop = img[y:y+h, x:x+w]

# Vorverarbeitung — invertiert wie bei Uhr und Spielstand
gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
_, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
cv2.imwrite("minute_processed.png", thresh)

# OCR — Ziffern und Apostroph erlauben
config = "--psm 7 -c tessedit_char_whitelist=0123456789"
text = pytesseract.image_to_string(thresh, config=config).strip()

print(f"Roh erkannt: '{text}'")

# Nur die Ziffern rausfiltern -> Minute
digits = re.findall(r"\d+", text)
if digits:
    print(f"OK - Minute erkannt: {digits[0]}'")
else:
    print("Keine gueltige Minute erkannt")