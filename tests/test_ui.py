import copy
import random
import unittest

from moonraker_lcd import screen, simulator
from moonraker_lcd.config import Config, MenuItemConfig, PreheatConfig

from tests.helpers import WALL, make_printer, make_ui, printing_printer


class PagesTest(unittest.TestCase):
    def test_printing(self):
        ui, _ = make_ui(printing_printer())
        lines = ui.render(0.0, WALL)
        self.assertEqual(lines[0], "Benchy_0.2mm_PLA_BLV")
        self.assertTrue(lines[1].endswith("  42%"))
        self.assertEqual(lines[2], "T235/235°    B60/60°")
        self.assertEqual(lines[3], "S 84/200  Ende 14:41")

    def test_idle(self):
        ui, _ = make_ui(make_printer())
        self.assertEqual(ui.render(0.0, WALL), [
            "drucker       bereit", "Hotend         24.1°", "Bett           22.4°", "Di 24.11.      14:00"])

    def test_english_and_12h(self):
        config = Config()
        config.display.language = "en"
        config.display.clock_12h = True
        ui, _ = make_ui(make_printer(config), config)
        self.assertEqual(ui.render(0.0, WALL)[3], "Tue 24 Nov     2:00p")

    def test_fault_shows_the_message(self):
        printer = make_printer()
        printer.set_klippy("shutdown", "Heater extruder not heating at expected rate")
        ui, _ = make_ui(printer)
        self.assertEqual(ui.render(0.0, WALL)[:3], ["   Klipper-Stopp    ", "Heater extruder not ", "heating at expected "])

    def test_m117(self):
        printer = printing_printer()
        printer.update_objects({"display_status": {"message": "Filament wechseln"}})
        ui, _ = make_ui(printer)
        titles = {ui.render(float(t), WALL)[0].strip() for t in range(0, 32, 4)}
        self.assertIn("Filament wechseln", titles)

    def test_every_page_always_has_the_exact_size(self):
        """Zufaellige Zustaende in allen Groessen und Sprachen."""
        rng = random.Random(1)
        for _ in range(400):
            config = Config()
            config.display.language = rng.choice(["de", "en"])
            config.display.clock_12h = rng.random() < 0.5
            objects = copy.deepcopy(simulator.base_objects())
            objects.update(copy.deepcopy(simulator.printing(rng.random())))
            objects["print_stats"]["state"] = rng.choice(
                ["standby", "printing", "paused", "complete", "cancelled", "error"])
            objects["print_stats"]["filename"] = rng.choice(["", simulator.FILENAME, "x" * 90 + ".gcode"])
            objects["print_stats"]["info"] = rng.choice([None, {"total_layer": 12345, "current_layer": 9999}, {}])
            objects["print_stats"]["total_duration"] = rng.choice([0, 1e3, 1e6])
            objects["display_status"]["message"] = rng.choice([None, "", "kurz", "Ü" * 77, "a\nb"])
            objects["extruder"] = {"temperature": rng.choice([-5.0, 21.3, 299.9]), "target": rng.choice([0, 300])}
            for name in rng.sample(sorted(objects), rng.randrange(6)):
                del objects[name]
            for index in range(rng.randrange(9)):
                objects["temperature_sensor sehr_langer_name_%d" % index] = {"temperature": 20.0 + index}
            printer = make_printer(config)
            printer.reset_objects()
            printer.update_objects(objects)
            printer.set_online(rng.random() < 0.95)
            printer.set_klippy(rng.choice(["ready"] * 8 + ["shutdown", "error", "startup", ""]), "Fehler " * 40)
            if rng.random() < 0.7:
                printer.set_metadata(simulator.FILENAME, simulator.METADATA)
            cols, rows = rng.choice([(20, 4), (16, 2), (16, 4), (20, 2), (8, 2)])
            ui, _ = make_ui(printer, config, cols, rows)
            for step in range(6):
                now = rng.random() * 1000
                lines = ui.render(now, WALL)
                self.assertEqual([len(line) for line in lines], [cols] * rows, lines)
                self.assertEqual(len(screen.to_codes(lines[0])), cols)
                ui.rotate(1, now)
            ui.click(now)
            self.assertEqual([len(line) for line in ui.render(now, WALL)], [cols] * rows)


