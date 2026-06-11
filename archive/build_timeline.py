import cv2
import pytesseract
import re
import os
import json

# Uhr-Region (die funktionierenden Werte)
X, Y, W, H = 110, 55, 74, 30

def read_clock(frame_path):
    """Liest die Spielzeit aus einem Frame. Gibt 'MM:SS' zurück oder None."""
    img = cv2.imread(frame_path)
    if img is None:
        return None
    crop = img[Y:Y+H, X:X+W]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    config = "--psm 7 -c tessedit_char_whitelist=0123456789:"
    text = pytesseract.image_to_string(thresh, config=config).strip()
    match = re.search(r"(\d{1,3}):(\d{2})", text)
    return match.group(0) if match else None

# Alle Frames durchgehen
frames = sorted(f for f in os.listdir("frames") if f.endswith(".png"))
timeline = []
hits = 0

for i, fname in enumerate(frames):
    clock = read_clock(os.path.join("frames", fname))
    if clock:
        hits += 1
    timeline.append({"videoSecond": i, "frame": fname, "clock": clock})

# Ergebnis speichern
with open("timeline.json", "w") as f:
    json.dump(timeline, f, indent=2)

# Zusammenfassung
total = len(frames)
print(f"Frames gesamt: {total}")
print(f"Uhr erkannt:   {hits} ({round(100*hits/total)}%)")
print(f"Keine Uhr:     {total - hits}")
print("Timeline gespeichert als timeline.json")

# Erste 15 zur Kontrolle zeigen
print("\nErste 15 Frames:")
for entry in timeline[:15]:
    print(f"  Sek {entry['videoSecond']:4d}: {entry['clock']}")