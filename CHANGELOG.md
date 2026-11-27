# Changelog

Das Format folgt [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die
Versionen [Semantic Versioning](https://semver.org/lang/de/):

* **Major** - inkompatible Änderung der Konfiguration, oder der Sketch muss neu
  geflasht werden
* **Minor** - neue Funktion, rückwärtskompatibel
* **Patch** - Fehlerbehebung oder reine Doku-Änderung

Neue Einträge kommen unter `[Unreleased]`. `scripts/release.py` macht daraus beim
Release einen datierten Abschnitt.

## [Unreleased]

### Neu

* Untermenü **Filament**: Laden und Entladen mit im Menü wählbarer Temperatur.
  Nutzt `LOAD_FILAMENT`/`UNLOAD_FILAMENT`, wenn es die Makros gibt, sonst einen
  eingebauten Ablauf (Direktantrieb: 50 + 30 mm laden, 60 mm entladen; in
  `[menu] filament_*` einstellbar). Lange Fahrten werden in Stücke bis
  `max_extrude_only_distance` geteilt.

## [1.2.0] - 2026-11-27

### Neu

* Untermenü **Achsen bewegen**: Achse wählen, Zielposition drehen, Klick fährt
  hin; Schrittweite 0,1/1/10 mm und Tempo je Achse als eigene Menüpunkte, Grenzen
  aus Klipper, Z nie unter 0, nur nach dem Homing und ohne Druck. Dazu „Motoren
  aus“ (`M84`). Abschalten mit `[menu] move = no`, Starttempo `move_speed_x`,
  `move_speed_y`, `move_speed_z` in mm/min (3000/3000/200).

## [1.1.0] - 2026-11-27

### Neu

* Untermenü **Homing**: alle Achsen, X und Y zusammen, X, Y oder Z (nur ohne Druck).
* Untermenü **Heizen**: Vorgaben (Standard PLA, PETG, ABS; eigene per
  `[preheat NAME]`), Abkühlen und die Zieltemperatur von Hotend und Bett per
  Drehgeber – auch während des Drucks, begrenzt durch `max_temp` aus Klipper.
  Abschalten mit `[menu] homing = no` bzw. `heating = no`, Schrittweite
  `temperature_step`.
* Langes Drücken geht im Menü eine Ebene zurück.
* Die Simulation steht zwei Minuten still, bevor sie „druckt“, und heizt auf
  Menübefehle hin.

## [1.0.1] - 2026-11-27

### Behoben

* Drehgeber mit 2 Flanken pro Rastung (z. B. manche HW-040) brauchten zwei
  Rastungen pro Schritt. Der Sketch (1.0.1) erkennt jetzt selbst, ob der
  Drehgeber 2 oder 4 Flanken pro Rastung hat. Dafür den Sketch neu flashen.

## [1.0.0] - 2026-11-24

Erste Version.

### Hinzugefügt
- Dienst, der Klipper-Drucker über Moonraker liest und auf einem Text-LCD
  (20×4 oder 16×2, HD44780 mit PCF8574) an einem Arduino Uno/Nano anzeigt.
- Seiten: Status, Temperaturen, Druckdetails, System; deutsch und englisch.
- Heizer, Extruder und Sensoren werden aus dem Drucker ermittelt.
- Drehgeber mit Menü: Pause, Fortsetzen, Abbrechen, Firmware-Neustart, eigene
  G-Code- und Power-Einträge; Neustart und Herunterfahren des Rechners
  (standardmäßig aus).
- Arduino-Sketch ohne Zusatzbibliotheken: Kennung, Prüfsummen, Quittungen,
  automatische I2C-Suche, dunkles Display ohne Dienst, Wiederherstellung nach
  Störungen.
- Kommandos `run`, `config`, `ports`, `identify`, `pages`, `simulate`.
- `install.sh` (auch mehrere Instanzen), systemd-Dienst, Block für den
  Moonraker-Update-Manager.
- Tests: Unit-Tests, der echte Sketch gegen ein LCD-Modell, Ende-zu-Ende-Test.

