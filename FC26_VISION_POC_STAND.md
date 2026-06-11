# FC26 Vision-Experiment — Arbeitsstand & Übergabe

> **Was das ist:** Lern-/Experimentier-Projekt zur Computer-Vision-Pipeline
>   für FC26-Spielaufnahmen. Dieses Dokument hält den **tatsächlich
>   erreichten Stand** fest (Stand: vierte Hands-on-Session) und dient als
>   Einstieg für die Fortsetzung in einer neuen Session.
> **Ort:** `~/Projects/fc26-vision-poc/` (lokal auf dem MacBook)
> **Hardware:** Billige HDMI-Capture-Box (OEM, ~20€), funktioniert. HDCP
>   war kein Problem (Box strippt intern). Aufnahme via QuickTime als .mov.

---

## 0. Scope-Disziplin — bitte zuerst lesen

Dieses Projekt hat eine **strikte Leitplanke**:

**IM SCOPE (lesbare Tafeln an festen Positionen — funktioniert):**
- Spieluhr im laufenden Spiel auslesen ✅ erreicht
- Spielstand von der Anstoß-Tafel auslesen ✅ erreicht
- Minute von der Anstoß-Tafel auslesen ✅ erreicht

**BEWUSST NICHT IM SCOPE (das schwere, fragile Problem):**
- Erkennen im laufenden Spielgeschehen, WER schießt (Controller-Farben,
  Spieler-Tracking, Ball-Position)
- Tor-Erkennung im Live-Bild (statt über die Anstoß-Tafel)
- Workflow-Ersatz für die manuelle Eingabe

**Warum die Grenze hält:** Alles im Scope sind **statische, klar lesbare
Einblendungen** — feste Position, große Ziffern, hoher Kontrast. Das ist
zuverlässig lösbar (heute bewiesen). Das Live-Spielgeschehen zu
interpretieren ist ein offenes, jährlich (FC-Update) brechendes
Forschungsproblem und bleibt außen vor. Wenn der Gedanke kommt "und jetzt
auch erkennen wer geschossen hat" → innehalten, das ist die Grenze.

**Der Schütze kommt aus den App-Taps**, nicht aus Vision. Die Vision
liefert Minute + Spielstand (leichte Ziffern), das WER tippt ihr wie
gehabt manuell ein.

---

## 1. Erreichter Stand

### Erste Session — drei OCR-Bausteine

Von "Box ausgepackt" bis zu drei funktionierenden OCR-Bausteinen:

| Baustein | Quelle im Bild | Ergebnis | Status |
|---|---|---|---|
| **Spieluhr** | HUD oben links (laufendes Spiel) | `27:04` | ✅ über ganze Halbzeit fehlerfrei |
| **Spielstand** | Anstoß-Tafel unten mittig | `1:0` | ✅ über ganze Halbzeit (Score-Timeline) |
| **Minute** | Anstoß-Tafel oben (nach Schützenname) | `4'` | ✅ über ganze Halbzeit (Score-Timeline) |

**Trefferquote Spieluhr** über die ganze Halbzeit: 304 von 366 Frames
(83%). Die fehlenden 17% sind legitime Nicht-Uhr-Phasen (Mannschaftsauswahl,
Einlauf, Halbzeitscreen, Jubel/Wiederholungen) — keine Lesefehler. In
Frames mit sichtbarer Uhr war die Erkennung praktisch fehlerfrei.

**Wichtige Erkenntnis:** Spielstand und Minute werden nach JEDEM Tor auf
der Anstoß-Tafel eingeblendet. Damit ist die Tafel ein zuverlässiges
Tor-Signal (dass + wann + Spielstand), ohne das schwere Live-Geschehen
analysieren zu müssen. Das war der Schlüssel-Fund der ersten Session.

### Zweite Session — Score-Timeline, Tor-Erkennung, Highlight-Schnitt

Die Anstoß-Tafel-Bausteine zur durchgehenden Pipeline ausgebaut und die
Kette einmal komplett auf echtem Material durchgespielt:

| Baustein | Ergebnis | Status |
|---|---|---|
| **Score-Timeline** | Spielstand über alle 366 Frames → `score_timeline.json` | ✅ |
| **Tor-Erkennung** | genau 1 Tor: `1:0`, Minute `4'`, Video-Sek 43 → `goals.json` | ✅ |
| **Highlight-Clip** | `[Sek 18..48]` aus dem `.mov`, Einblendung `4'  1:0` | ✅ |

