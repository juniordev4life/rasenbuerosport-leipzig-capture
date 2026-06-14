# Live-Stream in der App — Technischer Plan

> Status: Konzept / noch nicht umgesetzt. Ziel: einen Live-Stream des laufenden
> FC26-Spiels exklusiv in der App nach dem Login anbieten. Dieses Dokument hält
> die empfohlene Architektur, die Hardware-Bewertung und die offenen
> Entscheidungen fest.

## Kerngedanke

Ein Live-Stream passt fast nahtlos auf das, was bereits existiert: Der Mini-PC
nimmt schon per ffmpeg auf, Videos werden schon über einen Storage-Bucket
ausgeliefert, die App spielt schon `<video>` ab und gated alles hinter
Firebase-Login. Live ist im Grunde dasselbe Muster, nur **kontinuierlich**.

Empfehlung: **HLS** (HTTP Live Streaming), nicht WebRTC. Begründung unten.

## Datenfluss

```
Capture-Karte → Mini-PC (ffmpeg, QuickSync-Encode)
   ├─ HLS-Segmente (.m4s + rollende .m3u8)  → Bucket/CDN → App-Player
   └─ .mov-Datei (wie bisher)               → Highlight-/Zero-Tracking-Pipeline
```

Ein ffmpeg, zwei Ausgänge über den `tee`-Muxer: Live-Stream und die bestehende
Aufnahme laufen gleichzeitig aus demselben Capture-Input. Die Highlight-Pipeline
bleibt unverändert, Live kommt nur obendrauf.

Ablauf:
1. ffmpeg segmentiert den Feed in ~2–4s-Häppchen plus eine ständig
   aktualisierte Playlist (`.m3u8`).
2. Diese Dateien wandern in den Storage-Bucket — wie die Highlight-Reels, nur
   fortlaufend während des Spiels.
3. Die App spielt die Playlist per `<video>` + hls.js ab (Safari/iOS kann HLS
   nativ). Dieselbe Komponente wie der Highlight-Player, nur mit Live-Quelle.

## Capture / Encode (Mini-PC)

- Hardware-Encode über Intel QuickSync (`h264_qsv`) — 1080p30 läuft nebenbei,
  CPU-Last bleibt niedrig, auch parallel zur Aufnahme.
- `tee`-Muxer für den zweiten (HLS-)Ausgang, damit Aufnahme und Stream aus
  einem Capture-Input kommen (kein zweiter Karten-Zugriff, kein Konflikt).
- Live-Bitrate Richtung 4–6 Mbit/s bei 1080p; 720p als sparsamere Alternative,
  falls die Upload-Bandbreite knapp ist.

## Delivery (Bucket / CDN)

- Segmente + Playlist landen im bestehenden Storage-Bucket (gleicher Weg wie
  die Highlight-Reels, nur kontinuierlich).
- Zuschauerzahl ist dank Bucket/CDN praktisch gratis: das CDN liefert die
  Dateien aus, der Mini-PC sendet immer nur **einen** Stream hoch — egal ob
  1 oder 30 Zuschauer.
- Aufbewahrung: Live-Segmente nach dem Spiel löschen / kurze TTL — sie sollen
  sich nicht ansammeln.

## Zugriffsschutz — „exklusiv nach Login"

Ein öffentlicher Bucket-Link (wie bei den Highlights) wäre **nicht** exklusiv —
wer die URL hat, schaut mit. Zwei Stufen:

1. **MVP / pragmatisch:** Stream unter einem nicht-erratbaren Pfad (UUID pro
   Spiel), den die App erst nach Login preisgibt; kurze Aufbewahrung. Für einen
   Bürokreis faktisch ausreichend, aber „Sicherheit durch Unkenntnis", kein
   echtes Schloss.
2. **Sauber / echtes Schloss:** Cloud CDN vor den Bucket, und die API stellt
   nach dem Firebase-Auth-Check ein **kurzlebiges Signed Cookie** aus. Das eine
   Cookie deckt Playlist + alle Segmente ab und läuft nach X Minuten ab. Damit
   ist der Stream wirklich nur für eingeloggte Nutzer erreichbar — und das CDN
   skaliert beliebig viele Zuschauer.

Empfohlener Weg: mit dem MVP starten (beweist die ganze Kette end-to-end), dann
auf Signed Cookies härten, sobald „exklusiv" wirklich dicht sein soll.

## App-Seite

- Live-Player-Komponente, im Wesentlichen der Highlight-Player mit Live-Quelle
  (hls.js für Chrome/Firefox/Android, nativ auf Safari/iOS).
- „Jetzt live"-Hinweis: Die App muss wissen, wann ein Stream läuft. Das nutzt
  den vorhandenen Recording-Status-Rückkanal (Agent → API) — wenn der Agent
  einen Live-Stream startet, meldet er das, die App zeigt den Live-View.
- Hinter dem bestehenden `/app/*`-Auth-Layout.

## Warum HLS und nicht WebRTC

| | HLS (empfohlen) | WebRTC |
|---|---|---|
| Latenz | ~10–20s (mit Tuning ~5–10s) | Sub-Sekunde |
| Infrastruktur | Reine Dateien, kein Server, bestehender Bucket/CDN | Media-Server (SFU) oder bezahlter Dienst |
| Skalierung Zuschauer | gratis über CDN | Last pro Zuschauer (Server/SFU) |
| Aufwand / Kosten | gering | deutlich höher |

Fürs Zuschauen beim Bürokick ist die Latenz egal — niemand wettet in Echtzeit.
Der Aufwand-/Nutzen-Schnitt fällt klar auf HLS.

## Hardware-Bewertung

Die geplante Hardware (Ubuntu-Mini-PC, Intel i7 mit QuickSync, USB-Capture-Karte)
trägt das locker:
- QuickSync encodet 1080p30 in Hardware praktisch nebenbei, auch parallel zur
  Aufnahme.
- Die Capture-Karte liefert ohnehin 1080p30.
- **Einziger echter Engpass: die Büro-Upload-Bandbreite.** Ein 1080p-Stream
  braucht dauerhaft ~4–6 Mbit/s nach oben. → **Vor Umsetzung einmal messen.**
  Falls knapp: 720p als sicherer Startpunkt.

## Aufwand grob

- **Capture:** ffmpeg-`tee` für den HLS-Ausgang + kontinuierlicher
  Segment-Upload. Baut auf dem bestehenden Agent auf.
- **API:** „Stream ist live"-Signal (vorhandener Recording-Status-Rückkanal) +
  später das Signed-Cookie-Minting.
- **App:** Live-Player-Komponente (≈ Highlight-Player) + „Jetzt live"-Hinweis,
  hinter dem Login.
- **Infra (nur saubere Stufe):** Cloud CDN + Signed Cookies einrichten.

## Offene Entscheidungen

1. **Latenz-Anspruch:** reichen ~10–20s (HLS, einfach), oder Richtung ~5s
   drücken (LL-HLS, mehr Tuning)?
2. **Exklusivität:** MVP (obskurer Pfad) zum Start akzeptabel, oder gleich
   Signed Cookies?
3. **Nur 1 Stream gleichzeitig** (ein Mini-PC, ein Spiel)? Vereinfacht alles —
   Annahme: ja.

## Voraussetzung vor Umsetzung

- Büro-Upload-Bandbreite messen (entscheidet 1080p vs. 720p).
- Mini-PC steht und der Agent läuft auf Ubuntu/v4l2 (siehe `SETUP_MINIPC.md`).
