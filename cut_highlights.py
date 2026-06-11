import glob
import json
import os
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# --- Konfiguration (zum Justieren) -----------------------------------------
# Pfade ueberschreibbar per Env (vom Orchestrator gesetzt), sonst Defaults.
INPUT = os.environ.get("HL_INPUT", "erste-halbzeit.mov")
OUTDIR = os.environ.get("HL_OUTDIR", "highlights")
GOALS_IN = os.environ.get("GOALS_IN", "goals.json")

# Die Anstoß-Tafel laeuft dem Tor nach.
PRE = 25    # Fallback-Vorlauf vor der Tafel (wenn kein Tor-Moment bekannt)
POST = 5    # Sekunden nach der Tafel-Sekunde
# Adaptiver Start: liegt ein Tor-Moment vor (aus der HUD-/Wiederholungs-Erkennung),
# startet der Clip BUILDUP_BEFORE_GOAL Sekunden davor — so ist die Spielszene
# IMMER drin, egal wie lang eine Wiederholung lief.
BUILDUP_BEFORE_GOAL = 20
# War eine Wiederholung zu sehen (grosse Luecke zwischen Tor-Moment und Tafel),
# bekommt der Clip zusaetzlichen Vorlauf — sonst frisst der Jubel die kurze
# Spielszene auf. Schwelle: Tafel-Sekunde minus Tor-Moment.
REPLAY_GAP_THRESHOLD = 28   # > X Sek zwischen Tor-Moment und Tafel -> Wiederholung gelaufen
REPLAY_EXTRA = 10            # zusaetzlicher Vorlauf in dem Fall

# Einblendung am Clip-Anfang: einblenden -> halten -> ausblenden, dann weg.
BANNER_FADE_IN = 0.5    # Sekunden Einblenden
BANNER_HOLD = 4.5       # Sekunden voll sichtbar
BANNER_FADE_OUT = 0.8   # Sekunden Ausblenden

# Video-Encoding der Clips. H.265/HEVC bei 1080p -> kleine Dateien (~13 MB/30s
# statt ~41 MB). Kleiner/groesser via VIDEO_CRF (hoeher = kleiner). Fuer maximale
# Kompatibilitaet stattdessen H.264: VIDEO_CODEC="libx264", VIDEO_EXTRA=[].
VIDEO_CODEC = "libx265"
VIDEO_PRESET = "medium"
VIDEO_CRF = 28
VIDEO_EXTRA = ["-tag:v", "hvc1"]   # HEVC-Tag fuer QuickTime/Apple-Kompatibilitaet

# --- Einblendung -----------------------------------------------------------
# Liegt overlay_template.png vor (eigene 1920x1080-RGBA-Grafik), wird sie
# eingeblendet und die dynamischen Felder darauf gezeichnet. Sonst Fallback:
# schlichtes cv2-Banner. Eigene Grafik einfach als overlay_template.png ablegen
# (transparenter Hintergrund) und die Positionen unten anpassen.
TEMPLATE = "overlay_template.png"
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
# Torschütze (gross, links) + Vorlage (kleiner, RECHTS daneben). Die Vorlage wird
# DYNAMISCH hinter den Namen gesetzt (x = Name-Ende + Abstand) — so passt auch der
# längste Name samt Vorlage in den Kasten (gemessen: bleibt < x1000, Kasten ~x1015).
SCORER_POS = (165, 952)        # links, vertikal zentriert (anchor "lm")
SCORER_SIZE = 60
ASSIST_SIZE = 34               # kleiner als der Schütze, aber gut lesbar
ASSIST_GAP = 30                # Abstand zwischen Name und Vorlage
ASSIST_COLOR = (210, 218, 232)  # gedämpftes Hellgrau
# Feste Felder: (key, x, y, fontsize, (r,g,b), anchor). "mm" zentriert.
TEXT_FIELDS = [
    ("score", 1158, 952, 58, (255, 255, 255), "mm"),   # Wert unter "SPIELSTAND"
    ("minute", 1410, 952, 58, (255, 255, 255), "mm"),  # Wert unter "MINUTE"
]