class NavigationTest(unittest.TestCase):
    def test_rotate_through_pages_and_back(self):
        ui, _ = make_ui(make_printer())
        first = ui.render(0.0, WALL)
        seen = [first]
        for _ in range(3):
            ui.rotate(1, 1.0)
            seen.append(ui.render(1.0, WALL))
        self.assertEqual(len({tuple(page) for page in seen}), 4)
        ui.rotate(1, 1.0)
        self.assertEqual(ui.render(1.0, WALL), first)
        ui.rotate(-1, 1.0)
        self.assertEqual(ui.render(1.0, WALL), seen[3])

    def test_returns_to_first_page(self):
        ui, _ = make_ui(make_printer())
        first = ui.render(0.0, WALL)
        ui.rotate(1, 1.0)
        self.assertNotEqual(ui.render(1.0, WALL), first)
        self.assertEqual(ui.render(62.0, WALL), first)

    def test_auto_rotate(self):
        config = Config()
        config.display.auto_rotate = 5
        ui, _ = make_ui(make_printer(config), config)
        seen = {tuple(ui.render(float(t), WALL)) for t in range(100, 140)}
        self.assertGreaterEqual(len(seen), 4)

    def test_busy_does_not_reset_the_page(self):
        printer = make_printer()
        ui, _ = make_ui(printer)
        ui.render(0.0, WALL)
        ui.rotate(1, 1.0)
        page = ui.render(1.0, WALL)
        printer.update_objects({"idle_timeout": {"state": "Printing"}})
        self.assertEqual(ui.render(2.0, WALL), page)

    def test_more_sensors_make_more_temperature_pages(self):
        printer = make_printer(objects={"temperature_sensor s%d" % i: {"temperature": 20} for i in range(6)})
        ui, _ = make_ui(printer)
        ui.render(0.0, WALL)
        texts = []
        for _ in range(3):
            ui.rotate(1, 1.0)
            texts += ui.render(1.0, WALL)
        self.assertTrue(any(line.startswith("S5") for line in texts))


