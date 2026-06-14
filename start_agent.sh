#!/usr/bin/env bash
# Startet den Office-Agent mit kompletter Konfiguration + Preflight-Checks.
#
# Secrets stehen NICHT hier drin: AGENT_SECRET, ANTHROPIC_API_KEY und der
# Bucket (FIREBASE_STORAGE_BUCKET) werden zur Laufzeit aus der API-.env
# gelesen — eine Quelle der Wahrheit, nichts doppelt zu pflegen.
#
#   ./start_agent.sh           # Preflight + Agent starten
#   ./start_agent.sh --check   # nur Preflight, kein Start
#
# Override per Env möglich: API_ENV (Pfad zur API-.env), HIGHLIGHTS_PREFIX,
# CAPTURE_INPUT, POLL_INTERVAL.
set -u
cd "$(dirname "$0")"

API_ENV="${API_ENV:-../rasenbuerosport-leipzig-api/.env}"
HIGHLIGHTS_PREFIX="${HIGHLIGHTS_PREFIX:-highlights-dev}"
POLL_INTERVAL="${POLL_INTERVAL:-1}"
# Audiogerät bewusst NICHT eingebunden (":none"): avfoundation lässt Bild und
# Ton mit leicht versetzten Takten laufen, der Ton driftet über lange
# Aufnahmen weg -> sichtbarer A/V-Versatz in den Highlights. Tonlos = kein
# Drift. Die Highlights sprechen für sich.
CAPTURE_INPUT="${CAPTURE_INPUT:--f avfoundation -framerate 30 -video_size 1920x1080 -pixel_format uyvy422 -i \"USB3.0 Video:none\"}"
CAPTURE_DEVICE_NAME="USB3.0 Video"

fail=0
note() { printf '  %s\n' "$1"; }
ok()   { printf '  [ok]   %s\n' "$1"; }
err()  { printf '  [FEHLT] %s\n' "$1"; fail=1; }

env_value() {
    # Wert eines Keys aus der API-.env (erste Treffer-Zeile, Quotes entfernt).
    grep -E "^$1=" "$API_ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"
}

echo "Preflight:"

# 1) API-.env + Werte
if [ -f "$API_ENV" ]; then
    ok "API-.env gefunden ($API_ENV)"
else
    err "API-.env nicht gefunden: $API_ENV (Pfad per API_ENV=... setzen)"
fi
AGENT_SECRET="$(env_value AGENT_SECRET)"
ANTHROPIC_API_KEY="$(env_value ANTHROPIC_API_KEY)"
GCS_BUCKET="$(env_value FIREBASE_STORAGE_BUCKET)"
[ -n "$AGENT_SECRET" ]      && ok "AGENT_SECRET gelesen" || err "AGENT_SECRET fehlt in der API-.env"
[ -n "$GCS_BUCKET" ]        && ok "Bucket: $GCS_BUCKET (Ordner: $HIGHLIGHTS_PREFIX)" || err "FIREBASE_STORAGE_BUCKET fehlt in der API-.env"
if [ -n "$ANTHROPIC_API_KEY" ]; then
    ok "ANTHROPIC_API_KEY gelesen (Events-Torliste aktiv)"
else
    note "[warn] ANTHROPIC_API_KEY fehlt — Aufnahme/Highlights laufen, aber ohne Taps gibt es keine Torliste (Zero-Tracking aus)."
fi

# 2) venv (Pipeline braucht cv2)
if [ -x venv/bin/python3 ]; then
    ok "venv vorhanden"
else
    err "venv fehlt: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
fi

# 3) Capture-Karte angeschlossen?
if ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | grep -q "$CAPTURE_DEVICE_NAME"; then
    ok "Capture-Karte gefunden ($CAPTURE_DEVICE_NAME)"
else
    err "Capture-Karte '$CAPTURE_DEVICE_NAME' nicht gefunden — angeschlossen? Namen pruefen: ffmpeg -f avfoundation -list_devices true -i \"\""
fi

# 4) Karte durch OBS & Co. gesperrt?
if pgrep -x OBS >/dev/null 2>&1; then
    err "OBS laeuft — die Karte ist dann gesperrt (Could not lock device). OBS beenden."
else
    ok "Kein OBS-Lock"
fi

# 5) API erreichbar?
if curl -s -m 3 -o /dev/null http://localhost:3001/health; then
    ok "API erreichbar (localhost:3001)"
else
    note "[warn] API auf localhost:3001 antwortet nicht — Agent pollt dann ins Leere, bis sie laeuft."
fi

if [ "$fail" -ne 0 ]; then
    echo "Abbruch — Preflight nicht bestanden."
    exit 1
fi
if [ "${1:-}" = "--check" ]; then
    echo "Preflight bestanden (--check, kein Start)."
    exit 0
fi

echo "Starte Office-Agent ..."
API_BASE=http://localhost:3001/api/v1 \
AGENT_SECRET="$AGENT_SECRET" \
GCS_BUCKET="$GCS_BUCKET" \
HIGHLIGHTS_PREFIX="$HIGHLIGHTS_PREFIX" \
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
CAPTURE_INPUT="$CAPTURE_INPUT" \
POLL_INTERVAL="$POLL_INTERVAL" \
PYTHONUNBUFFERED=1 \
exec venv/bin/python3 office_agent.py
