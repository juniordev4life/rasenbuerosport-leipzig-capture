"""HUD-Profile pro FC26-Skin.

Jeder Wettbewerb (Liga-Lizenz) rendert die lesbaren Tafeln anders. Ein Profil
beschreibt PRO Skin, wo und wie Stand und Minute stehen. Detektion, Schnitt
und Reel-Bau bleiben skin-unabhaengig — nur dieses Profil wechselt.

Region-Tupel: (x, y, w, h, method, psm)
  method:
    "otsu_inv" - helle Schrift auf dunkel (Otsu invertiert)        -> Bundesliga
    "otsu"     - dunkle Schrift auf hell  (Otsu normal)            -> Premier home/minute
    "white"    - nur weisse Ziffer behalten (gegen gemischten BG)  -> Premier away
  psm: Tesseract-Modus (10 = Einzelzeichen, 8 = Wort, 7 = Zeile)

Score:
  mode "dash"  -> EINE Region "H - A"                 (Bundesliga)
  mode "split" -> ZWEI Einzelziffer-Regionen home/away (Premier; Logo dazwischen)

Minute: pro Tor-Seite (home/away) — die Tafel ist je nach Schuetze gespiegelt.
  None = fuer diese Seite noch nicht kalibriert.
"""

HUD_PROFILES = {
    "bundesliga": {
        # Stand "H - A" per Template-Abgleich (NICHT OCR). Tesseract liest die
        # Tafel unzuverlaessig: laesst den Bindestrich weg ("2 - 0" -> "20", an
        # der strikten Regex gescheitert -> 2:0 ging verloren) UND verliest im
        # Spiel Marker/Ball zu Phantom-Staenden (4:4, 8:8 ...). Graustufen-
        # Korrelation der zwei Einzelziffern ist robust in beide Richtungen
        # (Live-Play korreliert <0.3). Siehe build_templates_bundesliga.py.
        # Validiert ueber das ganze Spiel: 0 Falsch-Positive, 2:0 sicher erkannt.
        "score": {
            "mode": "template",
            "home_region": (931, 936, 22, 24),   # Heim-Ziffer links vom Strich
            "away_region": (967, 936, 22, 24),    # Gast-Ziffer rechts vom Strich
            "templates": "templates/bundesliga",
            "threshold": 0.5,
        },
        "minute": {
            # Schuetzen-Zeile "NAME MM'": die Minute ist die LETZTE Zahl. Ihre
            # X-Position haengt von der Namenslaenge ab (rechtsbuendig: Heim
            # endet ~x940, Gast ~x1255) — darum die ganze Zeile scannen statt
            # einer engen Box (wie Premier, mode "line"). Validiert an MUSIALA 34',
            # TAH 53' (Heim) und MILOSEVIC 55', MBANGULA 75' (Gast).
            "mode": "line",
            "home": (600, 880, 360, 38, "otsu_inv", 7),
            "away": (960, 880, 360, 38, "otsu_inv", 7),
        },
        # Normales Spiel-HUD (Uhr + Team-Boxen, opak) -> Praesenz fuer
        # Wiederholungs- UND Elfmeterschiessen-Erkennung.
        "hud": {
            "region": (185, 55, 195, 65),               # "BAY"/"SVW"-Boxen (stabil, kontrastreich)
            "ref": "templates/bundesliga/hud_ref.png",
            "threshold": 0.5,
        },
        # Elfmeterschiessen (mode "hud_gap"): langer HUD-weg-Block am Spielende
        # (die Schuetzen-Icons ersetzen das normale HUD komplett -> hud_present
        # == False). End-Screens (keine gruene Wiese) werden per green_region
        # abgeschnitten.
        "shootout": {
            "mode": "hud_gap",
            "green_region": (560, 560, 800, 400),
            "green_min": 0.30,
            "min_length": 45,
            "label": "Elfmeterschießen",
        },
    },
    "premier": {
        "score": {
            # Template-Abgleich statt OCR: die Heim-Ziffer ist hell auf hellem
            # Chevron (niedriger Kontrast) -> OCR verliest sie. Graustufen-
            # Korrelation gegen Referenz-Ziffern ist robust. Siehe build_templates.py.
            "mode": "template",
            "home_region": (864, 831, 45, 88),
            "away_region": (1008, 822, 62, 92),
            "templates": "templates/premier",
            "threshold": 0.5,
        },
        "minute": {
            # ganze Schuetzen-Zeile scannen, letzte Zahl = Minute (Position
            # haengt von der Namenslaenge ab). Heim-Tor links, Gast-Tor rechts.
            "mode": "line",
            "home": (600, 916, 250, 38, "otsu", 7),    # "EZE 36'" / "TROSSARD 90'"
            "away": (1075, 916, 415, 38, "otsu", 7),   # "ZUBIMENDI (ET) 72'" / "MBEUMO 86'"
        },
        # HUD-Praesenz (Score-Bug oben links) -> erkennt Wiederholungen: waehrend
        # Jubel/Replay ist das HUD weg. Fuer den adaptiven Clip-Start.
        "hud": {
            "region": (80, 56, 390, 56),
            "ref": "templates/premier/hud_ref.png",
            "threshold": 0.45,
        },
    },
    "cross_nation": {
        # beIN-Optik. Score-Ziffern dunkel-auf-weiss, flankieren das V-Logo
        # (wie Premier) — hier aber KONTRASTREICH, Template-Abgleich liest sicher.
        # Ziffern fuer beide Seiten gleich (ein Template-Satz). Minute "MM'" steht
        # unter dem Schuetzen-Foto: Heim-Tor links, Gast-Tor rechts (gespiegelt).
        "score": {
            "mode": "template",
            "home_region": (850, 888, 60, 74),
            "away_region": (1005, 888, 85, 74),
            "templates": "templates/cross_nation",
            "threshold": 0.5,
        },
        "minute": {
            "mode": "digit",
            "home": (480, 985, 56, 28, "otsu", 8),    # "43'" unter Foto links
            "away": (1383, 985, 55, 28, "otsu", 8),   # "84'" unter Foto rechts
        },
        "hud": {
            "region": (90, 48, 200, 78),               # gruenes V-Logo + PSG/AVL-Box
            "ref": "templates/cross_nation/hud_ref.png",
            "threshold": 0.45,
        },
        # Elfmeterschiessen (mode "label"): Beim cross-Skin bleibt waehrend des
        # Schiessens ein HUD stehen (V-Logo + Penalty-Stand + "ELFMETER"), das das
        # normale HUD noch teilweise matcht (~0.62) -> der hud_gap-Ansatz greift
        # NICHT. Stattdessen die untere HUD-Zeile pruefen: dort steht "ELFMETER"
        # (statt der Uhr) -> per Template erkannt. Der Block reicht vom ersten
        # ELFMETER-Frame bis zum letzten gruenen Wiese-Frame (Sieger-Jubel), bevor
        # die End-Screens kommen.
        "shootout": {
            "mode": "label",
            "label_region": (150, 106, 150, 28),       # untere HUD-Zeile (Uhr bzw. "ELFMETER")
            "label_ref": "templates/cross_nation/elfmeter_ref.png",
            "label_threshold": 0.7,
            "green_region": (560, 560, 800, 400),
            "green_min": 0.30,
            "min_length": 45,
            "label": "Elfmeterschießen",
        },
    },
}