class MenuTest(unittest.TestCase):
    def select(self, ui, label, now=1.0):
        ui.click(now)
        for _ in range(20):
            lines = ui.render(now, WALL)
            if any(line.startswith(">" + label) for line in lines):
                ui.click(now)
                return
            ui.rotate(1, now)
        self.fail("%r nicht im Menue: %r" % (label, lines))

    def labels(self, ui):
        return [action.label for action in ui.actions()]

    def test_entries_depend_on_the_state(self):
        ui, _ = make_ui(make_printer())
        self.assertEqual(self.labels(ui), ["Zurück", "Homing", "Heizen", "Anzeige auffrischen"])
        ui, _ = make_ui(printing_printer())
        self.assertEqual(self.labels(ui), ["Zurück", "Pause", "Abbrechen", "Heizen", "Anzeige auffrischen"])
        printer = printing_printer()
        printer.update_objects({"print_stats": {"state": "paused"}})
        ui, _ = make_ui(printer)
        self.assertEqual(self.labels(ui)[1:3], ["Fortsetzen", "Abbrechen"])
        printer.set_klippy("shutdown")
        self.assertIn("Firmware-Neustart", self.labels(ui))

    def test_pause_without_question(self):
        ui, calls = make_ui(printing_printer())
        self.select(ui, "Pause")
        self.assertEqual(calls[0].method, "printer.print.pause")

    def test_cancel_asks_and_defaults_to_no(self):
        ui, calls = make_ui(printing_printer())
        self.select(ui, "Abbrechen")
        lines = ui.render(1.0, WALL)
        self.assertEqual(lines[0].strip(), "Abbrechen")
        self.assertIn(">Nein", lines[3])
        ui.click(1.0)
        self.assertEqual(calls, [])
        self.select(ui, "Abbrechen")
        ui.rotate(1, 1.0)
        self.assertIn(">Ja", ui.render(1.0, WALL)[3])
        ui.click(1.0)
        self.assertEqual(calls[0].method, "printer.print.cancel")

    def test_opening_and_double_click_do_nothing_dangerous(self):
        """Mehrfaches Druecken oeffnet und schliesst das Menue nur."""
        for printer in (printing_printer(), make_printer()):
            ui, calls = make_ui(printer)
            for _ in range(9):
                ui.click(1.0)
                ui.render(1.0, WALL)
            self.assertEqual(calls, [])

    def test_selection_never_slips_to_another_command(self):
        """Wechselt der Zustand im offenen Menue, bleibt die Auswahl oder sie wird 'Zurueck'."""
        printer = printing_printer()
        ui, calls = make_ui(printer)
        ui.render(1.0, WALL)
        ui.click(1.0)
        ui.rotate(1, 1.0)  # Pause
        self.assertTrue(any(line.startswith(">Pause") for line in ui.render(1.0, WALL)))
        printer.update_objects({"print_stats": {"state": "paused"}})
        self.assertTrue(any(line.startswith(">Zurück") for line in ui.render(1.1, WALL)))
        ui.click(1.2)
        self.assertEqual(calls, [])

    def test_stale_selection_is_checked_again_when_executed(self):
        printer = printing_printer()
        ui, calls = make_ui(printer)
        self.select(ui, "Abbrechen")
        ui.rotate(1, 1.0)
        printer.update_objects({"print_stats": {"state": "complete"}})
        ui.click(1.1)  # noch vor dem naechsten Zeichnen
        self.assertEqual(calls, [])
        self.assertIn("Jetzt nicht möglich", "".join(ui.render(1.2, WALL)))

    def test_menu_closes_by_itself(self):
        ui, _ = make_ui(printing_printer())
        page = ui.render(1.0, WALL)
        ui.click(1.0)
        self.assertNotEqual(ui.render(2.0, WALL), page)
        self.assertEqual(ui.render(22.0, WALL)[2:], page[2:])
        self.select(ui, "Abbrechen", 30.0)
        self.assertNotIn(">Nein", "".join(ui.render(51.0, WALL)))

    def test_long_press_goes_back(self):
        ui, calls = make_ui(printing_printer())
        page = ui.render(1.0, WALL)
        self.select(ui, "Abbrechen")
        ui.long_press(1.0)
        self.assertTrue(ui.render(1.0, WALL)[0].startswith((" ", ">")))
        ui.long_press(1.0)
        self.assertEqual(ui.render(1.0, WALL), page)
        self.assertEqual(calls, [])

    def test_custom_items(self):
        config = Config()
        config.menu.items = [
            MenuItemConfig("Vorheizen", gcode="M140 S60"),
            MenuItemConfig("Licht", power_device="licht", when="always"),
        ]
        ui, calls = make_ui(make_printer(config), config)
        self.select(ui, "Vorheizen")
        self.assertEqual((calls[0].kind, calls[0].payload), ("gcode", "M140 S60"))
        ui, calls = make_ui(printing_printer(config), config)
        self.assertNotIn("Vorheizen", self.labels(ui))
        self.select(ui, "Licht")
        self.assertEqual((calls[0].kind, calls[0].payload), ("power", "licht"))

    def test_custom_gcode_is_hidden_while_klipper_is_down(self):
        config = Config()
        config.menu.items = [MenuItemConfig("Makro", gcode="X", when="always")]
        printer = make_printer(config)
        printer.set_klippy("shutdown")
        ui, _ = make_ui(printer, config)
        self.assertNotIn("Makro", self.labels(ui))

    def test_host_shutdown_only_when_enabled_and_never_while_printing(self):
        config = Config()
        config.menu.shutdown = config.menu.reboot = True
        ui, calls = make_ui(make_printer(config), config)
        self.assertIn("Pi herunterfahren", self.labels(ui))
        self.select(ui, "Pi herunterfahren")
        self.assertEqual(calls, [])
        ui, _ = make_ui(printing_printer(config), config)
        self.assertNotIn("Pi herunterfahren", self.labels(ui))
        self.assertNotIn("Pi neu starten", self.labels(ui))

    def test_disabled_menu(self):
        config = Config()
        config.menu.enabled = False
        ui, _ = make_ui(make_printer(config), config)
        page = ui.render(1.0, WALL)
        ui.click(1.0)
        self.assertEqual(ui.render(1.0, WALL), page)

    def test_notice(self):
        ui, _ = make_ui(make_printer())
        ui.notice("Hallo", 1.0)
        self.assertIn("Hallo", "".join(ui.render(2.0, WALL)))
        self.assertNotIn("Hallo", "".join(ui.render(6.0, WALL)))

    def test_small_display(self):
        ui, calls = make_ui(printing_printer(), cols=16, rows=2)
        self.select(ui, "Abbrechen")
        self.assertIn(">Nein", ui.render(1.0, WALL)[1])


