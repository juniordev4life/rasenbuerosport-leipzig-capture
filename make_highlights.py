"""End-to-End-Highlights: ein Video rein, ein Highlight-Reel raus.

Aufruf:
    python make_highlights.py <video.mov>

Verkettet die vier Stufen:
  1) Frames extrahieren (ffmpeg)
  2) Tore erkennen        (build_score_timeline.py -> goals_<name>.json)
  3) Pro Tor einen Clip   (cut_highlights.py       -> highlights_<name>/)
  4) Clips zu EINEM Reel  (ffmpeg concat           -> <name>_highlights.mp4)

Pro Spiel ein Reel. Die bestehenden Skripte werden ueber Env-Variablen
parametrisiert (ihre Logik bleibt unveraendert).
"""
import glob
import json
import os
import subprocess
import sys

from detect_skin import detect_skin_from_dir
from hud_profiles import HUD_PROFILES

# Sampling-Rate fuers Frame-Extrahieren. 2 fps ist sicherer, weil manche
# Anstoß-Tafeln nur kurz stehen; 1 fps ist schneller (wie in der Testhalbzeit).
FPS = 2

# Intro/Outro-Branding (optional): liegen intro.png + outro.png vor, werden sie
# als Splash/Abspann an jeden Tor-Clip UND ans Reel gesetzt, mit Crossfades.
INTRO_IMG = "intro.png"
OUTRO_IMG = "outro.png"
INTRO_DUR = 3.0    # Sekunden Splash am Anfang
OUTRO_DUR = 2.5    # Sekunden Abspann am Ende
XFADE = 0.6        # Sekunden Crossfade zwischen Segmenten


def detect_profile(frames_dir, override):
    """Waehlt das HUD-Profil: explizit (--hud) oder AUTOMATISCH aus dem Bild.

    Keine manuelle Wettbewerbs-Auswahl noetig — `detect_skin` bestimmt den Skin
    per HUD-Abgleich ueber Stichproben-Frames (siehe detect_skin.py). Fallback
    auf bundesliga mit Warnung, falls kein Skin sicher erkannt wird.
    """
    if override:
        return override, "explizit (--hud)"
    skin, info = detect_skin_from_dir(frames_dir)
    if skin:
        return skin, f"automatisch erkannt, Konfidenz {info['confidence']} ({info['voting_frames']} Frames)"
    return "bundesliga", "FALLBACK (Skin nicht erkannt — ggf. --hud angeben)"


def extract_frames(video, frames_dir):
    """Zerlegt das Video mit FPS in Einzelframes. Leert frames_dir vorher."""
    os.makedirs(frames_dir, exist_ok=True)
    for old in glob.glob(os.path.join(frames_dir, "*.png")):
        os.remove(old)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", video,
         "-vf", f"fps={FPS}", os.path.join(frames_dir, "frame_%05d.png")],
        check=True,
    )


def run_step(script, env_overrides):
    """Ruft eines der bestehenden Skripte mit gesetzten Env-Variablen auf."""
    subprocess.run([sys.executable, script], check=True,
                   env={**os.environ, **env_overrides})


def concat_clips(clip_paths, reel_path):
    """Fuegt die Clips (gleiche Codec-Settings) verlustfrei zu einem Reel."""
    listfile = reel_path + ".txt"
    with open(listfile, "w") as f:
        for c in clip_paths:
            f.write(f"file '{os.path.abspath(c)}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", listfile, "-c", "copy", "-movflags", "+faststart", reel_path],
        check=True,
    )
    os.remove(listfile)


def _duration(path):
    """Laufzeit einer Mediendatei in Sekunden (ffprobe)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _fps(path):
    """Bildrate eines Videos (ffprobe), z.B. 60.0. Fuer fps-Match bei xfade."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True)
    num, den = out.stdout.strip().split("/")
    return float(num) / float(den)


def make_still_segment(png, dur, out_path, out_fps=30, fade_in=False, fade_out=False):
    """Standbild -> dur-Sekunden-Clip (1920x1080, H.265, stille Tonspur). Die
    Bildrate (out_fps) muss zu den Tor-Clips passen (sonst xfade-Fehler).
    fade_in/out blendet am Anfang/Ende von/zu Schwarz."""
    vf = ["scale=1920:1080", f"fps={out_fps}", "format=yuv420p"]
    if fade_in:
        vf.append("fade=t=in:st=0:d=0.4")
    if fade_out:
        vf.append(f"fade=t=out:st={max(0.0, dur - 0.4):.3f}:d=0.4")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-loop", "1", "-t", str(dur), "-i", png,
         "-f", "lavfi", "-t", str(dur), "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
         "-vf", ",".join(vf),
         "-c:v", "libx265", "-preset", "medium", "-crf", "28", "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
         "-c:a", "aac", out_path],
        check=True)


def xfade_chain(segments, out_path, xfade=XFADE):
    """Verkettet Segmente mit weichem Crossfade (Video xfade + Audio acrossfade).
    Re-encodet (kein -c copy), weil xfade Frames verrechnet."""
    if len(segments) == 1:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", segments[0],
                        "-c", "copy", out_path], check=True)
        return
    durs = [_duration(s) for s in segments]
    inputs = []
    for s in segments:
        inputs += ["-i", s]
    vparts, prev_v, cum = [], "[0:v]", durs[0]
    for i in range(1, len(segments)):
        out_v = f"[v{i}]"
        vparts.append(f"{prev_v}[{i}:v]xfade=transition=fade:duration={xfade}:offset={cum - xfade:.3f}{out_v}")
        prev_v, cum = out_v, cum + durs[i] - xfade
    aparts, prev_a = [], "[0:a]"
    for i in range(1, len(segments)):
        out_a = f"[a{i}]"
        aparts.append(f"{prev_a}[{i}:a]acrossfade=d={xfade}{out_a}")
        prev_a = out_a
    fc = ";".join(vparts + aparts)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error"] + inputs +
        ["-filter_complex", fc, "-map", prev_v, "-map", prev_a,
         "-c:v", "libx265", "-preset", "medium", "-crf", "28", "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-movflags", "+faststart", out_path],
        check=True)


