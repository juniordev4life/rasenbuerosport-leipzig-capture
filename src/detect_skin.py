"""Automatische HUD-Skin-Erkennung aus dem Videobild (rein cv2, kein OCR).

Warum: In der Office-/Cloud-Pipeline heissen die Dateien `game_<ID>.mov` — kein
Skin-Stichwort im Namen, und die Spieler sollen den Wettbewerb NICHT manuell
waehlen. Also bestimmen wir den Skin aus dem Bild.

Wie: Jedes Profil hat eine HUD-Referenz an einer festen Stelle (`hud.region` +
`hud.ref`, siehe hud_profiles). Fuer einen Frame schneiden wir JEDES Profil an
SEINER Stelle aus und korrelieren gegen SEINE Referenz. Das Profil mit dem
hoechsten Score (ueber seiner eigenen Schwelle) "gewinnt" diesen Frame. Ueber
viele Stichproben-Frames stimmen wir ab — der Skin mit den meisten Stimmen ist
es. Nicht-Spiel-Frames (Menue/Jubel/Wiederholung) matchen nirgends und stimmen
einfach nicht mit. So ist die Erkennung robust gegen einzelne Ausreisser.

Standalone:
    python detect_skin.py frames_<name>/         # auf einem Frames-Ordner
    python detect_skin.py videos/spiel.mov        # zieht selbst Stichproben
"""
import os
import subprocess
import sys

import cv2

from hud_profiles import HUD_PROFILES

_REF_CACHE = {}


def _ref(path):
    """HUD-Referenzbild (Graustufen), gecached."""
    if path not in _REF_CACHE:
        _REF_CACHE[path] = cv2.imread(path, 0)
    return _REF_CACHE[path]


def score_profiles(img):
    """Pro Profil den HUD-Match-Score fuer EINEN Frame. Profile ohne hud-Konfig
    oder fehlende Referenz werden uebersprungen. Gibt {profil: score}."""
    out = {}
    for name, prof in HUD_PROFILES.items():
        hud = prof.get("hud")
        ref = _ref(hud["ref"]) if hud else None
        if hud is None or ref is None:
            continue
        x, y, w, h = hud["region"]
        crop = cv2.cvtColor(img[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
        if crop.shape != ref.shape:  # gegen Mini-Abweichungen robust
            crop = cv2.resize(crop, (ref.shape[1], ref.shape[0]))
        out[name] = float(cv2.matchTemplate(crop, ref, cv2.TM_CCOEFF_NORMED)[0][0])
    return out


def detect_skin(images):
    """Skin aus einer Liste BGR-Frames per Mehrheitswahl bestimmen.

    Returns (skin_name | None, info). Jeder Frame stimmt fuer das Profil mit dem
    hoechsten Score, das seine eigene `hud.threshold` erreicht. None, wenn kein
    Frame ueber irgendeine Schwelle kommt (unbekannter/uncalibrierter Skin)."""
    votes = {name: 0 for name in HUD_PROFILES}
    for img in images:
        if img is None:
            continue
        scores = score_profiles(img)
        best, best_score = None, 0.0
        for name, s in scores.items():
            if s >= HUD_PROFILES[name]["hud"]["threshold"] and s > best_score:
                best, best_score = name, s
        if best:
            votes[best] += 1
    total = sum(votes.values())
    winner = max(votes, key=votes.get) if total else None
    confidence = (votes[winner] / total) if winner else 0.0
    return winner, {"votes": votes, "voting_frames": total, "confidence": round(confidence, 2)}


def detect_skin_from_dir(frames_dir, sample=20):
    """Skin aus einem Frames-Ordner bestimmen (gleichmaessig `sample` Frames)."""
    frames = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
    if not frames:
        return None, {"votes": {}, "voting_frames": 0, "confidence": 0.0}
    step = max(1, len(frames) // sample)
    picked = frames[::step][:sample]
    images = [cv2.imread(os.path.join(frames_dir, fn)) for fn in picked]
    return detect_skin(images)


def _sample_video(video, n=15):
    """n Frames gleichmaessig aus einem Video ziehen (ffmpeg fps-Filter)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video],
        capture_output=True, text=True, check=True)
    dur = float(out.stdout.strip())
    rate = n / dur if dur > 0 else 1
    tmp = ".skin_sample"
    os.makedirs(tmp, exist_ok=True)
    for old in os.listdir(tmp):
        os.remove(os.path.join(tmp, old))
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", video,
         "-vf", f"fps={rate:.5f}", os.path.join(tmp, "s_%03d.png")],
        check=True)
    return tmp


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Aufruf: python detect_skin.py <frames_dir | video.mov>")
        sys.exit(1)
    arg = sys.argv[1]
    if os.path.isdir(arg):
        skin, info = detect_skin_from_dir(arg)
    else:
        skin, info = detect_skin_from_dir(_sample_video(arg))
    print(f"Erkannter Skin: {skin}  (Konfidenz {info['confidence']}, "
          f"{info['voting_frames']} Stimm-Frames)")
    print(f"Stimmen: {info['votes']}")