class HomingHeatingTest(unittest.TestCase):
    select = MenuTest.select

    def menu(self, ui, now=1.0):
        return [line.strip() for line in ui.render(now, WALL)]

    def test_homing(self):
        ui, calls = make_ui(make_printer())
        self.select(ui, "Homing")
        self.assertEqual([a.label for a in ui.actions("home")],
                         ["Zurück", "Alle Achsen", "X- und Y-Achse", "X-Achse", "Y-Achse", "Z-Achse"])
        self.select_here(ui, "Z-Achse")
        self.assertEqual((calls[0].kind, calls[0].payload), ("gcode", "G28 Z"))
        self.assertNotIn(">", "".join(ui.render(1.0, WALL)))  # Menue geschlossen
        self.select(ui, "Homing")
        self.select_here(ui, "X- und Y")
        self.assertEqual(calls[1].payload, "G28 X Y")

    def select_here(self, ui, label, now=1.0):
        """Im schon offenen (Unter-)Menue auswaehlen."""
        for _ in range(20):
            lines = ui.render(now, WALL)
            if any(line.startswith(">" + label) for line in lines):
                ui.click(now)
                return
            ui.rotate(1, now)
        self.fail("%r nicht im Menue: %r" % (label, lines))

    def test_no_homing_while_printing(self):
        ui, _ = make_ui(printing_printer())
        self.assertNotIn("Homing", [a.label for a in ui.actions()])
        self.assertEqual([a.label for a in ui.actions("home")], ["Zurück"])

    def test_submenus_can_be_switched_off(self):
        config = Config()
        config.menu.homing = config.menu.heating = False
        ui, _ = make_ui(make_printer(config), config)
        self.assertEqual([a.label for a in ui.actions()], ["Zurück", "Anzeige auffrischen"])

    def test_preheat(self):
        ui, calls = make_ui(make_printer())
        self.select(ui, "Heizen")
        self.assertEqual(self.menu(ui), [">Zurück", "PLA 200°/60°", "PETG 240°/80°", "ABS 250°/100°"])
        self.select_here(ui, "PLA")
        self.assertEqual(calls[0].payload, "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=200\n"
                                           "SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=60")

    def test_own_preheats_and_cooldown(self):
        config = Config()
        config.menu.preheats = [PreheatConfig("Nur Bett", bed=70)]
        ui, calls = make_ui(make_printer(config), config)
        self.assertEqual([a.label for a in ui.actions("heat")],
                         ["Zurück", "Nur Bett 70°", "Hotend", "Bett", "Abkühlen"])
        self.select(ui, "Heizen")
        self.select_here(ui, "Abkühlen")
        self.assertEqual(calls[0].payload, "TURN_OFF_HEATERS")

    def test_while_printing_only_targets(self):
        ui, _ = make_ui(printing_printer())
        self.assertEqual([a.label for a in ui.actions("heat")], ["Zurück", "Hotend", "Bett"])
        self.select(ui, "Heizen")
        self.assertEqual(self.menu(ui)[1:3], ["Hotend: 235°", "Bett: 60°"])

    def test_set_target_with_the_encoder(self):
        ui, calls = make_ui(make_printer())
        self.select(ui, "Heizen")
        self.select_here(ui, "Hotend")
        # Ziel war aus: Start bei der ersten Vorgabe
        self.assertEqual(ui.render(1.0, WALL), [
            "Hotend              ", "Ist              24°", "Ziel            200°", "     Klick = OK     "])
        ui.rotate(3, 1.0)
        self.assertEqual(ui.render(1.0, WALL)[2], "Ziel            215°")
        ui.click(1.0)
        self.assertEqual(calls[0].payload, "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=215")
        # das Heizen-Menue bleibt offen
        self.assertTrue(any(line.startswith(">Hotend: aus") for line in ui.render(1.0, WALL)))

    def test_target_limits(self):
        ui, calls = make_ui(make_printer())
        self.select(ui, "Heizen")
        self.select_here(ui, "Bett")
        ui.rotate(-50, 1.0)
        self.assertEqual(ui.render(1.0, WALL)[2], "Ziel             aus")
        ui.rotate(500, 1.0)
        self.assertEqual(ui.render(1.0, WALL)[2], "Ziel            120°")  # max_temp aus Klipper
        ui.click(1.0)
        self.assertEqual(calls[0].payload, "SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=120")

    def test_target_during_print_starts_at_the_current_target(self):
        ui, calls = make_ui(printing_printer())
        self.select(ui, "Heizen")
        self.select_here(ui, "Hotend")
        ui.rotate(-1, 1.0)
        ui.click(1.0)
        self.assertEqual(calls[0].payload, "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=230")

    def test_long_press_goes_back_one_level(self):
        ui, calls = make_ui(make_printer())
        page = ui.render(1.0, WALL)
        self.select(ui, "Heizen")
        self.select_here(ui, "Hotend")
        ui.long_press(1.0)  # Einstellen abbrechen
        self.assertTrue(any(line.startswith(">Hotend") for line in ui.render(1.0, WALL)))
        ui.long_press(1.0)  # ins Hauptmenue, Auswahl bleibt auf "Heizen"
        self.assertTrue(any(line.startswith(">Heizen") for line in ui.render(1.0, WALL)))
        ui.long_press(1.0)
        self.assertEqual(ui.render(1.0, WALL), page)
        self.assertEqual(calls, [])

    def test_back_returns_to_the_main_menu(self):
        ui, _ = make_ui(make_printer())
        self.select(ui, "Homing")
        ui.click(1.0)  # "Zurueck"
        self.assertTrue(any(line.startswith(">Homing") for line in ui.render(1.0, WALL)))

    def test_editing_stops_when_klipper_stops(self):
        printer = make_printer()
        ui, calls = make_ui(printer)
        self.select(ui, "Heizen")
        self.select_here(ui, "Hotend")
        printer.set_klippy("shutdown")
        self.assertNotIn("Ziel", "".join(ui.render(1.1, WALL)))
        ui.click(1.2)
        self.assertEqual(calls, [])

    def test_editing_times_out(self):
        ui, calls = make_ui(make_printer())
        page = ui.render(1.0, WALL)
        self.select(ui, "Heizen")
        self.select_here(ui, "Hotend")
        self.assertEqual(ui.render(30.0, WALL), page)
        self.assertEqual(calls, [])

    def test_small_display(self):
        ui, _ = make_ui(make_printer(), cols=16, rows=2)
        self.select(ui, "Heizen")
        self.select_here(ui, "Hotend")
        self.assertEqual(ui.render(1.0, WALL), ["Hotend       24°", "Ziel        200°"])


