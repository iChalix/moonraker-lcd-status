# Moonraker LCD Status

Statusanzeige für Klipper-Drucker auf einem Text-LCD: Ein Dienst liest den Drucker
über **Moonraker**, ein **Arduino Uno/Nano** zeigt ihn auf einem **20×4**- oder
**16×2-LCD** an. Mit einem **Drehgeber** lässt sich durch Seiten blättern und ein
Menü bedienen.

```
+--------------------+   +--------------------+
|Benchy_0.2mm_PLA_BLV|   |drucker       bereit|
|██████▏░░░░░░░░  42%|   |Hotend         24.1°|
|T235/235°    B60/60°|   |Bett           22.4°|
|S 84/200  Ende 14:41|   |Di 24.11.      14:00|
+--------------------+   +--------------------+
```

- Funktioniert mit jedem Klipper-Drucker: Extruder, Bett, Kammer und Sensoren
  werden ermittelt, nichts ist auf ein Modell festgelegt.
- Alles Sichtbare entsteht im Dienst. Für neue Seiten, Texte oder Menüpunkte muss
  der Arduino nicht neu geflasht werden.
- Keine Arduino-Zusatzbibliotheken.

## Hardware

| Teil | Anschluss | Uno/Nano |
|---|---|---|
| LCD (HD44780 mit I2C-Adapter PCF8574) | GND / VCC | GND / 5V |
| | SDA / SCL | A4 / A5 |
| Drehgeber (z. B. KY-040, HW-040), optional | GND / + | GND / 5V |
| | CLK / DT | D2 / D3 |
| | SW | D4 |

Das LCD nicht direkt an die GPIO-Pins des Raspberry Pi hängen: Der Adapter zieht
SDA/SCL auf 5 V, die Pins vertragen 3,3 V. Den Kontrast stellt das Poti auf dem
Adapter ein – bleibt das Display leer oder zeigt nur Kästchen, zuerst dort drehen.

### Gehäuse

In [`cad/`](cad) liegt ein Gehäuse zum Drucken für ein 20×4-LCD mit I2C-Adapter,
einen Drehgeber HW-040/KY-040 und einen Arduino Nano. Es wird mit einem Halter an
ein **3030- oder 2020-Nutprofil** geschraubt, das Display ist 20° nach oben
geneigt. Außenmaß etwa 161 × 69 × 37 mm.

| Datei | Anzahl | Hinweis |
|---|---|---|
| [`gehaeuse.stl`](cad/gehaeuse.stl) | 1 | Front liegt auf dem Druckbett |
| [`deckel.stl`](cad/deckel.stl) | 1 | mit Schienen für den Nano |
| [`klemmbuegel.stl`](cad/klemmbuegel.stl) | 1 | hält den Drehgeber |
| [`halter_3030.stl`](cad/halter_3030.stl) oder [`halter_2020.stl`](cad/halter_2020.stl) | 1 | passend zum Profil |
| [`nutenstein_3030.stl`](cad/nutenstein_3030.stl) oder [`nutenstein_2020.stl`](cad/nutenstein_2020.stl) | 2 | Dreh-Nutenstein statt Hammermutter |

Die STLs sind schon fürs Druckbett ausgerichtet und brauchen keine Stützen. PLA
reicht, solange der Drucker offen ist; in einem warmen Bauraum besser PETG.
Nutensteine mit 100 % Infill, den Halter mit 4 Wänden drucken. Der Halter für 2020
ragt hinten 10 mm unter das Profil, damit er genauso stabil ist wie der für 3030.

Material: 8 M3-Gewindeeinsätze (Loch 4,0 mm), 4× M3×6 (Display), 4× M3×8
(Klemmbügel, Halter), 4× M3×8 seitlich in den Deckel. Für das Profil 2× M5×12
(3030) bzw. 2× M4×10 (2020) in die Nutensteine; statt der gedruckten Nutensteine
gehen auch passende Hammermuttern.

Zusammenbau:

1. Gewindeeinsätze in die 4 Display-Dome, die 2 Dome neben dem Drehgeber und die 2
   Löcher im Halter einschmelzen.
2. Halter mit den Nutensteinen an das Profil schrauben. Die Seite der Nutensteine
   mit der Rille zeigt zum Schraubenkopf; beim Festziehen drehen sie sich quer.
3. Deckel von innen mit 2× M3×8 an den Halter schrauben.
4. Den Nano von vorne in die Schienen des Deckels schieben, USB-Buchse unten.
5. Display auf die Dome schrauben, Drehgeber in den Rahmen an der Front setzen und
   mit dem Klemmbügel halten. Verkabeln.
6. Gehäuse über den Deckel stecken und seitlich verschrauben, USB-Kabel von unten
   einstecken.

Die Teile entstehen aus dem Skript [`cad/lcd_gehaeuse.py`](cad/lcd_gehaeuse.py).
Alle Maße stehen oben im Skript; für andere Bauteile die Werte anpassen und neu
erzeugen, ohne Oberfläche mit

```
freecadcmd cad/lcd_gehaeuse.py
```

(macOS: `/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd`) oder in der
Python-Konsole von FreeCAD mit

```
p = "/pfad/zu/cad/lcd_gehaeuse.py"
exec(open(p).read(), {"__file__": p, "__name__": "__main__"})
```

Dabei werden STL, STEP und die FreeCAD-Datei im Ordner `cad/` neu geschrieben. `lcd_gehaeuse_mit_bauteilen.step` zeigt den Zusammenbau samt
Platzhaltern für Display, Drehgeber, Nano und Profil.

## Sketch aufspielen

[`arduino/MoonrakerLcdStatus`](arduino/MoonrakerLcdStatus/MoonrakerLcdStatus.ino)
in der Arduino-IDE öffnen und hochladen. Für ein 16×2-Display vorher oben
`LCD_COLS 16` und `LCD_ROWS 2` setzen. Bei Nano-Nachbauten meldet die IDE beim
Hochladen oft einen Synchronisationsfehler; dann unter *Werkzeuge → Prozessor*
„ATmega328P (Old Bootloader)“ wählen.

Danach steht „Moonraker LCD“ und „waiting for host“ auf dem Display. Die
I2C-Adresse sucht der Sketch selbst.

## Installation auf dem Pi

```bash
git clone https://github.com/iChalix/moonraker-lcd-status.git ~/moonraker-lcd-status
cd ~/moonraker-lcd-status
./install.sh
```

Dann in `~/printer_data/config/moonraker-lcd.conf` unter `[serial]` den Port
eintragen. Geraten wird er absichtlich nicht, denn an einem Drucker hängen auch
Klipper-MCUs und andere Arduinos.

```bash
cd ~/moonraker-lcd-status
~/moonraker-lcd-env/bin/python -m moonraker_lcd ports
~/moonraker-lcd-env/bin/python -m moonraker_lcd identify
sudo systemctl start moonraker-lcd
```

`identify` zeigt, ob am eingetragenen Port wirklich der Display-Arduino hängt.
Läuft der Dienst schon, belegt er den Port – vorher
`sudo systemctl stop moonraker-lcd`.

### Zwei CH340-Arduinos am selben Pi

CH340-Nachbauten haben keine Seriennummer und bekommen unter `/dev/serial/by-id/`
alle **denselben Namen**; sichtbar bleibt nur einer. Dann für **beide** Geräte den
Pfad unter `/dev/serial/by-path/` verwenden und jeden an seiner USB-Buchse lassen:

```bash
ls -l /dev/serial/by-path/
```

Den schon vorhandenen Dienst umstellen, **bevor** der zweite Arduino angesteckt
wird. Gibt es zwei Einträge für dieselbe Buchse (`usb-` und `usbv2-`), den mit
`usb-` nehmen.

Dieser Dienst schreibt nichts außer der Frage nach der Kennung, bis sich der
richtige Arduino gemeldet hat. Andere Programme prüfen das nicht.