**Validierung des Tor-Triggers (das eigentliche Ergebnis von Schritt A):**
In der Halbzeit gibt es genau ein Tor — die Pipeline fand genau dieses eine
(`1:0` bei Video-Sek 43, Spielminute 4'). Die Uhr-Lücke bei Video-Sek
221–239 (Spielminute ~31') war eine **gelbe Karte** (Julian Ryerson,
Dortmund) mit Cutscene/Wiederholung — und erzeugte korrekt **keinen**
Fehlalarm. Grund: Ein Tor zählt nur, wenn sich der bestätigte Spielstand
erhöht. Damit ist bewiesen, dass sich die Tor-Anstoß-Tafel (unten mittig)
von anderen Einblendungen (gelbe Karte unten links, persistentes
Score-HUD oben) sauber trennen lässt.

**Robustheits-Trick:** Eine Tafel-Lesung zählt erst, wenn derselbe Stand in
≥2 aufeinanderfolgenden 1-fps-Frames steht (`MIN_STABLE = 2`). Das filtert
einzelne OCR-Ausreißer aus dem Live-Bild. Über die ganze Halbzeit ergaben
nur die 4 echten Tafel-Frames (Sek 43–46) einen bestätigten Stand — null
Fehltreffer.

### Dritte Session — Multi-Skin (Premier-League-Profil)

HUD-Profile eingeführt (`hud_profiles.py`), um verschiedene Liga-Skins zu
unterstützen. Premier-League vollständig kalibriert und über ein ganzes
4:2-Spiel validiert:

| Baustein | Methode | Status |
|---|---|---|
| **Score** (6 Tore) | Template-Abgleich (OCR scheiterte am kontrastarmen Heim-Digit) | ✅ 6/6 |
| **Minute** (6 Tore) | Zeilen-Scan der Schützen-Tafel, letzte Zahl, beide Seiten | ✅ 6/6 |
| **fps-Fix** | `videoSecond = Frame-Index / fps` → korrekte Schnittzeiten | ✅ |

Profil wird automatisch aus dem Bild erkannt (`detect_skin.py`, `--hud`
übersteuert). Technische Details in Schritt 9/10; offene Punkte in Abschnitt 5 E.

### Vierte Session — Branding, Wiederholung, 60fps, Elfmeterschießen

Die Pipeline rund gemacht und um Sonderfälle erweitert:

| Baustein | Ergebnis | Status |
|---|---|---|
| **Intro/Outro + Crossfades** | Splash/Abspann je Tor-Clip UND Reel (`intro.png`/`outro.png`, `xfade`) | ✅ Schritt 8b |
| **Wiederholungs-Erkennung** | adaptiver Clip-Start am Tor-Moment (HUD-Lücke), Extra-Vorlauf bei Replay | ✅ Schritt 6b |
| **60fps (OBS)** | Intro/Outro in Clip-fps erzeugt → Crossfades passen | ✅ |
| **Bundesliga-HUD** | `hud_ref` kalibriert → Wiederholungs-Erkennung jetzt auch Bundesliga | ✅ |
| **Elfmeterschießen** | langer HUD-weg-Block am Spielende → eigener Clip mit Label | ✅ Schritt 6c (cv2-validiert) |
| **Gast-Tore Bundesliga** | Score + `scoredBy` beidseitig; Gast-Minute jetzt per Zeilen-Scan (line) kalibriert | ✅ Schritt 6/9 |
| **Stand per Template (Bundesliga)** | dash-OCR verlor das 2:0 UND erzeugte Phantom-Stände (Tor mis-attribuiert) → Umstieg auf Template-Abgleich, ganzes Spiel cv2-validiert (4 Tore, 0 Falsch-Positive) | ✅ Schritt 9 |

---

## 2. Umgebung (verifiziert lauffähig)

```
ffmpeg   8.1.1
tesseract 5.5.2
Python   3.13.13  (venv unter ~/Projects/fc26-vision-poc/venv)
Pakete:  opencv-python, pytesseract, numpy
```

Aktivieren:
```bash
cd ~/Projects/fc26-vision-poc
source venv/bin/activate
```

---

## 3. Die funktionierende Pipeline

### Schritt 1 — Frames extrahieren

```bash
mkdir -p frames
ffmpeg -i erste-halbzeit.mov -vf "fps=1" frames/frame_%05d.png
```

1 Frame pro Sekunde. Bei einer Halbzeit ~366 Frames.

**Hinweis für später:** Für die Anstoß-Tafel (erscheint nur wenige
Sekunden) reicht 1 fps evtl. nicht — dann dichter sampeln (2–3 fps) oder
gezielt die Sekunden um einen Spielstand-Wechsel abtasten.

### Schritt 2 — Die drei Regionen (EXAKTE, getestete Werte)

Bei Full-HD (1920×1080). Alle drei nutzen dieselbe Vorverarbeitung:
Graustufen → 4× hochskalieren → **invertierter** Otsu-Threshold
(`THRESH_BINARY_INV`, weil helle Schrift auf dunklem Grund).

```python
# Spieluhr (laufendes Spiel, HUD oben links)
CLOCK_REGION  = (110, 55, 74, 30)   # x, y, w, h

# Spielstand (Anstoß-Tafel, unten mittig)
SCORE_REGION  = (900, 925, 120, 50)

# Minute (Anstoß-Tafel, nach dem Schützennamen) — SEITENABHÄNGIG:
# Heim-Tor links (verifiziert), Gast-Tor gespiegelt rechts (noch zu kalibrieren)
MINUTE_REGION_HOME = (860, 875, 40, 40)
MINUTE_REGION_AWAY = (1020, 875, 40, 40)  # Schätzung 1920−x−w, am Gast-Tor nachmessen
```

**Diese Werte sind manuell ausgemessen und haben funktioniert** — ABER nur
für den Bundesliga-Club-vs-Club-Skin. Andere Wettbewerbe haben ein anderes
HUD-Layout: Premier-League-Club vs Club und der generische Cross-Nation-Skin
sitzen anders. Die Regionen sind also skin-spezifisch.

**Umgesetzt: HUD-Profile** (`hud_profiles.py`, siehe Schritt 9) — die obigen
Werte sind das Bundesliga-Profil. Ein Profil pro Skin (`bundesliga`, `premier`,
`cross_nation`) mit eigenen Regionen (und ggf. Threshold/Whitelist, falls der
Stil abweicht). Die Pipeline wählt das Profil per Parameter/Dateiname;
Tor-Erkennung, Schnitt und Reel bleiben identisch. Pro neuem Skin einmalig die
Regionen ausmessen (großzügig zuschneiden, dann verkleinern bis nur die Ziffern
drin sind). Prüfen, ob jeder Skin die Tor-Anstoß-Tafel hat — sonst fürs
Tor-Signal auf den dauerhaften Score-Bug oben ausweichen.

### Schritt 3 — OCR-Parameter (getestet)

```python
# Vorverarbeitung (für alle drei gleich)
gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
_, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

# OCR
# Spieluhr: Ziffern + Doppelpunkt
config_clock  = "--psm 7 -c tessedit_char_whitelist=0123456789:"
# Spielstand:  Ziffern + Minus
config_score  = "--psm 7 -c tessedit_char_whitelist=0123456789-"
# Minute: NUR Ziffern (KEIN Apostroph in der Whitelist!)
config_minute = "--psm 7 -c tessedit_char_whitelist=0123456789"
```

**Stolperstein dokumentiert:** Der Apostroph `'` in der Whitelist bringt
den Shell-Parser von pytesseract zum Absturz ("No closing quotation").
Lösung: Apostroph weglassen, Ziffer per Regex `\d+` rausfiltern. Gleiche
Regel für alle Sonderzeichen — nur Nötiges in die Whitelist, Rest per
Regex filtern.

### Schritt 4 — Timeline über das ganze Video

`build_timeline.py` läuft über alle Frames, liest die Spieluhr und
schreibt `timeline.json` (Liste: videoSecond, frame, clock). Gibt
Trefferquote aus.

**Spieltempo-Beobachtung:** Die Spielzeit läuft ~11 Spielsekunden pro
Echtzeitsekunde (z.B. `01:48 → 01:59 → 02:10` bei aufeinanderfolgenden
Frames). Wichtig für die Glättung und die spätere Wall-Clock-Brücke.

### Schritt 5 — Glättung (Sicherheitsnetz)

`smooth_timeline.py` verwirft unplausible Werte. Die Spieluhr läuft nur
vorwärts in kleinen Schritten — Ausreißer (z.B. `92:10` zwischen `01:59`
und `02:22`) fliegen raus.

Parameter (getestet):
```python
MAX_FORWARD_JUMP = 25   # max. plausibler Vorwärtssprung der Spielzeit (Sek)
MAX_BACKWARD = 2        # kleine Rückwärts-Toleranz für OCR-Wackler
GAP_RESET = 3           # nach 3x None in Folge: Kontext-Neustart (neuer Abschnitt)
```

**Wichtige Logik-Lektion (Bug, der gefixt wurde):** `last_valid` darf NUR
bei akzeptierten Werten aktualisiert werden, sonst reißt ein einzelner
Ausreißer die ganze folgende Kette ab (erst alles als "Sprung" verworfen).
Und nach einer längeren None-Lücke muss der Kontext zurückgesetzt werden,
damit ein neuer Spielabschnitt sauber wieder einsteigt. Bei der sauberen
Test-Halbzeit war am Ende 0 Ausreißer nötig — die Glättung ist reine
Absicherung für schwierigere Spiele.

### Schritt 6 — Tor-Erkennung (Score-Timeline)

`build_score_timeline.py` liest den Spielstand (Region unten) über alle
Frames und leitet daraus Tor-Events ab. Drei Robustheits-Regeln:

- **Tafel-Muster verlangen:** Der `dash`-OCR-Modus verlangt `Ziffer - Ziffer`
  (Regex `(\d)\s*-\s*(\d)`). **Für Bundesliga reichte OCR aber nicht** — der
  Stand läuft dort jetzt über Template-Abgleich (Schritt 9, „Bundesliga-Lektion").
  Lehre nebenbei: ein verlorenes Zwischen-Tor verfälscht auch die Folge-Seite
  (1:0 → 2:0 verpasst → 2:1 wurde als Heim- statt Gast-Tor gewertet) — ein
  Grund mehr, beim Stand auf zuverlässige Erkennung statt OCR-Glück zu setzen.
- **Stabilität:** `MIN_STABLE = 2` — derselbe Stand muss in ≥2
  aufeinanderfolgenden Frames stehen. Einzelne OCR-Ausreißer fliegen raus.
- **Tor = Stand erhöht sich** (Summe Heim+Gast steigt gegenüber dem vorigen
  bestätigten Stand). So lösen wiederholte Tafeln und andere Einblendungen
  (gelbe Karte, Statistik) nichts aus.

Die Minute wird über die GANZE Tafel-Phase gelesen und der häufigste Wert
genommen. **Stolperstein:** Nur den ersten Tafel-Frame zu lesen ergibt oft
`None` — die Tafel fadet ein, die Minute steht erst, wenn der Schützenname
da ist. Mehrheit über die Phase ist robust.

**Seitenabhängige Minute (wichtig für Gast-Tore):** Bei einem GAST-Tor steht
der Schütze samt Minute auf der anderen Tafel-Seite (Heim links, Gast rechts).
Welche Seite getroffen hat, liefert die Spielstand-Änderung (`scoredBy`) —
daraus wählt das Skript die Heim- bzw. Gast-Region. Die Tor-Erkennung und der
Spielstand funktionieren für beide Seiten unverändert (der zentrale `H - A`-
Score steht symmetrisch in der Mitte). **Bundesliga-Minute jetzt per
Zeilen-Scan (mode "line"), wie Premier:** die Minute ist die LETZTE Zahl der
Schützen-Zeile „NAME MM'", ihre X-Position hängt von der Namenslänge ab. Die
Zeile ist rechtsbündig (Heim endet ~x940, Gast ~x1255). An echten Frames
kalibriert + thresh-geprüft: MUSIALA 34', TAH 53' (Heim); MILOŠEVIĆ 55',
MBANGULA 75' (Gast). Damit ist die frühere Gast-Spiegelungs-Schätzung ersetzt.

Output: `score_timeline.json` (pro Frame) und `goals.json` (Tor-Events mit
`videoSecond`, `score`, `minute`, `scoredBy`).

### Schritt 6b — Wiederholungs-Erkennung (adaptiver Clip-Start)

Problem: Läuft nach einem Tor die automatische Wiederholung, steht die
Anstoß-Tafel viel später — ein fester Vorlauf erwischt dann nur das Ende der
Wiederholung, nicht das Tor. Ein global größerer Vorlauf zeigt bei den ~80%
Toren OHNE Wiederholung zu viel Spiel davor.

Signal: Während Jubel/Wiederholung ist das Live-HUD (Uhr/Score-Bug oben links)
WEG; im laufenden Spiel ist es da. Pro Frame wird die HUD-Präsenz per
Template-Abgleich der HUD-Region gegen eine Live-Referenz geprüft (`hud`-Konfig
im Profil: `region` + `ref` + `threshold`; reines cv2, kein OCR).

Lösung: Pro Tor ist `goalMoment` = letzter Frame mit Live-HUD VOR der Lücke
(Jubel/Wiederholung), die zur Tafel führt — also der Tor-Moment, egal wie lang
die Wiederholung lief. Der Schnitt startet `BUILDUP_BEFORE_GOAL` Sekunden davor
(`cut_highlights.py`). Passt sich automatisch an: kurze Lücke → kein
Extra-Vorlauf; lange Wiederholung → Start wandert bis zum Tor zurück
(Spielszene + Wiederholung sind drin). Fallback auf festen `PRE`, wenn das
Profil keine `hud`-Konfig hat.

Extra-Vorlauf bei Wiederholung: War eine Wiederholung zu sehen (große Lücke
Tor-Moment..Tafel > `REPLAY_GAP_THRESHOLD`), bekommt der Clip `REPLAY_EXTRA`
Sekunden zusätzlichen Vorlauf — sonst frisst der Jubel den kurzen Vorlauf und
die Spielszene ist nur knapp zu sehen. Nicht-Wiederholungs-Tore bleiben
unverändert. (cut_highlights.py)

Kalibriert für premier, cross_nation **und bundesliga**. HUD-Referenz =
Graustufen-Crop der HUD-Region aus einem Live-Frame, in
`templates/<skin>/hud_ref.png` (Bundesliga: „BAY"/„SVW"-Team-Boxen aus
`bl_sample_play.png`). Validiert: Premier-1:0, Tafel 236s → Tor-Moment 225,5s
(HUD-Lücke 226–241s sauber erkannt).

### Schritt 6c — Elfmeterschießen-Erkennung

Bei Unentschieden nach Spielende kommt ein Elfmeterschießen. Wie es sich erkennen
lässt, hängt vom Skin ab — darum hat `shootout` ein Feld `mode` (reines cv2, kein
OCR). Das Event wird einheitlich als `{"type":"shootout","clipStart","clipEnd",
"label"}` an `goals.json` angehängt; `cut_highlights.py` schneidet diesen einen
Clip mit schlichtem Label-Banner („Elfmeterschießen", `render_label_overlay`) —
kein Stand, keine Minute. Er läuft als ganz normaler `tor_NN_*`-Clip ins Reel
(Branding/Crossfades inklusive, da er auf das Namensmuster matcht).

Modus `hud_gap` (Bundesliga): Oben links, wo sonst die Spieluhr steht, stehen
jetzt die Schützen-Icons („−", 5 pro Seite + je 1 pro Block). Das normale opake
Spiel-HUD ist also die GANZE Dauer weg → das Schießen ist der lange HUD-weg-Block
am Spielende (`hud_present` == False). End-Screens danach haben keine grüne Wiese
→ über `green_present` (Anteil grüner Pixel ≥ `green_min`) abgeschnitten. Konfig:
`green_region`, `green_min`, `min_length`, `label`. Validiert (cv2,
`bundesliga-2-2-5_3.mov`): HUD-weg-Block 714–864s → Grün-Trim → Clip 714–831s.

Modus `label` (cross_nation): Beim cross-Skin bleibt während des Schießens ein
HUD stehen (V-Logo + Penalty-Stand + „ELFMETER"), das das normale HUD noch
teilweise matcht (~0.62 > Schwelle) → der HUD-weg-Ansatz greift NICHT. Stattdessen
die UNTERE HUD-Zeile prüfen: dort steht im Spiel die Uhr („36:21"), im Schießen
„ELFMETER" — per Template-Abgleich erkannt (`label_region`, `label_ref`,
`label_threshold` 0.7; `elfmeter_ref.png`). Der Block reicht vom ersten
ELFMETER-Frame bis zum letzten grünen-Wiese-Frame (Sieger-Jubel, HUD dann weg),
bevor die End-Screens kommen. Konfig zusätzlich: `green_region`/`green_min` (für
das Jubel-Ende), `min_length`, `label`. Validiert (cv2, `2026-06-08 17-40-48.mov`,
LOM vs MCI 2:2): ELFMETER 614–744s, per Jubel-Grün bis 760s → Clip 614–760s
(146s). Gleicher Lauf: die 4 Tore (1:0, 1:1, 2:1, 2:2) korrekt erkannt.

**Achtung Profilwahl:** Dieses Video heißt nach OBS-Schema `2026-06-08 17-40-48.mov`
(kein Skin-Stichwort) → `make_highlights.py` würde auf bundesliga defaulten. Für
cross-Spiele also `--hud cross_nation` mitgeben (oder die Datei mit „cross"/
„nation"/„normal" im Namen ablegen).

**Template-Lektion (Ziffern-Verwechslung, positionsabhängige Glyphen):** Bei
`cross-3-1.mov` fehlte erst die „3" (cross_nation hatte nur 0–2) → das 3:1-Board
las sich als „2:1". Nach dem Nachziehen der „3" kippte das ANSTOSS-Board (0:0):
das Heim-„0" matchte „3" (0.65) knapp vor „0" (0.63), weil das Heim-„0" (steht
nur beim Anstoß) vom Gast-„0"-Glyph nur schwach getroffen wird. Ein als hoher
Stand verlesenes Board vergiftet die ganze Tor-Folge (prev springt zu hoch,
echte Tore fallen durch den Monoton-Check) — dieselbe Klasse Fehler wie der
Bundesliga-Phantom-„2:4". Lehre: (1) fehlende Ziffer = fehlendes Tor, früh
gegenprüfen; (2) wenn zwei Ziffern an EINER Position verwechselbar sind, einen
positionsspezifischen Glyph nehmen (hier: eigenes Heim-„0" aus dem Anstoß-Board),
statt an einer globalen Schwelle zu drehen (die hätte echte Boards mitgerissen);
(3) die ganze Erkennung über das GANZE Spiel in cv2 gegenprüfen (Score braucht
kein OCR) — fängt solche Verwechslungen vor dem Nutzer-Lauf ab.

### Schritt 7 — Highlight-Schnitt

`cut_highlights.py` schneidet pro Tor `[Tafel-Sek − PRE, + POST]` aus dem
`.mov` (Default `PRE = 25`, `POST = 5`) und blendet `Minute  Stand` ein.

- **Vorlauf großzügig**, weil die Tafel dem Tor NACHLÄUFT (Tor → Jubel →
  Tafel; in der Testhalbzeit Tor ~Sek 33–36, Tafel erst Sek 43). PRE/POST
  oben im Skript justierbar.
- **Stolperstein dokumentiert:** `drawtext` braucht libfreetype und fehlt in
  manchen ffmpeg-Builds ("No such filter: 'drawtext'"). Lösung: Einblendung
  als Banner-PNG mit cv2 zeichnen (BGRA, halbtransparente Box Alpha 150 +
  weiße Schrift Alpha 255) und mit dem `overlay`-Filter einblenden —
  `overlay` ist im Standard-ffmpeg immer dabei. Das Skript fällt bei einem
  Filter-Fehler automatisch auf "Schnitt ohne Einblendung" zurück.

**Eigene Grafik-Vorlage (`overlay_template.png`):** Liegt eine 1920×1080-RGBA-PNG
mit diesem Namen vor (transparenter Hintergrund, Grafik dort platziert, wo sie
auf dem Bild sein soll), wird sie als Lower-Third eingeblendet und Minute + Stand
mit Pillow (scharfe TrueType-Schrift) an konfigurierbaren Stellen (`TEXT_FIELDS`
in `cut_highlights.py`) daraufgezeichnet. Ohne Vorlage → cv2-Banner (s.o.).
`make_overlay_template.py` erzeugt eine Beispiel-Vorlage. Das Feld `scorer` ist
für den App-Tap-Namen bereits vorgesehen. Die Einblendung wird am Clip-Anfang
ein- und nach ein paar Sekunden wieder ausgeblendet (Fade auf dem Alpha-Kanal;
Zeiten `BANNER_FADE_IN` / `BANNER_HOLD` / `BANNER_FADE_OUT`).

**Encoding:** Clips werden als H.265/HEVC (1080p, crf 28, `-tag:v hvc1`) kodiert
→ ~13 MB/30s statt ~41 MB. Stellschrauben in `cut_highlights.py`:
`VIDEO_CRF` (höher = kleiner), `VIDEO_CODEC` (`libx264` + `VIDEO_EXTRA=[]` für
maximale Kompatibilität). H.265-Clips lassen sich verlustfrei per `concat -c copy`
zum Reel fügen (verifiziert). **Stolperstein:** Overlay/Fade hinterlässt einen
Alpha-Kanal — libx265 kann kein Alpha encodieren ("does not support alpha layer
encoding"). Darum endet die Overlay-Filterkette mit `,format=yuv420p`.

### Schritt 8 — Alles in einem Lauf (Orchestrator)

`make_highlights.py <video>` verkettet die ganze Kette für EIN Spiel:
Frames extrahieren → Tore erkennen → Clips schneiden → zu EINEM Reel
zusammenfügen. Ergebnis: `<name>_highlights.mp4` (ein Reel pro Spiel).

```bash
python make_highlights.py spiel2.mov
```

- `FPS = 2` (oben im Skript): Sampling-Rate fürs Extrahieren. 2 fps ist
  sicherer für kurze Tafeln, 1 fps schneller. Bei 90 min sind 2 fps ~10.000
  Frames → grob 10–20 min OCR-Zeit pro Spiel.
- Die bestehenden Skripte werden über Env-Variablen parametrisiert
  (`FRAMES_DIR`, `GOALS_OUT`, `HL_INPUT`, `GOALS_IN`, `HL_OUTDIR`) — ihre
  Logik bleibt unverändert, der Standalone-Aufruf funktioniert weiter.
- Zwischenartefakte pro Spiel: `frames_<name>/` (löschbar), `goals_<name>.json`,
  `highlights_<name>/` (Einzelclips). Das Reel entsteht per
  `ffmpeg concat -c copy` verlustfrei (alle Clips haben identische
  Codec-Settings — synthetisch verifiziert).

### Schritt 8b — Intro/Outro + Crossfades (optional)

Liegen `intro.png` + `outro.png` (je 1920×1080) vor, bekommt JEDER Tor-Clip UND
das Reel einen Splash am Anfang und einen Abspann am Ende, mit weichen
Übergängen (`xfade` Video + `acrossfade` Audio). Aufbau: Reel = EIN Intro +
alle Tore + EIN Outro (Crossfades dazwischen); Einzel-Clips = Intro + Tor +
Outro. Stellschrauben in `make_highlights.py`: `INTRO_DUR` / `OUTRO_DUR` /
`XFADE`. **Achtung:** mit Crossfades wird das Reel neu encodiert (kein
verlustfreies `-c copy` mehr) — der Schnitt-Schritt dauert dadurch länger.
Ohne die zwei Bilder läuft alles wie gehabt (Einzel-Clips ohne Branding,
Reel per `-c copy`). Intro/Outro werden in der fps der Tor-Clips erzeugt
(z.B. 60fps bei OBS-Aufnahmen), damit die Crossfades passen.

### Schritt 9 — HUD-Profile (Multi-Skin)

Jeder Wettbewerb rendert die Tafeln anders. `hud_profiles.py` haelt pro Skin
die Regionen + Lese-Methoden; Detektion/Schnitt/Reel bleiben gleich. Das Profil
wird AUTOMATISCH AUS DEM BILD bestimmt (`detect_skin.py`, Schritt 10) — keine
manuelle Wettbewerbs-Auswahl, kein Dateiname noetig. `--hud <profil>`
uebersteuert weiterhin. `build_score_timeline.py` liest das Profil aus der
Env-Variable `HUD_PROFILE`.

Region-Tupel: `(x, y, w, h, method, psm)`. Methoden:
- `otsu_inv` — helle Schrift auf dunkel (Bundesliga).
- `otsu` — dunkle Schrift auf hell (Premier home/minute).
- `white` — nur weisse Pixel behalten (alle 3 Kanaele > 150); noetig, wenn die
  weisse Ziffer in gemischten Hintergrund (Rasen) ragt und Otsu den Ring zu "U"
  oeffnen wuerde.

Score-Modi: `dash` (eine OCR-Region "H - A") vs `template` (zwei Einzelziffer-
Regionen per Glyph-Abgleich). Alle drei kalibrierten Skins nutzen inzwischen
`template` (Premier, cross_nation und — nach den OCR-Reinfällen — auch
Bundesliga). `dash` bleibt nur als Fallback-Pfad für etwaige künftige Skins.

**Premier-Lektionen (hart erarbeitet):**
- **Score-Ziffern: OCR war zu unzuverlaessig** — die Heim-Ziffer ist hell auf
  hellem Chevron (niedriger Kontrast), Tesseract verliest sie (0→1, 4→7) und
  eine ISOLIERTE "0" liest es gar nicht. **Loesung: Template-Abgleich**
  (`build_templates.py` schneidet Referenz-Ziffern nach `templates/premier/`;
  `read_score` matcht sie in Graustufen, kontrast-normalisiert, `TM_CCOEFF_NORMED`,
  Schwelle 0.5). Score-Mode im Profil: `template`. Ergebnis: 6/6 Tore korrekt
  (score-only validiert). Live-Frames korrelieren <0.3 → keine Falsch-Positive.
- **Minute (OCR, Zeilen-Scan):** steht je nach NAMENSLAENGE an anderer
  X-Position und je nach Tor-Seite links (Heim) bzw. rechts (Gast). Loesung:
  die ganze Schuetzen-Zeile "NAME (...) MM'" breit scannen, OHNE Whitelist
  (Name bleibt Text), und die LETZTE Zahl nehmen (minute mode "line", Regionen
  home + away). 6/6 Minuten korrekt — auch "TROSSARD 90'" und "ZUBIMENDI (ET) 72'".
- Merksatz: Fuer grosse, feste, kontrastarme UI-Ziffern ist Template-Abgleich
  das richtige Werkzeug, nicht OCR. Fuer eine Zahl in variabler Textzeile:
  ganze Zeile lesen, letzte Zahl nehmen.

**Bundesliga-Lektion (gleiche Erkenntnis, anderer Skin):** Der Stand „H - A"
(helle Ziffern auf dunklem Band) ließ sich per OCR NICHT zuverlässig lesen — in
BEIDE Richtungen daneben: (1) Tesseract ließ den Bindestrich auf einem gestochen
scharfen „2 - 0" oft weg (→ „20"), die strikte Regex verwarf es, das 2:0 ging
verloren (nur 1 von ~8 Tafel-Frames sauber, `MIN_STABLE=2` nie erreicht); (2) im
laufenden Spiel verlas Tesseract Marker-Dreiecke/Ball zu Phantom-Ständen (4:4,
8:8, „2:4"…), und ein „2:4" wurde sogar als Tor bestätigt — das vergiftete die
ganze Folge (alle echten Tore danach scheiterten am Monoton-Check). **Ein
2-Ziffern-Fallback half NICHT** (das 2:0 wurde auch so nur 1× gelesen, und die
Phantom-Stände nahmen zu). Lösung wie Premier: die zwei Einzelziffern (links/
rechts vom Strich) per Template-Abgleich (`build_templates_bundesliga.py`,
Regionen Heim `(931,936,22,24)` / Gast `(967,936,22,24)`, Schwelle 0.5; Ziffern-
Positionen datengetrieben per Spaltenprojektion gemessen). Über das GANZE Spiel
in cv2 validiert: alle Boards korrekt (0:0, 1:0, 2:0, 2:1, 2:2), das 2:0 in
mehreren Frames, NULL Falsch-Positive im laufenden Spiel — Score-Erkennung
braucht damit für Bundesliga gar kein OCR mehr. Templates bisher 0–2 (Maximal-
stand dieses Spiels); 3–9 ergänzen, sobald höhere Stände auftauchen.

### Schritt 10 — Automatische Skin-Erkennung (`detect_skin.py`)

Ziel (Office-/Cloud-Betrieb): keine manuelle Wettbewerbs-Auswahl, kein
Skin-Stichwort im Dateinamen (die heißen `game_<ID>.mov`). Der Skin wird aus
dem Bild bestimmt — rein cv2, kein OCR.

Wie: Jedes Profil hat eine HUD-Referenz an fester Stelle (`hud.region` +
`hud.ref`). Für einen Frame wird JEDES Profil an SEINER Stelle ausgeschnitten und
gegen SEINE Referenz korreliert; das Profil mit dem höchsten Score über seiner
eigenen Schwelle gewinnt den Frame. Über ~20 gleichmäßig verteilte Stichproben-
Frames wird abgestimmt (Mehrheit = Skin). Nicht-Spiel-Frames (Menü/Jubel/
Wiederholung) matchen nirgends und stimmen einfach nicht mit → robust gegen
Ausreißer. None bei unbekanntem Skin → `make_highlights` fällt mit Warnung auf
bundesliga zurück (oder `--hud` angeben).

Validiert über alle fünf Testvideos: bundesliga, cross-3-1, normal-anstoss-2-1,
premier-league-4-2, OBS-Aufnahme (LOM/MCI) — alle korrekt, Konfidenz 1.0, null
Fehlstimmen. In `make_highlights.py` verdrahtet: erst Frames extrahieren, dann
Skin erkennen, dann Tor-Erkennung mit dem erkannten Profil.

---

## 4. Projektstruktur & Skripte

```
fc26-vision-poc/
  make_highlights.py         Orchestrator (1 Video -> Reel)
  detect_skin.py             Auto-Skin-Erkennung (Schritt 10)
  build_score_timeline.py    Tor-Erkennung: Stand (Template) + goalMoment + Schiessen
  cut_highlights.py          Clips schneiden + Lower-Third-Overlay
  merge_scorers.py           App-Namen (Schütze/Vorlage) per Stand-Sequenz mergen
  hud_profiles.py            HUD-Profile/Regionen pro Skin
  build_templates*.py        Score-Ziffern-Templates extrahieren (premier/bundesliga/cross)
  overlay_template.png       Lower-Third-Vorlage (Banner)
  intro.png / outro.png      Branding (Splash/Abspann)
  app_timeline_example.json  App-Export-Beispiel (Merge-Format)
  templates/<skin>/          HUD-Ref + Ziffern-Templates (+ cross: elfmeter_ref)
  samples/                   Kalibrier-Frames (Quellen für die Builder)
  videos/                    Aufnahmen (Quelle)
  archive/                   abgelöste Session-1-Skripte (nur Referenz)
```

Generierte Outputs (`frames_*/`, `goals*.json`, `score_timeline*.json`,
`highlights_*/`, `*_highlights.mp4`) stehen in `.gitignore` und werden bei jedem
Lauf neu erzeugt — jederzeit löschbar.

| Aktives Skript | Zweck |
|---|---|
| `make_highlights.py` | Orchestrator: Video → Frames → Skin → Tore → (Merge) → Clips → Reel |
| `detect_skin.py` | Skin automatisch aus dem Bild (HUD-Abgleich, Mehrheitswahl) |
| `build_score_timeline.py` | Stand (Template) + Tor-Erkennung + `goalMoment` + Elfmeterschießen |
| `cut_highlights.py` | Clips + Overlay (Schütze/Vorlage/Stand/Minute), Label-Banner Schießen |
| `merge_scorers.py` | App-Tore (Schütze/Vorlage) per Stand-Sequenz → `scorer`/`assist` |
| `detect_scorer.py` | GERÜST: Vision-Modell (Sonnet) liest pro Tor die Marker-Farbe des Schützen + Konfidenz; eval-Modus misst Trefferquote gegen Wahrheits-Labels. Braucht `anthropic` + `ANTHROPIC_API_KEY` + Material. Noch NICHT in der Pipeline. |
| `office_agent.py` | GERÜST (Office-Box): pollt die API nach Start/Stop, nimmt per ffmpeg `game_<id>.mov` auf, lädt hoch (Stub), meldet Status zurück. Auth = Shared Secret (X-Agent-Secret, wie Scheduler). Mac-testbar (Testbild + `LOCAL_COMMAND_FILE`); i7 = nur Capture-/Encoder-Zeile tauschen. API-Contract im Datei-Docstring. |
| `hud_profiles.py` | HUD-Profile pro Skin (Regionen, Score/Minute-Methoden, hud-Präsenz, shootout) |
| `build_templates{,_bundesliga,_cross}.py` | Ziffern-Templates extrahieren + validieren (lesen `samples/`, schreiben `templates/`) |

`archive/` enthält die abgelösten Session-1-Skripte (`build_timeline.py`,
`smooth_timeline.py`, `test_*`, `test_premier_board.py`, `make_overlay_template.py`)
— nicht mehr Teil der Pipeline, nur als Referenz aufgehoben.

---

## 5. Nächste Schritte (für die Fortsetzung)

In sinnvoller Reihenfolge, von machbar zu anspruchsvoller:

### A) Anstoß-Tafel über ein ganzes Spiel (teilweise erledigt)
- [x] Erkennt die Pipeline die Tafel zuverlässig? In der Test-Halbzeit ja —
      die 4 Tafel-Frames (Sek 43–46) bei 1 fps reichten. Für **kürzere**
      Tafeln am ganzen Spiel ggf. dichteres Sampling (2–3 fps). Noch offen.
- [x] Tor-Anstoß-Tafel von anderen Einblendungen unterscheidbar? **Ja,
      bewiesen.** Der Score-Change-Trigger ist umgesetzt (`goals.json`); die
      gelbe Karte bei ~31' erzeugte korrekt keinen Fehlalarm.
- [ ] Ein ganzes Spiel aufnehmen (nicht nur Halbzeit) als Testmaterial —
      braucht neue Aufnahme. **Das ist der nächste echte Schritt** (mehrere
      Tore, Auf-/Absteiger der Trefferquote, kürzere Tafeln testen).
- [x] **Gast-Tor-Minute (Bundesliga) kalibriert:** an `bundesliga-2-2-5_3.mov`
      (2:2) erledigt — Minute jetzt per Zeilen-Scan (mode "line", letzte Zahl),
      Heim `(600,880,360,38)` / Gast `(960,880,360,38)`. An MUSIALA 34', TAH 53'
      (Heim) und MILOŠEVIĆ 55', MBANGULA 75' (Gast) gegengeprüft. Die alte
      Spiegelungs-Schätzung `(1020,875,40,40)` ist ersetzt.
- [ ] Re-Lauf bestätigen: `make_highlights.py videos/bundesliga-2-2-5_3.mov`
      sollte jetzt 4 Tore (2:0 dabei, 2:1 als Gast) mit Minuten 34'/53'/55'/75'
      + das Elfmeterschießen liefern.

### B) Score-Timeline bauen — ✅ erledigt
`build_score_timeline.py` liest den Spielstand über alle Frames, bestätigt
stabile Tafeln und schreibt Tor-Events (mit Video-Sekunde, Stand, Minute)
nach `goals.json`. Siehe Schritt 6.

### C) Highlight-Schnitt — ✅ Grundkette erledigt
`cut_highlights.py` schneidet pro Tor-Event einen Clip mit Einblendung
(Schritt 7). **Wichtige Vereinfachung dieser Session:** Für den
Batch-Schnitt aus der Aufnahme liefert die Vision die Video-Sekunde des
Tores DIREKT (von der Tafel) — die Wall-Clock-Brücke wird dafür gar nicht
gebraucht. Offen für ein rundes Gesamtsystem:
- [x] Clips eines Spiels aneinanderhängen → Highlight-Reel: erledigt via
      `make_highlights.py` (Schritt 8), ein Reel pro Spiel.
- [ ] **End-to-End an einem frisch aufgenommenen ganzen Spiel laufen lassen**
      (`python make_highlights.py <spiel>`) — die noch ausstehende echte
      Bewährungsprobe: fängt 2 fps alle Tafeln? mehrere/beidseitige Tore?
- [ ] Vorlauf-Feinschliff: Tafel läuft dem Tor nach; alternativ am
      Uhr-Lücken-Beginn (≈ Tormoment) ankern statt an der Tafel-Sekunde.
- [ ] Housekeeping: `frames_<name>/` nach dem Reel automatisch löschen?
      (siehe D — aktuell bleiben sie liegen)

### C2) App-Merge + Office-/Cloud-Architektur (aktueller Zielpfad)

Die Stats-App liegt in einem EIGENEN Repo (`rasenbuerosport-leipzig-app` +
`-api`, Fastify + Supabase). Sie speichert pro Spiel die volle Tor-Timeline
(`score_timeline`: pro Tor `scored_by`, `assist_by`, laufender Stand, period)
plus das ganze Elfmeterschießen. Arbeitsteilung (vom Nutzer festgelegt — Spieler
sollen minimal tippen):
- Spieler (iPad): nur Torschütze + Vorlagengeber.
- Minute: aus dem Vision-OCR.
- Spielstand: ergibt sich automatisch aus den Taps (Schütze → Team → +1).

Merge (keine Wall-Clock-Sync nötig!): Vision ist Wahrheit für Stand + Minute +
Video-Timing (`goalMoment`), die App liefert die Namen. Verknüpft wird über die
STAND-SEQUENZ (das Tor, das in beiden 2:1 macht). Die Game-ID verbindet
Video↔Spiel-Record. Selbstprüfend: weicht der App-Stand (aus Taps) vom
Vision-Tafel-Stand ab, wurde ein Tap vergessen. Ergebnis füllt das
`scorer`-Feld (im Overlay schon verdrahtet).

Der Merge-Schritt ist GEBAUT: `merge_scorers.py` (Join über die Stand-Sequenz,
Minute-Fallback aus der App wenn OCR `null`, Seiten-Plausibilitätscheck,
optionale Spieler-Map id→Name). An `app_timeline_example.json` (4:2-Spiel)
validiert: 6/6 Tore gemerged, 0 Warnungen. In `make_highlights` optional
eingehängt (Schritt 2b: läuft, wenn `app_<name>.json` oder Env `APP_TIMELINE`
vorliegt). Offen bleibt nur die Spieler-ID→Name-Map (kommt aus der App) und der
Cloud-Klebstoff (Game-ID ↔ Video, Recording-Trigger/Upload).

Office-/Cloud-Setup (Zielbild):
- Raspberry Pi hinter dem Office-Monitor: nimmt auf + lädt hoch. Verbindet sich
  RAUS zur Cloud (pollt/abonniert), setzt die Game-ID in den Dateinamen, lädt
  `game_<ID>.mov` in einen GCS-Bucket. Empfehlung: ffmpeg-Direct-Capture statt
  OBS (leichter headless, leichter zu skripten). RISIKO: 1080p60-Encoding auf
  dem Pi ist grenzwertig — vorher testen, ggf. 1080p30 oder Capture-Gerät mit
  HW-Encode.
- Altes iPad Mini: Webapp fürs Tracking (Skin-/iOS-Version prüfen).
- Cloud: GCS-Upload → Eventarc → Cloud Run JOB (nicht Service: 60-Min-Limit)
  fährt die cv2+OCR-Pipeline → Vision-Tore + Clips/Reel; Merge per Game-ID +
  Stand-Sequenz. Skin wird automatisch erkannt (Schritt 10).
- Schema-Ergänzung nötig: Recording-/Video-Link am Spiel (`recording_id` +
  `video_status`: recording/processing/ready).

**Architektur bleibt Batch** (Highlights nach Spielende); Live-Stats kommen
sofort aus den App-Taps.

### D) Housekeeping-Strategie
Rohvideos sind groß (~1–2 GB pro Spielminute). Lösch-/Archiv-Strategie:
Rohmaterial nach Highlight-Extraktion wegwerfen, nur Clips behalten —
oder große externe SSD, falls als Forschungsmaterial gesammelt.

### E) Weitere HUD-Skins (Multi-Liga)
**Drei Profile kalibriert:** bundesliga, premier, cross_nation.
- Premier (4:2-Spiel): Score 6/6 (Template), Minute 6/6 (Zeilen-Scan, beide Seiten).
- cross_nation/beIN: Score per Template (dunkel-auf-weiss). Ziffern 0–3
  kalibriert; an `normal-anstoss-2-1.mov` (2:1) UND `cross-3-1.mov` (3:1, ganzes
  Spiel cv2-validiert: 4 Tore 1:0/2:0/3:0/3:1, 0 Falsch-Positive) geprüft. Minute
  „MM'" unter dem Schützen-Foto (Heim links, Gast rechts, mode "digit"). Dateiname
  „normal"/„cross"/„nation" → cross_nation. **„0" positionsabhängig:** das
  Heim-„0" (nur beim Anstoß 0:0) wird vom Gast-„0"-Glyph nur schwach getroffen und
  mit „3" verwechselt (das Anstoß-Board las sich sonst als 3:0 und vergiftete die
  Tor-Folge) → eigener Heim-„0"-Glyph aus dem Anstoß-Board. **Elfmeterschießen
  (mode "label", Schritt 6c):** an `2026-06-08 17-40-48.mov` (LOM vs MCI 2:2, ganzes
  Spiel cv2-validiert: 4 Tore + Schießen 614–760s) geprüft — über das „ELFMETER"-
  Label in der HUD-Zeile, weil das cross-Schießen-HUD den HUD-weg-Ansatz austrickst.
- bundesliga (2:2-Spiel `bundesliga-2-2-5_3.mov`): Score „H - A" per
  Template-Abgleich (Ziffern 0–2, ganzes Spiel cv2-validiert, 0 Falsch-Positive),
  Minute per Zeilen-Scan (mode "line", Heim + Gast kalibriert), HUD-Präsenz
  kalibriert (Wiederholungs-Erkennung), Elfmeterschießen (Schritt 6c).

Offen:
- [ ] **Elfmeterschießen + Gast-Tore end-to-end:**
      `python make_highlights.py videos/bundesliga-2-2-5_3.mov` — Schießen-Clip
      von Anfang bis Ende? Label korrekt? Die 4 Tore (2 Heim, 2 Gast) + Minuten?
- [ ] Finale Reels visuell prüfen (Premier + cross_nation), Minuten-OCR checken.
- [ ] Score-Templates ergänzen, wenn andere Stände auftauchen: Premier 5–9;
      cross_nation 4–9 (0–3 vorhanden; Gast-„3" bisher aus der Heim-Position —
      bei einem echten x:3 ggf. ein Gast-„3" nachziehen); bundesliga 3–9
      (bisher nur 0–2 gesehen).
- [ ] Weitere Skins nach demselben Rezept (Board-Frame → Regionen messen →
      Template-Glyphen ziehen → Profil + cv2-Validierung).

---

## 6. Was bewusst NICHT als nächster Schritt gilt

- Schützen-Erkennung im Live-Bild (Controller-Marker-Farben,
  Spieler-Tracking) — Marker getestet, siehe Notiz unten
- Tor-Erkennung aus dem Spielgeschehen (statt über die Anstoß-Tafel)
- Eigenname des Schützen per OCR (É-Sonderzeichen, fragil — kommt aus
  den App-Taps)
- Echtzeit-/Live-Verarbeitung (das ganze System läuft im Batch)

Das bleibt das große, teure, jährlich brechende Problem — unabhängig
davon wie gut die lesbaren Tafeln funktionieren.

### Notiz: Marker-Experiment (zweite Session)

Einmal bewusst an EINEM Standbild getestet (`frame_00027`), um es zu
verstehen — NICHT als Pipeline-Schritt. Der gesteuerte Spieler am Ball trägt
ein farbiges Dreieck über dem Kopf (Controller-Marker). Es gibt **vier
Farben, eine pro Mensch/Controller: ROT, GELB, LILA, BLAU.** In 2v2 sagt die
Farbe also, welcher Mensch zuletzt am Ball war (z.B. rot = Person A, blau =
Person B). Das ist der eigentliche Wunsch — der In-Game-Name nützt nichts,
weil beim ständigen Spielerwechsel der gesteuerte ≠ der treffende Spieler ist.

Gemessene Werte (ROTER Marker, `frame_00027`):
- RGB (236, 3, 75) — HEX `#EC034B` — HSV (OpenCV) (171, 252, 236)
- Flache, voll gesättigte UI-Farbe, klar von Trikot-/Banden-Rot trennbar
  (deren Sättigung lag deutlich niedriger).

**Erkenntnis — warum es trotzdem geparkt bleibt:** Die FARBE auszulesen ist
trivial und billig (Farb-Threshold). Der teure Teil ist NICHT die Farbe,
sondern (1) den Moment des letzten Ballkontakts vor dem Tor im Live-Bild zu
treffen (im Jubel ist der Marker weg — Cutscene) und (2) den richtigen Marker
dem Schützen zuzuordnen (mehrere Marker möglich). Das ist die Live-Tracking-/
Ball-Verfolgungs-Branch. Die Farbe→Mensch-Zuordnung selbst ist danach nur ein
Lookup (rot=…, gelb=…, lila=…, blau=…).

**Nebenbefund (auch geparkt):** Das Spiel blendet nach dem Tor zusätzlich den
In-Game-Namen des Schützen als feste Tafel ein (z.B. „ASSAN OUÉDRAOGO" +
Schüsse/Tore-Karte, unten links). Lesbar wie die anderen Tafeln, aber für
2v2 unbrauchbar (gesteuerter ≠ treffender Spieler) — daher nicht verfolgt.

---

## 7. Hardware-Notizen

- Billige OEM-Capture-Box (~20€, baugleich mit Rybozen/NearStream-Klasse,
  Shenzhen-OEM) reicht fürs Experiment. HDCP war kein Problem.
- Monitor-Passthrough evtl. auf 1080p begrenzt (Bild am Monitor ggf.
  schlechter als direkt) — für Vision egal, da Aufnahme in 1080p ohnehin
  reicht.
- Falls je Dauerbetrieb: auf eine Elgato (Neo ~100€ oder 4K S ~160€)
  upgraden wegen Treiber-Stabilität. 4K X ist Overkill.
- MacBook Pro 16" M4 Pro hat nur USB-C/Thunderbolt — bei USB-A-Kabel der
  Box einen Adapter nutzen.
