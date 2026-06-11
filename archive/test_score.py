import cv2
import pytesseract
import re

# Frame mit der Anstoß-Tafel laden
img = cv2.imread("frames/frame_00045.png")

# Spielstand-Region (erste Schätzung) — x, y, Breite, Höhe
x, y, w, h = 900, 925, 120, 50
crop = img[y:y+h, x:x+w]

# Ausschnitt zum Anschauen speichern
cv2.imwrite("score_crop.png", crop)
print(f"Ausschnitt gespeichert. Bildgröße gesamt: {img.shape[1]}x{img.shape[0]}")