import json

MAX_FORWARD_JUMP = 25   # max. plausibler Vorwärtssprung der Spielzeit (Sek)
MAX_BACKWARD = 2        # kleine Rückwärts-Toleranz für OCR-Wackler
GAP_RESET = 3           # nach so vielen None hintereinander: Neustart

def to_seconds(clock):
    if not clock:
        return None
    try:
        mm, ss = clock.split(":")
        return int(mm) * 60 + int(ss)
    except (ValueError, AttributeError):
        return None

def to_clock(total):
    return f"{total // 60:02d}:{total % 60:02d}"

timeline = json.load(open("timeline.json"))

smoothed = []
last_valid = None
none_streak = 0      # wie viele None zuletzt in Folge
rejected = 0

for entry in timeline:
    raw = entry["clock"]
    secs = to_seconds(raw)
    result = None

    if secs is None:
        none_streak += 1
        # Nach längerer Lücke: Kontext zurücksetzen (neuer Abschnitt)
        if none_streak >= GAP_RESET:
            last_valid = None
        result = None
    else:
        if last_valid is None:
            # Erster Wert oder Wiedereinstieg nach Lücke -> akzeptieren
            result = secs
            last_valid = secs
        else:
            diff = secs - last_valid
            if -MAX_BACKWARD <= diff <= MAX_FORWARD_JUMP:
                result = secs
                last_valid = secs       # nur bei Akzeptanz aktualisieren
            else:
                rejected += 1
                result = None
                # last_valid bleibt — ein einzelner Ausreißer reißt die Kette nicht ab
        none_streak = 0

    smoothed.append({
        "videoSecond": entry["videoSecond"],
        "frame": entry["frame"],
        "clockRaw": raw,
        "clock": to_clock(result) if result is not None else None,
    })

with open("timeline_smoothed.json", "w") as f:
    json.dump(smoothed, f, indent=2)

raw_hits = sum(1 for e in timeline if e["clock"])
smooth_hits = sum(1 for e in smoothed if e["clock"])
print(f"Roh erkannt:        {raw_hits}")
print(f"Nach Glättung:      {smooth_hits}")
print(f"Als Ausreißer raus: {rejected}")
print("Gespeichert als timeline_smoothed.json")

print("\nKorrigierte Stellen (Roh -> geglättet):")
shown = 0
for e in smoothed:
    if e["clockRaw"] and e["clock"] != e["clockRaw"]:
        print(f"  Sek {e['videoSecond']:4d}: {e['clockRaw']} -> {e['clock']}")
        shown += 1
        if shown >= 20:
            print("  ...")
            break
if shown == 0:
    print("  (keine — die Rohdaten waren schon sauber)")