class BacklightTest(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.config.display.backlight_timeout = 10

    def test_always_on_by_default(self):
        ui, _ = make_ui(make_printer())
        ui.render(0.0, WALL)
        self.assertTrue(ui.backlight(1e6))

    def test_off_when_idle_and_first_input_only_wakes(self):
        ui, _ = make_ui(make_printer(self.config), self.config)
        first = ui.render(0.0, WALL)
        self.assertTrue(ui.backlight(500))
        self.assertFalse(ui.backlight(601))
        ui.click(700)
        self.assertTrue(ui.backlight(700))
        self.assertEqual(ui.render(700, WALL), first)  # kein Menue
        ui.click(701)
        self.assertNotEqual(ui.render(701, WALL), first)

    def test_on_while_printing_heating_or_faulted(self):
        ui, _ = make_ui(printing_printer(self.config), self.config)
        ui.render(0.0, WALL)
        self.assertTrue(ui.backlight(1e6))
        ui, _ = make_ui(make_printer(self.config, {"extruder": {"target": 200}}), self.config)
        ui.render(0.0, WALL)
        self.assertTrue(ui.backlight(1e6))
        printer = make_printer(self.config)
        printer.set_klippy("shutdown")
        ui, _ = make_ui(printer, self.config)
        ui.render(0.0, WALL)
        self.assertTrue(ui.backlight(1e6))


if __name__ == "__main__":
    unittest.main()
