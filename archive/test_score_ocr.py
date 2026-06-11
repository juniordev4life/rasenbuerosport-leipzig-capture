import cv2
import pytesseract
import re

# Frame laden
img = cv2.imread("frames/frame_00045.png")

# Spielstand-Region (deine justierten Werte)
x, y, w, h = 900, 925, 120, 50
crop = img[y:y+h, x:x+w]

# Vorverarbeitung — wie bei der Uhr: grau, 4x groß, invertiert
gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
_, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
cv2.imwrite("score_processed.png", thresh)

# OCR — Ziffern, Minus und Leerzeichen erlauben
config = "--psm 7 -c tessedit_char_whitelist=0123456789-"
text = pytesseract.image_to_string(thresh, config=config).strip()

print(f"Roh erkannt: '{text}'")

# Zwei Ziffern rausfiltern -> Heim:Gast
digits = re.findall(r"\d", text)
if len(digits) >= 2:
    print(f"OK - Spielstand erkannt: {digits[0]}:{digits[1]}")
else:
    print("Kein gueltiger Spielstand erkannt")