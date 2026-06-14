# Training & Tuning — mit fertigen Videos die Erkennung verbessern

Praktischer Leitfaden, um die Tor-/Stand-Erkennung an vorhandenem Spielmaterial
zu testen und zu verbessern. Alle Befehle mit dem venv-Python (`venv/bin/python`),
da die Pipeline cv2 braucht.

Grundprinzip vorweg: Der Stand wird per Template-Abgleich der Score-Ziffern
gelesen (kein OCR, kein Laufzeit-Lernen). Die Pipeline lernt also NICHT von
selbst dazu — neue Ziffern/Skins werden manuell aus Sample-Frames ergänzt
(Abschnitt 4). Ein verpasstes Tor ist fast immer eines von dreien: eine fehlende
Ziffer (Template-Loch), ein zu strenger Schwellwert, oder der falsch erkannte
Skin.

WICHTIG für torreiche Spiele: Ab zweistelligen Ständen (10+) ist die
Ziffern-Lesung strukturell am Ende (zwei Ziffern passen nicht in die
Ein-Ziffer-Regionen). Dafür gibt es den ANKER-MODUS (Abschnitt 8) — er braucht
gar keine Ziffern-Templates jenseits der 0 und ist am 11:10-Spiel mit 21/21
verankerten Toren validiert.

---

## 0. Voraussetzungen

```bash
cd ~/Projects/private/rasenbuerosport-leipzig-capture
# venv muss da sein (einmalig): python3 -m venv venv && venv/bin/pip install -r requirements.txt
# System: ffmpeg. (tesseract nur für die Minute-Zeile; der Stand läuft über Templates.)
mkdir -p videos
# Trainingsvideos nach videos/ legen, z.B. videos/bl-test-1.mov
```

Die Skripte legen ihre Zwischenergebnisse im Repo-Root ab, abgeleitet vom
Dateinamen (`base` = Dateiname ohne Endung). Für `videos/bl-test-1.mov`:
`frames_bl-test-1/`, `goals_bl-test-1.json`, `score_timeline_bl-test-1.json`,
`highlights_bl-test-1/`, `bl-test-1_highlights.mp4`. Alle sind gitignored.

---

## 1. Video durch die volle Pipeline jagen

```bash
venv/bin/python src/make_highlights.py videos/bl-test-1.mov
# Skin wird automatisch erkannt. Erzwingen, falls die Erkennung danebenliegt:
venv/bin/python src/make_highlights.py videos/bl-test-1.mov --hud bundesliga
```

Profile: `bundesliga`, `premier`, `cross_nation`. Danach liegen die oben
genannten Artefakte vor. Wichtig: `frames_<base>/` bleibt liegen — darauf bauen
die schnellen Iterationen in Abschnitt 3 auf.

---

## 2. Diagnose — was wurde erkannt, was fehlt?

Erkannte Tore und Stand-Verlauf ansehen:

```bash
cat goals_bl-test-1.json            # erkannte Tore: score, videoSecond, goalMoment, type
cat score_timeline_bl-test-1.json   # jeder stabile Tafel-Stand mit Frame/Sekunde
```

Vergleiche den echten Spielverlauf (du kennst das Ergebnis) mit `goals_*.json`.
Fehlt ein Tor, schau, bei welchem Stand der Sprung fehlt — z.B. das Spiel ging
über 2:1, aber `score_timeline` springt von 2:1 direkt weiter, das 3:1 fehlt.
Genau dieser Stand ist der Ansatzpunkt.

Das passende Tafel-Frame finden: Nach jedem Tor zeigt FC kurz die Anstoß-Tafel
mit dem neuen Stand. In `frames_bl-test-1/` (2 fps, fortlaufend nummeriert) im
Zeitfenster des verpassten Tors nach diesem Tafel-Frame suchen — das ist das
Rohmaterial für ein neues Template.

---

## 3. Schnelle Iteration — nur die Erkennung wiederholen

Frames neu zu extrahieren und zu schneiden dauert. Beim Tunen reicht es, die
Stand-/Tor-Erkennung auf den schon extrahierten Frames erneut laufen zu lassen:

