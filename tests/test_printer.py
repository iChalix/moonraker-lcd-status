import unittest

from moonraker_lcd import simulator
from moonraker_lcd.config import Config
from moonraker_lcd.printer import Phase, is_extruder

from tests.helpers import make_printer, printing_printer


class PhaseTest(unittest.TestCase):
    def test_offline(self):
        printer = make_printer()
        printer.set_online(False)
        self.assertIs(printer.phase, Phase.OFFLINE)
        self.assertEqual(printer.heaters, [])

    def test_klippy_states(self):
        for state, phase in (
            ("startup", Phase.STARTUP), ("error", Phase.ERROR), ("shutdown", Phase.SHUTDOWN),
            ("disconnected", Phase.DISCONNECTED), ("", Phase.DISCONNECTED), ("ready", Phase.STANDBY),
        ):
            printer = make_printer()
            printer.set_klippy(state)
            self.assertIs(printer.phase, phase, state)

    def test_webhooks_shutdown_counts_without_notification(self):
        printer = make_printer(objects={"webhooks": {"state": "shutdown", "state_message": "MCU 'mcu'\nshutdown"}})
        self.assertIs(printer.phase, Phase.SHUTDOWN)
        self.assertEqual(printer.fault_message, "MCU 'mcu' shutdown")

    def test_print_states(self):
        for state, phase in (
            ("printing", Phase.PRINTING), ("paused", Phase.PAUSED), ("complete", Phase.COMPLETE),
            ("cancelled", Phase.CANCELLED), ("error", Phase.PRINT_ERROR), ("standby", Phase.STANDBY),
        ):
            self.assertIs(make_printer(objects={"print_stats": {"state": state}}).phase, phase)

    def test_busy(self):
        self.assertIs(make_printer(objects={"idle_timeout": {"state": "Printing"}}).phase, Phase.BUSY)

    def test_pause_resume_while_print_stats_lags(self):
        printer = make_printer(objects={"print_stats": {"state": "printing"}, "pause_resume": {"is_paused": True}})
        self.assertIs(printer.phase, Phase.PAUSED)


class JobTest(unittest.TestCase):
    def test_progress_skips_header_bytes(self):
        printer = printing_printer()
        printer.set_metadata(simulator.FILENAME, {"gcode_start_byte": 200000, "gcode_end_byte": 800000})
        printer.update_objects({"virtual_sdcard": {"file_position": 500000, "progress": 0.5}})
        self.assertAlmostEqual(printer.progress, 0.5)
        printer.update_objects({"virtual_sdcard": {"file_position": 100000}})
        self.assertEqual(printer.progress, 0.0)

    def test_progress_sources(self):
        config = Config()
        config.progress.source = "display"
        printer = printing_printer(config)
        printer.update_objects({"display_status": {"progress": 0.7}})
        self.assertEqual(printer.progress, 0.7)
        config.progress.source = "sdcard"
        self.assertEqual(printer.progress, 0.42)

    def test_metadata_of_another_file_is_ignored(self):
        printer = printing_printer()
        printer.update_objects({"print_stats": {"filename": "anders.gcode"}})
        self.assertIsNone(printer._meta.get("estimated_time"))

    def test_remaining(self):
        config = Config()
        printer = printing_printer(config, 0.5)
        self.assertAlmostEqual(printer.remaining, 2160)
        config.progress.eta = "slicer"
        self.assertAlmostEqual(printer.remaining, 2160)
        config.progress.eta = "file"
        printer.update_objects({"print_stats": {"print_duration": 4000}})
        self.assertAlmostEqual(printer.remaining, 4000)

    def test_remaining_unknown_at_the_start_without_metadata(self):
        printer = make_printer(objects={"print_stats": {"state": "printing", "filename": "x.gcode", "print_duration": 5}})
        self.assertIsNone(printer.remaining)
        self.assertIsNone(printer.eta(0))

    def test_layers_from_klipper_then_from_height(self):
        printer = printing_printer()
        self.assertEqual(printer.layers, (84, 200))
        printer.update_objects({"print_stats": {"info": {"total_layer": None, "current_layer": None}},
                                "gcode_move": {"gcode_position": [0, 0, 4.0, 0]}})
        self.assertEqual(printer.layers, (20, 200))

    def test_layers_unknown(self):
        self.assertIsNone(make_printer().layers)

    def test_job_name(self):
        printer = make_printer(objects={"print_stats": {"filename": "ordner/Teil v1.2.gcode"}})
        self.assertEqual(printer.job_name, "Teil v1.2")

    def test_broken_values_do_not_raise(self):
        printer = make_printer(objects={
            "print_stats": {"state": "printing", "print_duration": None, "info": None, "filename": None},
            "virtual_sdcard": {"progress": None, "file_position": None},
            "gcode_move": {"gcode_position": None, "speed_factor": None},
            "extruder": {"temperature": None, "target": None}, "display_status": None,
        })
        self.assertEqual(printer.progress, 0.0)
        self.assertEqual(printer.message, "")
        self.assertIsNotNone(printer.heaters)


class HeaterTest(unittest.TestCase):
    def test_extruder_names(self):
        self.assertTrue(is_extruder("extruder") and is_extruder("extruder1"))
        self.assertFalse(is_extruder("extruder_stepper foo") or is_extruder("heater_bed"))

    def test_discovery(self):
        config = Config()
        config.hidden = ("temperature_sensor geheim",)
        wanted = make_printer(config).subscription([
            "webhooks", "print_stats", "extruder", "extruder1", "heater_bed", "heater_generic chamber",
            "temperature_fan exhaust", "temperature_sensor pi", "temperature_sensor geheim",
            "extruder_stepper x", "gcode_macro FOO", "toolhead",
        ])
        self.assertEqual(
            set(wanted),
            {"webhooks", "print_stats", "extruder", "extruder1", "heater_bed", "heater_generic chamber",
             "temperature_fan exhaust", "temperature_sensor pi", "toolhead"},
        )

    def test_order_and_names(self):
        config = Config()
        config.names = {"heater_generic chamber": "Bauraum"}
        printer = make_printer(config)
        self.assertEqual([h.name for h in printer.heaters], ["Hotend", "Bett", "Bauraum", "Raspberry pi"])

    def test_active_extruder_of_several(self):
        printer = make_printer(objects={
            "extruder1": {"temperature": 100, "target": 0}, "toolhead": {"extruder": "extruder1"}})
        self.assertEqual(printer.extruder.object, "extruder1")
        self.assertEqual([h.name for h in printer.heaters][:2], ["Hotend 0", "Hotend 1"])

    def test_printer_without_bed(self):
        printer = make_printer()
        del printer.objects["heater_bed"]
        self.assertIsNone(printer.bed)


class SystemTest(unittest.TestCase):
    def test_addresses(self):
        printer = make_printer()
        printer.update_system_info({"system_info": {"network": {
            "wlan0": {"ip_addresses": [
                {"family": "ipv6", "address": "fe80::1", "is_link_local": True},
                {"family": "ipv4", "address": "192.0.2.7", "is_link_local": False}]},
            "eth0": {"ip_addresses": []}}}})
        self.assertEqual(printer.addresses, ["192.0.2.7"])


if __name__ == "__main__":
    unittest.main()
