"""Vision-Tore mit den App-Daten (Torschuetze/Vorlagengeber) verheiraten.

Aufgabenteilung (siehe Stand-Doc C2): die Vision ist Wahrheit fuer Stand, Minute
und Video-Timing (`goalMoment`); die App liefert die NAMEN (Schuetze + Vorlage).
Verknuepft wird ueber die laufende STAND-SEQUENZ — das Vision-Tor mit score "h:a"
trifft das App-Tor mit (home=h, away=a). Jeder Zwischenstand ist eindeutig, also
braucht es KEINE Wall-Clock-Synchronisation.

Das Ergebnis fuellt pro Tor `scorer` (+ `assist`), die das Overlay-Template schon
verdrahtet hat (TORSCHÜTZE-Feld). Selbstpruefend: stimmt die Vision-Seite
(`scoredBy`) nicht mit der App-Seite (`team`) ueberein, wird gewarnt.

Pfade per Env (oder Defaults):
  GOALS_IN      Vision-Tore aus build_score_timeline (default goals.json)
  APP_TIMELINE  App-`score_timeline` (Array von Tor-Events)
  PLAYERS       optional: Spieler-Map id->Name (dict oder Liste mit id/name)
  GOALS_OUT     Ausgabe (default: GOALS_IN ueberschreiben)

    python merge_scorers.py
"""
import json
import os
import re

GOALS_IN = os.environ.get("GOALS_IN", "goals.json")
APP_TIMELINE = os.environ.get("APP_TIMELINE", "app_timeline.json")
PLAYERS = os.environ.get("PLAYERS")
GOALS_OUT = os.environ.get("GOALS_OUT", GOALS_IN)


def load_players(path):
    """id->Name. Akzeptiert {id: name} oder [{id, name|display_name|gamertag}]."""
    if not path or not os.path.exists(path):
        return {}
    data = json.load(open(path))
    if isinstance(data, dict):
        return data
    out = {}
    for p in data:
        pid = p.get("id") or p.get("player_id")
        if pid:
            out[pid] = p.get("name") or p.get("display_name") or p.get("gamertag") or pid
    return out


def player_name(players, pid):
    """Name zur Spieler-ID, oder die ID selbst (wenn keine Map vorhanden)."""
    return players.get(pid, pid) if pid else None


def merge(vision_goals, app_timeline, players=None):
    """Schreibt scorer/assist (aus der App) in die Vision-Tore. Mutiert + gibt
    vision_goals zurueck. Join ueber den laufenden Stand (home, away)."""
    players = players or {}
    app_goals = [g for g in app_timeline if g.get("event_type", "goal") == "goal"]
    by_score = {(g["home"], g["away"]): g for g in app_goals}

    matched = warnings = 0
    for vg in vision_goals:
        if vg.get("type") == "shootout":
            continue  # Schiessen hat keinen Einzel-Schuetzen (Label-Clip)
        m = re.match(r"(\d+)\s*:\s*(\d+)", str(vg.get("score", "")))
        if not m:
            print(f"  WARN: Vision-Tor ohne lesbaren Stand: {vg.get('score')!r}")
            warnings += 1
            continue
        key = (int(m.group(1)), int(m.group(2)))
        ag = by_score.get(key)
        if not ag:
            print(f"  WARN: kein App-Tor fuer Stand {key[0]}:{key[1]} (Tap vergessen?)")
            warnings += 1
            continue
        vg["scorer"] = player_name(players, ag.get("scored_by"))
        vg["assist"] = player_name(players, ag.get("assist_by"))
        vg["scorerId"] = ag.get("scored_by")
        vg["assistId"] = ag.get("assist_by")
        vg["isOwnGoal"] = ag.get("is_own_goal", False)
        # Minute: Vision (OCR) bleibt fuehrend; App-Minute nur als Fallback,
        # falls das OCR die Minute nicht lesen konnte.
        if vg.get("minute") is None and ag.get("minute") is not None:
            vg["minute"] = ag["minute"]
        # Plausibilitaet: welche Seite hat getroffen?
        if vg.get("scoredBy") and ag.get("team") and vg["scoredBy"] != ag["team"]:
            print(f"  WARN: Seiten-Mismatch bei {key[0]}:{key[1]} — "
                  f"Vision '{vg['scoredBy']}' vs App '{ag['team']}'")
            warnings += 1
        matched += 1
    return vision_goals, matched, warnings


if __name__ == "__main__":
    vision = json.load(open(GOALS_IN))
    app = json.load(open(APP_TIMELINE))
    players = load_players(PLAYERS)
    merged, matched, warnings = merge(vision, app, players)
    json.dump(merged, open(GOALS_OUT, "w"), indent=2, ensure_ascii=False)
    print(f"Gemerged: {matched} Tor(e) mit Schuetze/Vorlage gefuellt, "
          f"{warnings} Warnung(en) -> {GOALS_OUT}")