```bash
FRAMES_DIR=frames_bl-test-1 \
HUD_PROFILE=bundesliga \
FPS=2 \
GOALS_OUT=goals_bl-test-1.json \
SCORE_TIMELINE_OUT=score_timeline_bl-test-1.json \
venv/bin/python src/build_score_timeline.py
```

`FPS=2` ist wichtig — `make_highlights` extrahiert mit 2 fps; nur dann stimmen
die zurückgerechneten Sekunden. So testest du Template- oder Schwellwert-
Änderungen in Sekunden statt Minuten. Erst wenn die Erkennung stimmt, einmal die
volle Pipeline (Abschnitt 1) für das fertige Reel.

---

## 4. Fehlende Ziffer ergänzen (der häufigste Fix)

Aktuelle Ziffern-Abdeckung der Score-Templates:

| Skin          | Heim-Ziffern | Gast-Ziffern |
|---------------|--------------|--------------|
| `bundesliga`  | 0–2          | 0–2          |
| `cross_nation`| 0–3          | 0–3          |
| `premier`     | 0–4          | 0–2          |

Erreicht ein Stand eine Ziffer außerhalb dieser Abdeckung (bei Bundesliga also
schon die 3), kann die Tafel nicht gelesen werden und das Tor fällt durch. So
ergänzt du eine Ziffer:

1. Tafel-Frame mit dem fehlenden Stand aus `frames_<base>/` als Sample ablegen,
   nach der Namenskonvention des Skins (siehe `samples/`):

   ```bash
   cp frames_bl-test-1/frame_01342.png samples/bl_board_3_1.png
   ```

2. Den passenden Builder um die neue Ziffer erweitern — das `glyphs`-Dict mappt
   Ziffer → Sample-Frame. In `build_templates_bundesliga.py` z.B.:

   ```python
   glyphs = {
       0: crop("samples/bl_board_1_0.png", AWAY),
       1: crop("samples/bl_board_1_0.png", HOME),
       2: crop("samples/bl_board_2_0.png", HOME),
       3: crop("samples/bl_board_3_1.png", HOME),   # NEU: Heim-Ziffer von 3:1
   }
   ```

   Heim- und Gast-Ziffern sehen bei Bundesliga/cross gleich aus (ein Glyph dient
   beiden Seiten). Bei `premier` sind es getrennte Sätze (`HOME_SRC`/`AWAY_SRC`).
   Die Crop-Region (`HOME`/`AWAY` im Builder) entspricht der `home_region`/
   `away_region` im jeweiligen Profil in `hud_profiles.py`.

3. Builder laufen lassen — er speichert die Templates und validiert sofort gegen
   die Samples (zeigt gelesen vs. erwartet):

   ```bash
   venv/bin/python src/tools/build_templates_bundesliga.py
   # -> templates/bundesliga/home_3.png + away_3.png, + Validierungsausgabe
   ```

4. Erkennung auf dem Video wiederholen (Abschnitt 3) und prüfen, ob das Tor jetzt
   auftaucht.

Hinweis: `build_templates_bundesliga.py` und `build_templates_cross.py` lesen aus
`samples/` (eingecheckt, reproduzierbar). `build_templates.py` (premier) liest
noch aus einem alten `frames_premier-league-4-2/`-Ordner — beim Erweitern auf
`samples/` umstellen, sonst fehlt die Quelle.

---

## 5. Schwellwerte & Stabilität tunen

Wenn ein Tafel-Frame zwar gelesen, aber knapp verworfen wird, helfen zwei Hebel:

- Match-Schwellwert pro Skin in `hud_profiles.py` → `score.threshold` (Default
  `0.5`). Niedriger = toleranter, aber Vorsicht: zu niedrig erzeugt Phantom-
  Stände aus dem Live-Bild (Marker/Ball werden zu Ziffern verlesen). In kleinen
  Schritten (0.05) testen und immer gegen ein ganzes Spiel prüfen (keine neuen
  Falsch-Positiven).
- Stabilitätsfenster `MIN_STABLE` in `build_score_timeline.py` (Default `2`): Ein
  Stand zählt erst, wenn er ≥ N Frames steht. Steht eine Tafel nur sehr kurz,
  kann `1` helfen — erhöht aber das Risiko von Fehllesungen.