def field_text(goal, key):
    """Text eines dynamischen Feldes aus dem Tor-Event."""
    if key == "score":
        return goal.get("score", "").replace(":", " : ")  # "3:1" -> "3 : 1" (wie im Design)
    if key == "minute":
        return f"{goal['minute']}'" if goal.get("minute") is not None else ""
    if key == "scorer":
        return goal.get("scorer", "")  # aus App-Taps (merge_scorers.py)
    if key == "assist":
        return f"Vorlage: {goal['assist']}" if goal.get("assist") else ""  # leer = keine Vorlage (z.B. CPU)
    return ""


def render_template_overlay(goal, out_png):
    """Zeichnet die dynamischen Felder mit Pillow (scharfe TrueType-Schrift)
    auf die eigene PNG-Vorlage."""
    base = Image.open(TEMPLATE).convert("RGBA")
    draw = ImageDraw.Draw(base)
    # Torschütze gross links; Vorlage kleiner direkt rechts daneben (dynamisch)
    sx, sy = SCORER_POS
    scorer = field_text(goal, "scorer")
    if scorer:
        sfont = ImageFont.truetype(FONT_PATH, SCORER_SIZE)
        draw.text((sx, sy), scorer, font=sfont, fill=(255, 255, 255, 255), anchor="lm")
        assist = field_text(goal, "assist")
        if assist:
            afont = ImageFont.truetype(FONT_PATH, ASSIST_SIZE)
            # Vorlage auf die BASELINE des Schützen-Namens setzen (gleiche Grundlinie,
            # nicht vertikal zentriert) -> sauberer Sitz. Baseline aus der "lm"-Mitte
            # des Schützen: Mitte + (Ascent - Descent)/2.
            asc, desc = sfont.getmetrics()
            baseline_y = sy + (asc - desc) / 2
            ax = sx + draw.textlength(scorer, font=sfont) + ASSIST_GAP
            draw.text((ax, baseline_y), assist, font=afont, fill=ASSIST_COLOR + (255,), anchor="ls")
    # feste Felder (Stand, Minute)
    for key, x, y, size, color, anchor in TEXT_FIELDS:
        text = field_text(goal, key)
        if text:
            draw.text((x, y), text, font=ImageFont.truetype(FONT_PATH, size),
                      fill=color + (255,), anchor=anchor)
    base.save(out_png)


def render_label_overlay(label, out_png):
    """Vollbild-PNG mit zentriertem Label (z.B. 'Elfmeterschießen') auf
    halbtransparentem Band unten — fuer Sonderclips ohne Stand/Minute."""
    img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 956, 1920, 1036], fill=(18, 18, 24, 200))
    draw.text((960, 996), label.upper(), font=ImageFont.truetype(FONT_PATH, 72),
              fill=(255, 255, 255, 255), anchor="mm")
    img.save(out_png)


def make_banner(text, path):
    """Fallback ohne Vorlage: schlichtes cv2-Banner (weisse Schrift auf Box)."""
    font = cv2.FONT_HERSHEY_DUPLEX
    scale, thick, pad = 1.6, 2, 26
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    w, h = tw + 2 * pad, th + base + 2 * pad
    banner = np.zeros((h, w, 4), dtype=np.uint8)
    banner[:, :, 3] = 150
    cv2.putText(banner, text, (pad, pad + th), font, scale, (255, 255, 255, 255), thick, cv2.LINE_AA)
    cv2.imwrite(path, banner)


