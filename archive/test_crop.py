import cv2

# Frame laden
img = cv2.imread("frames/frame_00200.png")

# Uhr-Region (erste Schätzung) — x, y, Breite, Höhe
x, y, w, h = 120, 55, 78, 45

# Ausschneiden
crop = img[y:y+h, x:x+w]

# Ausschnitt als eigenes Bild speichern, zum Anschauen
cv2.imwrite("clock_crop.png", crop)
print("Ausschnitt gespeichert als clock_crop.png")
print(f"Bildgröße gesamt: {img.shape[1]}x{img.shape[0]}")