Nach jeder Änderung Abschnitt 3 laufen lassen und gelesene vs. echte Tore
vergleichen.

---

## 6. Skin-Erkennung prüfen

Wird der falsche Skin gewählt, passen Regionen und Templates nicht und kaum
etwas wird erkannt. Beim Lauf gibt `make_highlights` das erkannte Profil samt
Konfidenz aus. Sitzt das daneben, Skin per `--hud <profil>` erzwingen (Abschnitt
1) und prüfen, ob die Erkennung dann stimmt — dann liegt es an der Skin-Erkennung
(`detect_skin.py` / `hud_ref.png`), nicht an den Ziffern.

---

## 7. Schützenerkennung evaluieren (optionale Stufe 2)

Die KI-gestützte Schützenerkennung (`detect_scorer.py`) ist ein Gerüst und noch
nicht in `make_highlights` verdrahtet — bewusst erst messen, dann entscheiden.
So misst du die Trefferquote an echtem Material gegen Wahrheits-Labels:

```bash
# labels.json: je Tor ein Eintrag, Zuordnung über den Stand (siehe labels_example.json)
ANTHROPIC_API_KEY=... \
venv/bin/python src/detect_scorer.py eval videos/bl-test-1.mov \
  goals_bl-test-1.json labels.json
```

Label-Format (`labels_example.json`):

```json
[
  { "score": "1:0", "scorer_color": "red",  "assist_color": "blue" },
  { "score": "2:1", "scorer_color": "unknown", "assist_color": "none" }
]
```

Die Ausgabe zeigt die Gesamt-Trefferquote und — wichtiger — die Quote bei hoher
Konfidenz (`SCORER_CONF`, Default 0.8). Das ist die Hybrid-Kennzahl: hohe
Konfidenz automatisch übernehmen, den Rest dem App-Tap / Review überlassen.
Modell über `SCORER_MODEL` wählbar.

---

## 8. Anker-Modus — Tore ohne Ziffern-Lesen verankern (`build_anchor_timeline.py`)

Der Ziffern-Ansatz beantwortet zwei Fragen auf einmal: „Ist ein Tor gefallen?"
und „Wo im Video?". Der Anker-Modus trennt das: WAS gefallen ist, liefert die
App-Timeline (Taps; Seite + Minute je Tor — autoritativ). WO die Tore liegen,
verraten die Anstoß-Tafeln — und die müssen nur ERKANNT werden, nicht gelesen:

