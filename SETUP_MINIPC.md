# Mini-PC einrichten — FC26 Highlight-Aufnahme (Office)

Ziel: kleiner Rechner im Office, der die FC-Spiele aufnimmt, verarbeitet und die
Highlights hochlädt. Diese Anleitung bringt den Rechner in den Grundzustand — der
Rest (Aufnahme-Agent + Verarbeitung) wird danach per SSH aus der Ferne eingerichtet.

## Hardware
- Mini-PC (i7), 8 oder 16 GB RAM, 256 GB SSD. (16 GB bevorzugt, falls wählbar.)
- LAN-Kabel (Ethernet) — WLAN nicht nötig.
- USB-Capture-Box (kommt später dazu, an einen USB-3.0-Port = meist blau).

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
(QuickSync/Hardware-Encode = `intel-media-va-driver`; Texterkennung = `tesseract`;
`v4l-utils`/`vainfo` nur zum Prüfen.)

## 4. Hardware-Encode (QuickSync) prüfen
```bash
vainfo
```
→ Es sollten Zeilen wie `VAProfileH264...` und idealerweise `VAProfileHEVC...` mit
„**Encode**" erscheinen. Dann steht der Hardware-Encoder.
(Falls HEVC-Encode fehlt — ältere CPU-Generation — ist das kein Problem, wir nutzen
dann H.264.)

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

## 6. Dauerbetrieb (optional, empfohlen)
- Im BIOS „**Auto Power On after power loss / Restore on AC**" aktivieren → der
  Rechner startet nach einem Stromausfall von selbst wieder.
- (Nur bei Desktop-Variante:) automatischen Ruhezustand ausschalten:
  ```bash
  sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
  ```

## Fertig — was wir zum Weitermachen brauchen
- die **IP-Adresse** des Rechners,
- **Benutzername + Passwort** (oder ein SSH-Key).

Den Rest — Aufnahme-Agent (Start/Stop + Spiel-ID im Dateinamen), die Verarbeitungs-
Pipeline und den Cloud-Upload — richten wir dann per SSH ein. Es muss nichts
Spielspezifisches vorinstalliert werden.