def cut(start, dur, out, overlay=None, full_frame=False):
    """Schneidet [start, start+dur] aus INPUT. overlay-PNG wird am Clip-Anfang
    ein- und nach BANNER_HOLD wieder ausgeblendet (fade auf dem Alpha-Kanal).
    full_frame=True bei 0:0 (eigene 1920x1080-Vorlage), sonst unten mittig (Banner)."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-i", INPUT]
    if overlay:
        pos = "0:0" if full_frame else "(W-w)/2:H-h-60"
        fade_out_start = BANNER_FADE_IN + BANNER_HOLD
        fc = (
            f"[1:v]format=rgba,"
            f"fade=t=in:st=0:d={BANNER_FADE_IN}:alpha=1,"
            f"fade=t=out:st={fade_out_start}:d={BANNER_FADE_OUT}:alpha=1[ov];"
            f"[0:v][ov]overlay={pos},format=yuv420p[v]"  # format=yuv420p: Alpha weg (libx265 kann kein Alpha)
        )
        cmd += ["-loop", "1", "-i", overlay,
                "-filter_complex", fc,
                "-map", "[v]", "-map", "0:a?"]
    cmd += ["-t", str(dur),
            "-c:v", VIDEO_CODEC, "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF), *VIDEO_EXTRA,
            "-c:a", "aac", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)


# --- Ablauf ----------------------------------------------------------------
goals = json.load(open(GOALS_IN))
os.makedirs(OUTDIR, exist_ok=True)
# Alte Clips aus einem frueheren Lauf entfernen. Die Dateinamen enthalten den
# Stand (tor_NN_<score>.mp4); aendert sich die Erkennung, bleiben Clips mit
# altem Suffix liegen und der Orchestrator (glob tor_*.mp4) nimmt sie als
# Geister-Tor mit ins Reel. Darum hier zuerst leeren.
for old in glob.glob(os.path.join(OUTDIR, "tor_*.mp4")):
    os.remove(old)
use_template = os.path.exists(TEMPLATE)
print(f"Einblendung: {'eigene Vorlage ' + TEMPLATE if use_template else 'cv2-Banner (keine Vorlage)'}")

for idx, g in enumerate(goals, 1):
    # Sonderfall Elfmeterschiessen: ganzer Block als ein Clip, Label-Banner
    if g.get("type") == "shootout":
        start, dur = g["clipStart"], g["clipEnd"] - g["clipStart"]
        overlay = os.path.join(OUTDIR, f".overlay_{idx:02d}.png")
        out = os.path.join(OUTDIR, f"tor_{idx:02d}_elfmeterschiessen.mp4")
        print(f"Clip {idx}: {g['label']} {start}s..{g['clipEnd']}s -> {out}")
        try:
            render_label_overlay(g["label"], overlay)
            cut(start, dur, out, overlay, full_frame=True)
        except subprocess.CalledProcessError:
            print("  Overlay fehlgeschlagen, schneide ohne Einblendung ...")
            cut(start, dur, out)
        finally:
            if os.path.exists(overlay):
                os.remove(overlay)
        continue
    sec = g["videoSecond"]  # Tafel-Sekunde
    gm = g.get("goalMoment")
    # adaptiver Start: am Tor-Moment ankern; bei erkannter Wiederholung (grosse
    # Luecke Tor-Moment..Tafel) extra Vorlauf, sonst fester Vorlauf als Fallback
    if gm is not None:
        replay = (sec - gm) > REPLAY_GAP_THRESHOLD
        start = max(0, gm - BUILDUP_BEFORE_GOAL - (REPLAY_EXTRA if replay else 0))
    else:
        replay = False
        start = max(0, sec - PRE)
    dur = (sec + POST) - start
    overlay = os.path.join(OUTDIR, f".overlay_{idx:02d}.png")
    out = os.path.join(OUTDIR, f"tor_{idx:02d}_{g['score'].replace(':', '-')}.mp4")
    minute = g.get("minute")
    tag = "  [Wiederholung -> +Vorlauf]" if replay else ""
    print(f"Tor {idx}: {g['score']} (Min {minute}'), Tor-Moment {gm}s, Tafel {sec}s{tag} "
          f"-> Clip [{start}s .. {start + dur}s] -> {out}")
    try:
        if use_template:
            render_template_overlay(g, overlay)
            cut(start, dur, out, overlay, full_frame=True)
        else:
            caption = f"{minute}'  {g['score']}" if minute is not None else g["score"]
            make_banner(caption, overlay)
            cut(start, dur, out, overlay, full_frame=False)
    except subprocess.CalledProcessError:
        print("  Overlay fehlgeschlagen, schneide ohne Einblendung ...")
        cut(start, dur, out)
    finally:
        if os.path.exists(overlay):
            os.remove(overlay)

print(f"\n{len(goals)} Highlight-Clip(s) in {OUTDIR}/ erstellt.")
