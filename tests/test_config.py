import os
import tempfile
import unittest

from moonraker_lcd import config as config_module

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(text):
    with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False, encoding="utf-8") as handle:
        handle.write(text)
    try:
        return config_module.load(handle.name)
    finally:
        os.unlink(handle.name)


class ConfigTest(unittest.TestCase):
    def test_example_config_matches_the_defaults(self):
        example = config_module.load(os.path.join(ROOT, "config", "moonraker-lcd.conf"))
        default = config_module.Config()
        self.assertEqual(example.display, default.display)
        self.assertEqual(example.moonraker, default.moonraker)
        self.assertEqual(example.encoder, default.encoder)
        self.assertEqual(example.progress, default.progress)
        self.assertEqual(example.serial, default.serial)
        self.assertEqual(example.menu, default.menu)

    def test_dangerous_entries_are_off_by_default(self):
        menu = config_module.Config().menu
        self.assertFalse(menu.shutdown or menu.reboot)

    def test_full(self):
        cfg = load(
            "[moonraker]\nurl = http://drucker:7125\napi_key = a%b;c\n"
            "[serial]\nport = /dev/x\n"
            "[display]\nlanguage = EN\npages = status, system\nhide = temperature_sensor mcu_temp, fan\n"
            "[names]\ntemperature_sensor chamber = Kammer\nextruder = Düse\n"
            "[menu_item Licht]\npower_device = licht\nwhen = always\n"
            "[menu_item]\nlabel = Vorheizen\ngcode =\n  M140 S60 ; Bett\n  M117 100%\nconfirm = yes\n"
        )
        self.assertEqual(cfg.moonraker.url, "ws://drucker:7125/websocket")
        self.assertEqual(cfg.moonraker.api_key, "a%b;c")
        self.assertEqual(cfg.display.language, "en")
        self.assertEqual(cfg.display.pages, ("status", "system"))
        self.assertEqual(cfg.hidden, ("temperature_sensor mcu_temp", "fan"))
        self.assertEqual(cfg.names["temperature_sensor chamber"], "Kammer")
        light, heat = cfg.menu.items
        self.assertEqual((light.label, light.power_device, light.when), ("Licht", "licht", "always"))
        self.assertEqual(heat.gcode, "M140 S60 ; Bett\nM117 100%")
        self.assertTrue(heat.confirm)
        self.assertEqual(heat.when, "idle")

    def test_rejected(self):
        for text in (
            "[unbekannt]\na = 1\n", "[display]\nsprache = de\n", "[display]\nlanguage = xx\n",
            "[display]\npages = status, foo\n", "[display]\npages =\n", "[display]\nauto_rotate = -1\n",
            "[display]\nrefresh_interval = 0.01\n", "[serial]\nbaudrate = schnell\n",
            "[menu_item A]\n", "[menu_item A]\ngcode = G28\npower_device = x\n", "[menu_item]\ngcode = G28\n",
            "[menu_item A]\ngcode = G28\nwhen = nie\n", "[menu]\ntimeout = 0\n", "kaputt",
        ):
            with self.assertRaises(config_module.ConfigError, msg=text):
                load(text)

    def test_missing_explicit_file(self):
        with self.assertRaises(config_module.ConfigError):
            config_module.load("/gibt/es/nicht.conf")

    def test_ch340_warning(self):
        cfg = load("[serial]\nport = /dev/serial/by-id/usb-1a86_USB2.0-Ser_-if00-port0\n")
        self.assertIn("by-path", cfg.describe())


if __name__ == "__main__":
    unittest.main()
