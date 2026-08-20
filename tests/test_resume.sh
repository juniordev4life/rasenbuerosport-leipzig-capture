#!/usr/bin/env bash
# Testet resume_pending() aus src/process_highlights.py gegen einen lokalen
# API-Stub — ohne Netz, ohne Prod, ohne gsutil. Aufruf: bash tests/test_resume.sh
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/venv/bin/python"
[ -x "$PY" ] || { echo "venv fehlt: $PY"; exit 1; }
WORK="$(mktemp -d)"; CALLS="$WORK/calls.json"; PORT=8977
FAILED=0

"$PY" "$REPO/tests/fake_api.py" "$PORT" "$CALLS" & STUB=$!
disown $STUB 2>/dev/null   # keine Job-Meldung beim Beenden
trap 'kill $STUB 2>/dev/null; rm -rf "$WORK"' EXIT
sleep 1

marker() { printf '%s' "$2" > "$WORK/$1"; }
run() {
  ( cd "$WORK" && RESUME_ONLY=1 API_BASE="$1" AGENT_SECRET=test \
      RETRY_ATTEMPTS=2 RETRY_BACKOFF=0.1 PENDING_GIVEUP_HOURS=24 \
      "$PY" "$REPO/src/process_highlights.py" 2>&1 )
}
check() {  # $1=Bedingung-Ergebnis(0/1) $2=Beschreibung
  if [ "$1" -eq 0 ]; then echo "  ok   — $2"; else echo "  FAIL — $2"; FAILED=1; fi
}
UP="http://127.0.0.1:$PORT/api/v1"
DOWN="http://127.0.0.1:9/api/v1"
NOW=$(date +%s); OLD=$((NOW - 200000))

echo "T1: Status meldbar -> Marker weg, PATCH abgesetzt"
marker pending_game_t1.json "{\"base\":\"game_t1\",\"game_id\":\"GID-T1\",\"stage\":\"patch\",\"status\":\"ready\",\"url\":\"https://x/y.mp4\",\"written_at\":$NOW}"
run "$UP" >/dev/null
[ ! -f "$WORK/pending_game_t1.json" ]; check $? "Marker nach Erfolg entfernt"
"$PY" -c "import json,sys; d=json.load(open('$CALLS')); sys.exit(0 if d and d[0]['body']=={'video_status':'ready','highlight_url':'https://x/y.mp4'} else 1)"
check $? "PATCH enthaelt Status und highlight_url"

echo "T2: API tot, Marker frisch -> Marker bleibt liegen"
marker pending_game_t2.json "{\"base\":\"game_t2\",\"game_id\":\"GID-T2\",\"stage\":\"patch\",\"status\":\"ready\",\"url\":\"https://x/y.mp4\",\"written_at\":$NOW}"
[ "$(run "$DOWN" | grep -c '^\[retry\]')" -ge 1 ]; check $? "Retry-Versuche protokolliert"
[ -f "$WORK/pending_game_t2.json" ]; check $? "Marker bleibt fuer den naechsten Versuch"
rm -f "$WORK/pending_game_t2.json"

echo "T3: API tot, Marker aelter als PENDING_GIVEUP_HOURS -> verworfen"
marker pending_game_t3.json "{\"base\":\"game_t3\",\"game_id\":\"GID-T3\",\"stage\":\"patch\",\"status\":\"ready\",\"url\":\"https://x/y.mp4\",\"written_at\":$OLD}"
run "$DOWN" >/dev/null
[ ! -f "$WORK/pending_game_t3.json" ]; check $? "kein Endlos-Zustand: alter Marker verworfen"

echo "T4: Upload-Stufe ohne Reel, frisch -> Marker bleibt"
marker pending_game_t4.json "{\"base\":\"game_t4\",\"game_id\":\"GID-T4\",\"stage\":\"upload\",\"status\":\"ready\",\"reel\":\"fehlt.mp4\",\"obj\":\"highlights/x.mp4\",\"url\":\"https://x/y.mp4\",\"written_at\":$NOW}"
run "$UP" >/dev/null
[ -f "$WORK/pending_game_t4.json" ]; check $? "Marker bleibt, wenn das Reel (noch) fehlt"
rm -f "$WORK/pending_game_t4.json"

echo "T5: kaputter Marker -> verworfen, kein Absturz"
marker pending_game_t5.json "kein json"
run "$UP" >/dev/null
[ ! -f "$WORK/pending_game_t5.json" ]; check $? "unlesbarer Marker verworfen"

[ "$FAILED" -eq 0 ] && echo "ALLE TESTS OK" || { echo "TESTS FEHLGESCHLAGEN"; exit 1; }
