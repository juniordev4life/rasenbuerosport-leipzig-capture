"""Zentrale, CWD-unabhängige Pfade fürs Capture-/Analyse-Projekt.

Alle Skripte liegen in src/, die Assets daneben im Repo-Root (templates/,
assets/, samples/, fixtures/). Damit die Pipeline egal von wo gestartet
werden kann (Agent, manueller Lauf, anderer Arbeitsordner), werden Pfade
hier aus der Lage DIESER Datei abgeleitet — nicht aus dem aktuellen
Arbeitsverzeichnis.

    from paths import TEMPLATES, ASSETS, script
    subprocess.run([sys.executable, script("make_highlights.py"), video])
    overlay = os.path.join(ASSETS, "overlay_template.png")
"""
import os

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
TEMPLATES = os.path.join(ROOT, "templates")
ASSETS = os.path.join(ROOT, "assets")
SAMPLES = os.path.join(ROOT, "samples")
FIXTURES = os.path.join(ROOT, "fixtures")


def script(name):
    """Absoluter Pfad zu einem Geschwister-Skript in src/ (für subprocess)."""
    return os.path.join(SRC, name)
