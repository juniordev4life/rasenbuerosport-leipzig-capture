# Mini-PC einrichten — FC26 Highlight-Aufnahme (Office)

Ziel: kleiner Rechner im Office, der die FC-Spiele aufnimmt, verarbeitet und die
Highlights hochlädt. Diese Anleitung bringt den Rechner in den Grundzustand — der
Rest (Aufnahme-Agent + Verarbeitung) wird danach per SSH aus der Ferne eingerichtet.

## Hardware
- Intel NUC5i7RYH — Core i7-5557U (**Broadwell / Gen8**, 2 Kerne / 4 Threads,
  Iris Graphics 6100). Älteres Gerät (2015), reicht für die Capture-Box. Der
  vorinstallierte iHD-Treiber (`intel-media-va-driver`) treibt die Iris 6100
  für H.264-Encode — am echten Gerät verifiziert.
- Kit: RAM + SSD selbst bestücken. 16 GB DDR3L empfohlen. Zwei Laufwerks-Bays
  (M.2 + 2,5"): am besten eine größere 2,5"-SSD (z.B. 1 TB), dann füllen die
  Roh-`.mov`-Aufnahmen die Platte nicht.
- LAN-Kabel (Ethernet) — WLAN nicht nötig.
- USB-Capture-Box (kommt später dazu, an einen USB-3.0-Port = meist blau;
  der NUC hat 2 vorne + 2 hinten).

## 1. Betriebssystem installieren
- **Ubuntu Server 24.04 LTS** (Desktop geht auch, falls eine Oberfläche gewünscht
  ist — die Befehle bleiben gleich).
  - Warum 24.04 und nicht die neuere 26.04: 24.04 ist die ausgereifte LTS
    (Sicherheitsupdates bis 2029, mit Ubuntu Pro bis 2034). 26.04 ist noch sehr
    frisch — erst ab Punkt-Release 26.04.1 fürs Dauergerät empfehlenswert.
  - **Keine** Nicht-LTS-Version (24.10 / 25.04 / 25.10) — nur 9 Monate Support.
- Bei der Installation:
  - Benutzer anlegen (z.B. `fchighlights`), Passwort notieren.
  - **Hostname** sinnvoll vergeben (z.B. `fc-office`) — darüber wird der Rechner
    später IP-unabhängig erreichbar.
  - **„Install OpenSSH server" ankreuzen** (wichtig — damit wir den Rest remote machen).
- Per LAN ans Netzwerk, **bei DHCP belassen** (keine feste IP am Rechner einstellen —
  sonst läuft er nur in genau einem Netz). Die lokale IP darf sich also ruhig
  ändern; der Rechner ist im LAN als `<hostname>.local` (z.B. `fc-office.local`)
  erreichbar.

## 2. System aktualisieren + automatische Sicherheitsupdates
```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install unattended-upgrades
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
```
(Damit holt sich der Rechner Sicherheitspatches künftig selbst — wichtig für ein
Gerät, das dauerhaft läuft.)

## 3. Benötigte Pakete installieren
```bash
sudo apt -y install ffmpeg python3-venv python3-pip git \
  v4l-utils vainfo intel-media-va-driver-non-free \
  tesseract-ocr tesseract-ocr-deu avahi-daemon
```
(`avahi-daemon` = damit der Rechner im LAN als `<hostname>.local` erreichbar ist,
unabhängig von der wechselnden IP.)
(Hardware-Encode-Treiber: `intel-media-va-driver` (iHD). Entgegen der Faustregel
„iHD erst ab Gen9/Skylake" treibt iHD 24.1.0 die Broadwell-Iris-6100 für
H.264-Encode — am echten Gerät verifiziert. Sollte eine künftige Treiberversion
Broadwell fallen lassen, ist `i965-va-driver` der Fallback. `tesseract` =
Texterkennung; `v4l-utils`/`vainfo` nur zum Prüfen.)

## 4. Hardware-Encode (VA-API) prüfen
Der vorinstallierte iHD-Treiber genügt — kein `LIBVA_DRIVER_NAME`-Override nötig:
```bash
vainfo | grep -E "Driver version|VAProfileH264.*Enc"
```
→ Es muss `VAProfileH264...` mit `VAEntrypointEncSlice` erscheinen — das ist unser
Encoder. `VAProfileHEVC`-Encode fehlt auf Broadwell, und das ist erwartet: die
Iris 6100 kann H.265 nur (teilweise) dekodieren, nicht encoden. Wir encoden daher
in H.264.

Verifiziert (16.06.2026, am Gerät `eafc-capture`): `vainfo` meldet H264 Enc, und
ein echter `h264_vaapi`-Encode (1080p30, 2 s) erzeugt eine gültige H.264-Datei —
Hardware-Encode steht.

Wozu das gut ist: Der Agent encodet die Aufnahme sonst per Software-`libx264` auf
nur 2 Kernen — knapp bei 1080p30 und erst recht, wenn später ein Live-Stream
parallel läuft. Mit VA-API macht das die GPU. Der Agent bekommt den Encoder
später (beim SSH-Setup) per Env mit, als Startpunkt:
```bash
ENCODE_ARGS='-vaapi_device /dev/dri/renderD128 -vf format=nv12,hwupload -c:v h264_vaapi -b:v 6M'
```
(Die genaue Flag-Reihenfolge feilen wir beim Verdrahten am Gerät aus —
`vainfo` muss vorher H.264-Encode zeigen.)

Hinweis zum Highlight-Reel: `make_highlights`/`cut_highlights` encoden die Clips
aktuell mit `libx265` (Software-HEVC). Auf diesem 2-Kern-Broadwell ist das langsam
(kein HW-HEVC). Es ist ein Hintergrund-Job nach dem Spiel — funktioniert, der Reel
braucht nur ein paar Minuten länger. Wer das beschleunigen will, stellt die
Clip-/Reel-Encodes ebenfalls auf H.264 (VA-API) um.

## 5. Capture-Box prüfen (nur falls schon vorhanden)
USB-Capture-Box anstecken, dann:
```bash
lsusb
v4l2-ctl --list-devices
v4l2-ctl --list-formats-ext -d /dev/video0   # unterstützte Formate/Auflösungen/FPS
```
→ Die Box sollte als Gerät auftauchen (z.B. `/dev/video0`). Wenn die Box noch nicht
da ist: einfach überspringen, machen wir später.

Die `--list-formats-ext`-Ausgabe ist das Linux-Pendant zur macOS-Pixelformat-Eigenheit
(siehe HANDOFF, Gotchas): Der Agent fordert per `CAPTURE_INPUT` (Linux-Default `v4l2`,
1920x1080@30) ein Format an, das die Box wirklich kann. Liefert die Box z.B. nur
`YUYV`/`MJPG`, das via `-input_format` in `CAPTURE_INPUT` setzen — sonst bricht ffmpeg
mit „format not supported" ab. Und: nur ein Prozess darf `/dev/video0` öffnen
(kein paralleler Stream), sonst „device busy".

### Am Gerät verifiziert (16.06.2026, MacroSilicon USB3.0 Video)
Die Karte liefert `YUYV` 1920×1080 (bis 60fps) auf `/dev/video0`. Aufnahme +
VA-API-Encode mit echtem PS5/FC26-Signal in Echtzeit getestet. Die zwei
verifizierten Env-Werte für den Agent:

```bash
CAPTURE_INPUT='-f v4l2 -use_wallclock_as_timestamps 1 -framerate 30 -video_size 1920x1080 -input_format yuyv422 -i /dev/video0'
ENCODE_ARGS='-vaapi_device /dev/dri/renderD128 -vf format=nv12,hwupload -c:v h264_vaapi -b:v 6M'
```

‼️ `-use_wallclock_as_timestamps 1` ist PFLICHT für diese Karte: sie liefert
kaputte Frame-Timestamps. Ohne das Flag bekommt eine dauerbasierte Aufnahme
0 Frames, und der VA-API-Encoder crasht dann bei leerem Input (Segfault). Mit
dem Flag läuft die Aufnahme stabil in Echtzeit. (Der Linux-Default in
`office_agent.py` enthält das Flag bereits; die `ENCODE_ARGS` müssen gesetzt
werden, sonst encodet der Agent in Software-libx264.)

## 6. Dauerbetrieb (optional, empfohlen)
- Im BIOS „**Auto Power On after power loss / Restore on AC**" aktivieren → der
  Rechner startet nach einem Stromausfall von selbst wieder.
- (Nur bei Desktop-Variante:) automatischen Ruhezustand ausschalten:
  ```bash
  sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
  ```

### Aufnahme-Agent automatisch beim Boot starten (systemd)
Der Agent (`office_agent.py`) läuft als **User-Service** (kein sudo/root nötig;
lädt `agent.env`; `Restart=on-failure` bei Absturz). Die Unit liegt im Repo unter
`deploy/eafc-agent.service`. Einrichten:
```bash
mkdir -p ~/.config/systemd/user
cp ~/rasenbuerosport-leipzig-capture/deploy/eafc-agent.service ~/.config/systemd/user/
systemctl --user daemon-reload
loginctl enable-linger "$USER"    # User-Manager startet schon vor dem Login -> Autostart ohne Anmeldung
systemctl --user enable --now eafc-agent.service
```
Prüfen / Live-Log / nach einer `agent.env`-Änderung neu starten:
```bash
systemctl --user status eafc-agent
journalctl --user -u eafc-agent -f     # ersetzt das alte /tmp/agent.log
systemctl --user restart eafc-agent
```
Voraussetzung für Aufnahme + VA-API: der Benutzer muss in den Gruppen `render`
und `video` sein (siehe Abschnitt 4).

### Speicherplatz & Aufräumen
Ein Lauf erzeugt ein Vielfaches der Aufnahme an Zwischendaten: Frames bei 1080p60,
geschnittene Clips, das Reel und ~2 GB Postmatch-Temp unter `/tmp`. Die Pipeline
räumt selbst auf — gesteuert über `agent.env`:

| Variable | Default | Wirkung |
|----------|---------|---------|
| `CLEANUP` | `1` | `0` schaltet **jedes** Aufräumen ab (nur zum Debuggen) |
| `RECORDING_RETENTION_DAYS` | `0` | `0` = Aufnahmen dauerhaft behalten; `>0` = älter als X Tage löschen (Büro-Box: `7`) |
| `ORPHAN_SCRATCH_HOURS` | `24` | Ab wann Frames/Stats/JSONs früherer Läufe als verwaist gelten |
| `ORPHAN_REEL_HOURS` | `48` | Ab wann Reels/Clips gescheiterter Läufe weggeräumt werden (bis dahin bleiben sie für einen manuellen Upload-Retry) |

### Netzausfall während des Uploads
Reel-Upload und Status-Meldung werden wiederholt (`RETRY_ATTEMPTS`, exponentieller
Backoff über `RETRY_BACKOFF`). Kommt danach noch nichts durch, hinterlässt der Lauf
einen Marker `pending_game_<id>.json` neben dem fertigen Reel. Beim nächsten
Pipeline-Lauf **und** beim Agent-Start wird er abgearbeitet: Reel hochladen, Status
melden, Marker weg. Das Spiel wird dabei bewusst **nicht** als `failed` gemeldet —
das Reel existiert ja, es fehlt nur der Transport.

| Variable | Default | Wirkung |
|----------|---------|---------|
| `RETRY_ATTEMPTS` | `4` | Versuche pro Upload bzw. Status-PATCH |
| `RETRY_BACKOFF` | `5` | Sekunden bis zum zweiten Versuch, danach verdoppelnd |
| `PENDING_GIVEUP_HOURS` | `24` | Danach wird ein nicht abschließbarer Marker als `failed` gemeldet und verworfen — damit kein Spiel endlos auf `processing` hängt |

Manuell nachholen (ohne auf ein neues Spiel zu warten):
```bash
cd ~/rasenbuerosport-leipzig-capture
RESUME_ONLY=1 venv/bin/python src/process_highlights.py
```

Die Zustandsmaschine dahinter ist getestet (lokaler API-Stub, kein Netz nötig):
```bash
bash tests/test_resume.sh
```

Aufgeräumt wird nach **jedem** Lauf — auch nach einem gescheiterten — plus beim
Start des nächsten Laufs (Verwaist-Sweep, fängt hart abgebrochene Läufe). Platz
gelegentlich prüfen:
```bash
df -h ~
du -sh ~/rasenbuerosport-leipzig-capture/recordings /tmp
```
Läuft die Platte voll, scheitern zuerst die teuren Schritte (Reel), dann die
kleinen (Stats) — und jeder Fehlversuch hinterlässt neue Reste. Diese Spirale hat
im August 2026 eine Woche Ausfall verursacht (HANDOFF.md → Gotchas).

## Fertig — was wir zum Weitermachen brauchen
- die **IP-Adresse** des Rechners,
- **Benutzername + Passwort** (oder ein SSH-Key).

Den Rest — Aufnahme-Agent (Start/Stop + Spiel-ID im Dateinamen), die Verarbeitungs-
Pipeline und den Cloud-Upload — richten wir dann per SSH ein. Es muss nichts
Spielspezifisches vorinstalliert werden.
