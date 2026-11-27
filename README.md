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
| Drehen | nächste/vorige Seite | Auswahl bewegen, Temperatur ändern |
| Drücken | Menü öffnen | auswählen, Temperatur übernehmen |
| Lang drücken | zur ersten Seite | eine Ebene zurück |

Im Menü stehen außerdem:

* **Homing ›** – alle Achsen, X und Y zusammen, X, Y oder Z (`G28`), nur ohne Druck.
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
