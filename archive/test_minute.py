import cv2
import pytesseract
import re

# Frame laden
img = cv2.imread("frames/frame_00045.png")

# Minuten-Region (erste Schätzung) — die "4'" sitzt oben, rechts vom Namen
# Grobe Schätzung, anschauen und justieren wie beim Spielstand
x, y, w, h = 860, 875, 40, 40
crop = img[y:y+h, x:x+w]

cv2.imwrite("minute_crop.png", crop)
print(f"Ausschnitt gespeichert. Bildgröße: {img.shape[1]}x{img.shape[0]}")