"""Erzeugt eine BEISPIEL-Lower-Third als overlay_template.png (1920x1080 RGBA).

Nur die Grafik/Platte — die dynamischen Felder (Minute, Stand) zeichnet
cut_highlights.py zur Laufzeit darauf. Ersetze overlay_template.png durch deine
eigene Grafik (gleiche Groesse 1920x1080, transparenter Hintergrund) oder passe
dieses Skript an. Die Textpositionen stehen in cut_highlights.py (TEXT_FIELDS).

    source venv/bin/activate && python make_overlay_template.py
"""
from PIL import Image, ImageDraw

W, H = 1920, 1080
RBL_RED = (221, 0, 55, 255)

img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Platte unten mittig
x0, y0, x1, y1 = 680, 946, 1240, 1020
draw.rounded_rectangle([x0, y0, x1, y1], radius=14, fill=(18, 18, 24, 215))
# roter Akzent links
draw.rounded_rectangle([x0, y0, x0 + 12, y1], radius=6, fill=RBL_RED)
# Trenner zwischen Minute (links) und Stand (rechts)
draw.line([(960, y0 + 12), (960, y1 - 12)], fill=(255, 255, 255, 90), width=2)

img.save("overlay_template.example.png")
print("overlay_template.example.png erzeugt (Beispiel/Format-Referenz; ueberschreibt NICHT deine overlay_template.png).")
