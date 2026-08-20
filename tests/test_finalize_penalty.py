"""Prueft, dass finalize_if_pending ein erkanntes Elfmeterschiessen MIT dem
Finalize meldet — nicht erst mit dem spaeteren Status-PATCH. Die API berechnet
die ELO im Finalize und bewertet ein Elfmeterschiessen als Sieg statt als Remis;
kommt die Information danach, zaehlt der Sieg null.

Aufruf: venv/bin/python tests/test_finalize_penalty.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("PIPE_GAME_ID", "game-uuid")
os.environ.setdefault("PIPE_VIDEO", "recordings/none.mov")

import process_highlights as ph          # noqa: E402

FAILED = []
SENT = []


def fake_api_post(path, body, timeout=120):
    SENT.append((path, body))
    return {"score_home": 2, "score_away": 2}


def check(condition, label):
    print(f"  {'ok  ' if condition else 'FAIL'} — {label}")
    if not condition:
        FAILED.append(label)


ph.api_post = fake_api_post
ph.GAME_ID = "game-uuid"

TIMELINE = [{"home": 1, "away": 0, "team": "home", "minute": 3},
            {"home": 1, "away": 1, "team": "away", "minute": 7},
            {"home": 2, "away": 1, "team": "home", "minute": 8},
            {"home": 2, "away": 2, "team": "away", "minute": 9}]
PENDING = {"pending": True, "players": [{"team": "home"}, {"team": "away"}]}
POST = {"final_score": {"home": 2, "away": 2}}
PENALTY = {
    "result_type": "penalty",
    "penalty_shootout": {
        "score_before": {"home": 2, "away": 2},
        "final_score": {"home": 4, "away": 1},
        "winner_side": "home",
        "source": "auto",
    },
}

print("T1: Elfmeterschiessen geht mit dem Finalize raus")
SENT.clear()
ph.finalize_if_pending(TIMELINE, PENDING, POST, PENALTY)
check(len(SENT) == 1, "genau ein Finalize-Aufruf")
path, body = SENT[0] if SENT else ("", {})
check(path == "/recording/finalize", "Pfad /recording/finalize")
check(body.get("result_type") == "penalty", "result_type=penalty im Body")
check(body.get("penalty_shootout", {}).get("winner_side") == "home", "winner_side im Body")
check(body.get("game_id") == "game-uuid", "game_id im Body")
check(len(body.get("score_timeline") or []) == 4, "Timeline unveraendert mitgeschickt")

print("T2: ohne Elfmeterschiessen bleibt der Body schlank")
SENT.clear()
ph.finalize_if_pending(TIMELINE, PENDING, POST, None)
_, body = SENT[0]
check("result_type" not in body, "kein result_type ohne Elfmeterschiessen")
check("penalty_shootout" not in body, "kein penalty_shootout ohne Elfmeterschiessen")

print("T3: kein Finalize fuer ein nicht-pending Spiel")
SENT.clear()
ph.finalize_if_pending(TIMELINE, {"pending": False}, POST, PENALTY)
check(len(SENT) == 0, "kein Aufruf")

if FAILED:
    print(f"TESTS FEHLGESCHLAGEN: {len(FAILED)}")
    sys.exit(1)
print("ALLE TESTS OK")