1. Selbstkalibrierung: Das Spiel beginnt 0:0; die vorhandenen Ziffern-Templates
   finden die Anstoß-Tafel (nur die „0" wird gebraucht). Von dort croppt sich
   das Skript die linke Team-Box als spiel-eigenen Anker — konstant, egal wie
   hoch der Stand steigt, egal welche Teams spielen.
2. Tafel-Präsenz: Der Anker wird über alle Frames gematcht (Tafeln ≥0.99,
   Live-Bild ≤0.35 — sauber trennbar bei Schwelle 0.7).
3. Zuordnung primär über die REIHENFOLGE (Tore und Tafeln sind beide
   chronologisch). Die Tafel-Minute (OCR der Schützenzeile, Rezept je Skin aus
   dem HUD-Profil + Roh-Graustufen-Fallback) dient als Filter und Validierung:
   Halbzeit-Tafeln zeigen in allen drei Skins die bisherigen Schützen — ihre
   Minute WIEDERHOLT eine frühere Tafel und fliegt darüber raus. Wichtig: Die
   App-TAP-Minuten weichen real bis zu ~9 Minuten von den Tafel-Minuten ab
   (premier: Tap 28' vs. Tafel 36'), darum ist die Minute bewusst NICHT das
   primäre Zuordnungssignal; der Report zeigt die Abweichung je Tor.

```bash
# Frames müssen extrahiert sein (make_highlights-Lauf oder Abschnitt 3),
# die Torliste im App-Format daneben liegen (app_<base>.json):
FRAMES_DIR=frames_bl-11-10 FPS=2 \
APP_TIMELINE=fixtures/app_bl-11-10.json \
GOALS_OUT=goals_anchor_bl-11-10.json \
venv/bin/python src/build_anchor_timeline.py

# Ergebnis ist cut_highlights-kompatibel (inkl. scorer/assist fürs Banner):
HL_INPUT=videos/bl-11-10.mov GOALS_IN=goals_anchor_bl-11-10.json \
HL_OUTDIR=highlights_bl-11-10-anchor venv/bin/python src/cut_highlights.py
```

Tunebar per Env: `BOARD_THRESHOLD` (0.7), `MINUTE_TOLERANCE` (10 — Spielraum
für die Tap-Abweichung; wird nur fürs Aussortieren von Überschuss-Tafeln und
Warnungen genutzt), `BOARDS_OUT` (Debug-Liste aller erkannten Tafeln).

Kalibriert und validiert sind ALLE drei Skins (`BOARD_CALIB` im Skript):
bundesliga 21/21 (bl-11-10), premier 6/6 (premier-league-4-2, Tap-Abweichung
bis +9), cross_nation 4/4 (cross-3-1). Skin-Eigenheiten, die das Skript
abdeckt: Premier-Tafeln ANIMIEREN (~1,5 s — Schützenzeile erst ab Blockmitte),
beim Cross-Skin verschwindet das Schützenfoto samt Minute VOR dem Bandende
(darum verteilte OCR-Samples über den ganzen Block), und die Cross-Minutenbox
(weiß auf grün) liest nur roh in Graustufen, nicht binarisiert.

Im OFFICE-BETRIEB passiert das alles automatisch: `process_highlights` holt
die Torliste von der API (`GET /recording/timeline`) und legt sie als
`app_<base>.json` ab; `make_highlights` springt dann von selbst in den
Anker-Modus. `ANCHOR_MODE=off` erzwingt die klassische Ziffern-Erkennung,
und bei Anker-Fehlern (z. B. 0:0-Tafel nicht gefunden) fällt `make_highlights`
automatisch auf sie zurück.

Grenzen: kein Elfmeterschießen (die Pipeline warnt bei `result_type=penalty`),
`goalMoment` bleibt leer (die HUD-Referenz ist team-spezifisch — bekannte
Baustelle), und ohne App-Timeline läuft die klassische Erkennung.

## 9. Welches Material hilft am meisten?

- Hochstehende Spiele je Skin (4:3, 5:2 …) — sie liefern genau die fehlenden
  Ziffern 3–9. Ein Spiel pro Skin, das jede Ziffer einmal auf der Tafel zeigt,
  schließt die Abdeckung (Abschnitt 4).
- Spiele in allen drei Skins (Bundesliga, Premier, Cross-Nation), damit kein
  Profil zurückfällt.
- Für die Schützen-Eval (Abschnitt 7): ~10 Spiele / 30–50 Tore mit Labels. Tipp:
  Die manuellen App-Taps SIND die Wahrheit — im Normalbetrieb fällt der Eval-Satz
  gratis ab.

---

## Datei-Referenz

| Datei | Rolle |
|-------|-------|
| `make_highlights.py` | Orchestrator: Frames → Skin → Stand/Tore → Schnitt → Reel |
| `build_score_timeline.py` | Stand-/Tor-Erkennung (per Env parametrierbar, Abschnitt 3) |
| `build_anchor_timeline.py` | Anker-Modus: Tafel-Präsenz + App-Torliste statt Ziffern (Abschnitt 8) |
| `hud_profiles.py` | Pro Skin: Regionen, Templates, Schwellwerte (Abschnitt 5) |
| `build_templates*.py` | Ziffern-Templates aus `samples/` erzeugen + validieren (Abschnitt 4) |
| `detect_skin.py` | Skin-Erkennung per HUD-Abgleich (Abschnitt 6) |
| `detect_scorer.py` | Schützen-Eval gegen Labels (Abschnitt 7) |
| `samples/` | Eingecheckte Tafel-Samples, Quelle der Templates |
| `templates/<skin>/` | Erzeugte Ziffern-Glyphen + HUD-Referenzen |