def main():
    args = sys.argv[1:]
    override = None
    if "--hud" in args:
        i = args.index("--hud")
        override = args[i + 1]
        del args[i:i + 2]
    if not args:
        print("Aufruf: python make_highlights.py <video.mov> [--hud <profil>]")
        sys.exit(1)

    video = args[0]
    if not os.path.exists(video):
        print(f"Video nicht gefunden: {video}")
        sys.exit(1)

    base = os.path.splitext(os.path.basename(video))[0]
    frames_dir = f"frames_{base}"
    goals_json = f"goals_{base}.json"
    timeline_json = f"score_timeline_{base}.json"
    clips_dir = f"highlights_{base}"
    reel = f"{base}_highlights.mp4"

    print(f"[1/4] Frames extrahieren ({FPS} fps) aus {video} ...")
    extract_frames(video, frames_dir)

    # Skin aus dem Bild bestimmen (kein Dateiname, keine manuelle Auswahl)
    profile, how = detect_profile(frames_dir, override)
    print(f"      HUD-Profil: {profile}  [{how}]")
    if profile not in HUD_PROFILES:
        print(f"HUD-Profil '{profile}' ist noch nicht kalibriert. Bekannt: {list(HUD_PROFILES)}")
        sys.exit(1)

    print(f"[2/4] Tore erkennen (HUD-Profil: {profile}) ...")
    run_step("build_score_timeline.py", {
        "FRAMES_DIR": frames_dir,
        "GOALS_OUT": goals_json,
        "SCORE_TIMELINE_OUT": timeline_json,
        "HUD_PROFILE": profile,
        "FPS": str(FPS),
    })

    # Optional: Schuetze/Vorlage aus einem App-Export einmischen (per Stand-Sequenz).
    # Quelle: Env APP_TIMELINE, sonst Konvention app_<name>.json neben dem Video.
    app_timeline = os.environ.get("APP_TIMELINE") or f"app_{base}.json"
    if os.path.exists(app_timeline):
        print(f"[2b/4] App-Daten mergen ({app_timeline}) ...")
        env = {"GOALS_IN": goals_json, "APP_TIMELINE": app_timeline, "GOALS_OUT": goals_json}
        if os.environ.get("PLAYERS"):
            env["PLAYERS"] = os.environ["PLAYERS"]
        run_step("merge_scorers.py", env)

    goals = json.load(open(goals_json))
    if not goals:
        print("Keine Tore erkannt — kein Reel erstellt.")
        return

    print(f"[3/4] {len(goals)} Tor-Clip(s) schneiden ...")
    run_step("cut_highlights.py", {
        "HL_INPUT": video,
        "GOALS_IN": goals_json,
        "HL_OUTDIR": clips_dir,
    })

    # Clips in Tor-Reihenfolge (Dateiname tor_01_, tor_02_, ...) einsammeln
    clips = sorted(glob.glob(os.path.join(clips_dir, "tor_*.mp4")))
    if not clips:
        print("Keine Clips erzeugt — Reel uebersprungen.")
        return

    if os.path.exists(INTRO_IMG) and os.path.exists(OUTRO_IMG):
        print(f"[4/4] Intro/Outro + Crossfades ({len(clips)} Tore) ...")
        clip_fps = _fps(clips[0])  # Intro/Outro muessen die fps der Tore treffen (xfade)
        intro_seg = os.path.join(clips_dir, ".intro_seg.mp4")
        outro_seg = os.path.join(clips_dir, ".outro_seg.mp4")
        make_still_segment(INTRO_IMG, INTRO_DUR, intro_seg, out_fps=clip_fps, fade_in=True)
        make_still_segment(OUTRO_IMG, OUTRO_DUR, outro_seg, out_fps=clip_fps, fade_out=True)
        # Reel: EIN Intro + alle Tore + EIN Outro, Crossfades dazwischen (aus Roh-Clips)
        xfade_chain([intro_seg] + clips + [outro_seg], reel)
        # gebrandete Einzel-Clips: Intro + Tor + Outro (ueberschreibt das Roh-Tor)
        for c in clips:
            tmp = c + ".branded.mp4"
            xfade_chain([intro_seg, c, outro_seg], tmp)
            os.replace(tmp, c)
        for seg in (intro_seg, outro_seg):
            if os.path.exists(seg):
                os.remove(seg)
        print(f"\nFertig: {reel}  ({len(clips)} Tore, mit Intro/Outro + Crossfades)")
        print(f"Gebrandete Einzel-Clips: {clips_dir}/   |   Frames (loeschbar): {frames_dir}/")
    else:
        print(f"[4/4] {len(clips)} Clip(s) zu einem Reel zusammenfuegen ...")
        concat_clips(clips, reel)
        print(f"\nFertig: {reel}  ({len(clips)} Tore)")
        print(f"Einzelclips: {clips_dir}/   |   Frames (loeschbar): {frames_dir}/")


if __name__ == "__main__":
    main()
