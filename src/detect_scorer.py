"""Hybride Schützen-Erkennung per Vision-Modell (GERÜST — noch nicht validiert).

Idee: Pro Tor die Frames KURZ VOR dem Jubel (um den `goalMoment`) an ein
Vision-Modell (Claude Sonnet) geben. Das Modell liest die Marker-Farbe des
Schützen (rot/blau) — und, falls erkennbar, des Vorlagengebers — plus eine
Konfidenz. Confidence-gated genutzt: hohe Konfidenz -> automatisch übernehmen,
niedrige -> dem App-Tap / Review überlassen.

WICHTIG: Das ist das Gerüst. Es läuft erst mit echtem Material:
  - `pip install anthropic`
  - Env `ANTHROPIC_API_KEY` setzen (Modell via `SCORER_MODEL`, Default Sonnet)
  - Videos + `goals_<name>.json` (aus build_score_timeline) + Wahrheits-Labels.
Die echte Trefferquote ermitteln wir über den eval-Modus, NICHT raten.

Noch NICHT in make_highlights verdrahtet — erst messen, dann entscheiden.

Eval-Aufruf:
    ANTHROPIC_API_KEY=... python detect_scorer.py eval <video.mov> <goals.json> <labels.json>

labels.json: Liste, je Tor {"score": "2:1", "scorer_color": "red", "assist_color": "blue"}
(assist_color optional; "none"/"unknown" erlaubt). Zuordnung zu den Toren ueber den Stand.
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile

MODEL = os.environ.get("SCORER_MODEL", "claude-sonnet-4-6")
CONF_THRESHOLD = float(os.environ.get("SCORER_CONF", "0.8"))  # ab hier "automatisch übernehmen"

PROMPT = (
    "These frames are from an EA Sports FC match, captured in the ~2 seconds just "
    "before a goal. Two human players control the team; the player they control "
    "has a small RED or BLUE triangle/chevron marker floating above the head. "
    "The opponent is the CPU (no human marker).\n"
    "Determine the marker color of the player who SCORED (the one shooting / last "
    "on the ball before the net bulges). If an assisting human player is clearly "
    "identifiable (the one who passed just before), give its color too.\n"
    "Reply with ONLY a JSON object, no prose:\n"
    '{"scorer_color": "red"|"blue"|"unknown", '
    '"assist_color": "red"|"blue"|"none"|"unknown", '
    '"confidence": 0.0-1.0}\n'
    "Use \"unknown\" and a low confidence if the marker isn't clearly visible "
    "(e.g. camera cut to the goal, scramble, marker off-screen)."
)


def extract_goal_frames(video, goal, count=5, span=2.0, out_dir=None):
    """Zieht `count` Frames aus dem Video im Fenster [moment-span, moment+0.3] —
    also kurz vor dem Jubel. moment = goalMoment (echter Tor-Zeitpunkt) bzw.
    ersatzweise videoSecond. Gibt die Frame-Pfade zurueck."""
    moment = goal.get("goalMoment")
    if moment is None:
        moment = goal.get("videoSecond", 0)
    start = max(0, moment - span)
    out_dir = out_dir or tempfile.mkdtemp(prefix="scorer_")
    rate = count / (span + 0.3)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start),
         "-i", video, "-t", str(span + 0.3),
         "-vf", f"fps={rate:.4f}", os.path.join(out_dir, "g_%02d.png")],
        check=True)
    return sorted(os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".png"))


def _b64(path):
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode()


def detect_scorer(image_paths, color_map=None, model=MODEL):
    """Schickt die Frames ans Vision-Modell und gibt
    {scorer_color, assist_color, confidence, scorer, assist, raw} zurueck.
    color_map (optional): {"red": "Marco", "blue": "Tobi"} -> fuellt scorer/assist
    mit Namen (sonst bleibt's bei der Farbe). Lazy import, damit das Modul auch
    ohne installiertes anthropic-Paket ladbar bleibt (z.B. fuers Frame-Ziehen)."""
    import anthropic  # noqa: lazy — nur fuer den echten Aufruf noetig

    content = [{"type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": _b64(p)}}
               for p in image_paths]
    content.append({"type": "text", "text": PROMPT})

    resp = anthropic.Anthropic().messages.create(
        model=model, max_tokens=200,
        messages=[{"role": "user", "content": content}])
    text = resp.content[0].text
    m = re.search(r"\{.*\}", text, re.DOTALL)
    data = json.loads(m.group(0)) if m else {}

    out = {
        "scorer_color": data.get("scorer_color", "unknown"),
        "assist_color": data.get("assist_color", "unknown"),
        "confidence": float(data.get("confidence", 0.0)),
        "raw": text,
    }
    if color_map:
        out["scorer"] = color_map.get(out["scorer_color"])
        out["assist"] = color_map.get(out["assist_color"])
    return out


def _key(score):
    m = re.match(r"(\d+)\s*:\s*(\d+)", str(score))
    return (int(m.group(1)), int(m.group(2))) if m else None


def evaluate(video, goals_json, labels_json, conf_threshold=CONF_THRESHOLD):
    """Faehrt detect_scorer ueber alle (echten) Tore, vergleicht mit den Labels
    und gibt Trefferquote gesamt + bei hoher Konfidenz + Fehlerliste aus."""
    goals = [g for g in json.load(open(goals_json)) if g.get("type") != "shootout"]
    labels = {(_key(l["score"])): l for l in json.load(open(labels_json))}

    total = correct = hi = hi_correct = 0
    print(f"{'Stand':>6} | {'wahr':>5} | {'erkannt':>7} | {'Konf':>5} | ok?")
    for g in goals:
        lab = labels.get(_key(g.get("score")))
        if not lab:
            print(f"  {g.get('score'):>6} | (kein Label)")
            continue
        frames = extract_goal_frames(video, g)
        pred = detect_scorer(frames)
        truth = lab.get("scorer_color")
        ok = pred["scorer_color"] == truth
        total += 1
        correct += ok
        if pred["confidence"] >= conf_threshold:
            hi += 1
            hi_correct += ok
        print(f"  {g.get('score'):>6} | {truth:>5} | {pred['scorer_color']:>7} | "
              f"{pred['confidence']:>4.2f} | {'OK' if ok else 'X'}")
    print(f"\nGesamt: {correct}/{total} richtig"
          f" ({100*correct/total:.0f}%)" if total else "\nKeine Tore mit Label.")
    if hi:
        print(f"Bei Konfidenz >= {conf_threshold}: {hi_correct}/{hi} richtig"
              f" ({100*hi_correct/hi:.0f}%)  <- DAS ist die Hybrid-Kennzahl")
    print("Tipp: hohe Konfidenz automatisch übernehmen, Rest per Tap/Review.")


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "eval":
        evaluate(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        print("Aufruf: ANTHROPIC_API_KEY=... python detect_scorer.py eval "
              "<video.mov> <goals.json> <labels.json>")
        print("(labels.json: Liste je Tor {\"score\":\"2:1\",\"scorer_color\":\"red\"})")