## Bedienung

| Eingabe | Auf den Seiten | Im Menü |
|---|---|---|
| Drehen | nächste/vorige Seite | Auswahl bewegen, Wert ändern |
| Drücken | Menü öffnen | auswählen, Wert übernehmen |
| Lang drücken | zur ersten Seite | eine Ebene zurück, Wert verwerfen |

Im Menü stehen außerdem:

* **Homing ›** – alle Achsen, X und Y zusammen, X, Y oder Z (`G28`), nur ohne Druck.
  Hat Klipper `[z_tilt]` bzw. `[quad_gantry_level]`, steht dort auch „Z-Tilt
  ausrichten“ bzw. „Gantry ausrichten“: bei Bedarf erst `G28`, dann
  `Z_TILT_ADJUST`/`QUAD_GANTRY_LEVEL` und `G28 Z`; „(ok)“ zeigt, dass schon
  ausgerichtet ist.
* **Achsen bewegen ›** – wie bei den Temperaturen: Achse auswählen, Klick,
  Zielposition drehen, Klick fährt hin und führt zurück zur Auswahl. „Schritt“
  (0,1 / 1 / 10 mm) und „Tempo X/Y/Z“ (mm/min, Standard aus `move_speed_x/_y/_z`:
  3000/3000/200) stellt man genauso ein. Nur ohne Druck und nur für Achsen nach
  dem Homing; die Grenzen kommen aus Klipper, Z nie unter 0. „Motoren aus“ sendet
  `M84`.
* **Z-Offset ›** – Babystepping, auch während des Drucks: „Z-Offset“ wählen,
  Klick, drehen, Klick verstellt um die Differenz (`SET_GCODE_OFFSET Z_ADJUST`,
  nach dem Homing mit `MOVE=1`). „Schritt“ 0,005 bis 0,1 mm, Grenze ±2 mm.
  „Zurücksetzen“ setzt den Offset auf 0. „Speichern“ (nur ohne Druck, mit
  Rückfrage) schreibt ihn mit `Z_OFFSET_APPLY_PROBE` – oder
  `Z_OFFSET_APPLY_ENDSTOP`, wenn der Z-Endstop keine Sonde ist – und
  `SAVE_CONFIG` fest; Klipper startet dabei neu.
* **Bed Mesh ›** – nur ohne Druck und nur mit `[bed_mesh]` in Klipper:
  „Kalibrieren“ (mit Rückfrage, vorher `G28`, falls nicht alle Achsen
  referenziert sind), gespeicherte Profile laden (das aktive ist mit `*`
  markiert), „Mesh löschen“ und „Speichern“ (mit Rückfrage:
  `BED_MESH_PROFILE SAVE=…` + `SAVE_CONFIG`, Klipper startet neu).
* **Lüfter ›** – Bauteillüfter und jeder `[fan_generic]` in 10-%-Schritten
  (Klick, drehen, Klick), auch während des Drucks. Automatische Lüfter (Hotend,
  Elektronik) regelt Klipper selbst, sie erscheinen nicht.
* **Filament ›** – Laden, Entladen und die Temperatur dafür (Start: erste
  Vorheiz-Vorgabe, nicht unter `min_extrude_temp`). Es wird aufgeheizt und
  gewartet; gibt es in Klipper `LOAD_FILAMENT`/`UNLOAD_FILAMENT`, laufen danach
  diese Makros, sonst ein eingebauter Ablauf für Direktantrieb: Laden 50 mm
  schnell + 30 mm langsam, Entladen 5 mm vor und 60 mm zurück. Längen und Tempo
  in `[menu] filament_*`, für Bowden die Längen entsprechend erhöhen. Nur ohne Druck.
* **Heizen ›** – Vorgaben wie „PLA 200°/60°“ und „Abkühlen“ (nur ohne Druck)
  sowie die Zieltemperatur von Hotend und Bett. Die stellt man mit dem Drehgeber
  in Schritten von 5° ein und übernimmt sie per Klick. Das geht auch während
  eines Drucks. Nach oben begrenzt `max_temp` aus der Klipper-Konfiguration.

Das Menü zeigt nur, was gerade möglich ist. Abbrechen, Neustart und Herunterfahren
fragen nach, „Nein“ ist vorausgewählt. Ohne Eingabe schließt sich das Menü. Ist die
Beleuchtung aus, weckt die erste Eingabe nur das Display.

Es gibt absichtlich keinen Not-Aus: Die Kette aus USB, Dienst und Moonraker ist
dafür nicht zuverlässig genug.

## Konfiguration

Vollständig kommentiert in [config/moonraker-lcd.conf](config/moonraker-lcd.conf).
Eigene Vorheiz-Vorgaben ersetzen PLA, PETG und ABS:

```ini
[preheat PLA]
extruder = 210
bed = 60

[preheat TPU]
extruder = 225
bed = 50
```

Eigene Menüpunkte:

```ini
[menu_item Bett vermessen]
gcode = BED_MESH_CALIBRATE
confirm = yes

[menu_item Licht]
power_device = licht
when = always
```

| `when` | Menüpunkt erscheint |
|---|---|
| `idle` (Standard) | Klipper bereit, nichts in Arbeit |
| `printing` / `paused` / `active` | beim Druck / in der Pause / in beiden Fällen |
| `always` | immer (G-Code nur, wenn Klipper bereit ist) |

Für ein zweites Display oder einen zweiten Drucker:
`./install.sh --instance name` legt einen eigenen Dienst mit eigener
Konfiguration `moonraker-lcd-name.conf` an.

## Updates über Moonraker

`install.sh` gibt den passenden Block für `moonraker.conf` aus. Das Update betrifft
nur die Software auf dem Pi, **nicht den Sketch im Arduino**. Passt er nicht mehr,
zeigt das Display „Sketch veraltet“.

## Ohne Drucker ausprobieren

```bash
python3 -m moonraker_lcd simulate --preview
```

Ohne `--preview` läuft der Scheindrucker auf dem echten Display, samt Drehgeber.
`pages` zeigt alle Seiten des echten Druckers einmal im Terminal. Alle Befehle im
Projektordner ausführen.

## Fehlersuche

| Beobachtung | Ursache |
|---|---|
| „waiting for host“, dann dunkel | Dienst läuft nicht oder falscher Port: `journalctl -u moonraker-lcd -n 30` |
| Beleuchtet, aber leer oder Kästchen | Kontrast-Poti; sonst SDA/SCL prüfen |
| Log: „Arduino findet kein LCD“ | Verdrahtung SDA→A4, SCL→A5, GND, 5V |
| Log: „keine Kennung“ | falscher Port oder anderer Sketch auf dem Arduino |
| Drehrichtung verkehrt | `[encoder] reverse = yes` |
| Eine Rastung springt zwei Seiten oder keine | Der Sketch erkennt 2 oder 4 Flanken pro Rastung selbst (ab Sketch 1.0.1). Sonst `ENCODER_STEPS` im Sketch fest auf 2 bzw. 4 |
| Falsche Zeichen statt ä, ö, °  | `[display] charset = a02` oder `ascii` |
| „kein Moonraker“ | `[moonraker] url`; bei anderem Rechner `trusted_clients` oder `api_key` |

## Entwicklung

```bash
python3 -m unittest discover -s tests -t .
python3 tests/integration_moonraker.py
```

Die Unit-Tests brauchen keine Fremdpakete. Mit einem C++-Compiler läuft dabei der
**echte Sketch** gegen ein Modell von LCD und Drehgeber. Der Integrationstest
braucht zusätzlich `websockets` und `pyserial`. Das Protokoll steht in
[docs/protokoll.md](docs/protokoll.md).

Release schneiden: `python3 scripts/release.py patch|minor|major`
(`--dry-run` zeigt nur an).

## Lizenz

MIT, siehe [LICENSE](LICENSE).
