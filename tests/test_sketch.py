"""Der echte Sketch gegen ein LCD-Modell: Protokoll, Anzeige, Drehgeber."""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import arduino_host

from moonraker_lcd import protocol, screen


@unittest.skipUnless(arduino_host.compiler() and os.name == "posix", "kein C++-Compiler")
class SketchTest(unittest.TestCase):
    cols, rows = 20, 4

    @classmethod
    def setUpClass(cls):
        cls.directory = arduino_host.temporary_directory()
        cls.binary = arduino_host.build(cls.directory.name, cls.cols, cls.rows)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.arduino = arduino_host.Arduino(self.binary)
        self.fd = os.open(self.arduino.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.buffer = b""
        # die Kennung beim Start
        self.assertEqual(self.receive()[:4], b"IMLS")

    def tearDown(self):
        shown = self.arduino.show()
        os.close(self.fd)
        self.arduino.close()
        self.assertEqual(shown.errors, 0, "LCD-Zeitverhalten/Wire-Puffer verletzt")
        self.assertEqual(shown.overflow, 0, "Empfangspuffer uebergelaufen")

    def receive(self, timeout=3.0):
        end = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            try:
                self.buffer += os.read(self.fd, 256)
            except BlockingIOError:
                if time.monotonic() > end:
                    return None
                time.sleep(0.002)
        line, self.buffer = self.buffer.split(b"\n", 1)
        return protocol.decode(line)

    def send(self, payload):
        os.write(self.fd, protocol.encode(payload))
        return self.receive()

    def settled(self, seconds=0.4):
        time.sleep(seconds)
        return self.arduino.show()

    def test_boot_screen(self):
        shown = self.settled()
        self.assertTrue(shown.text[0].startswith("Moonraker LCD"))
        self.assertTrue(shown.on and shown.light)

    def test_ident(self):
        ident = protocol.parse_ident(self.send(protocol.QUERY))
        self.assertEqual((ident.protocol, ident.cols, ident.rows), (protocol.VERSION, self.cols, self.rows))
        self.assertEqual(ident.address, 0x27)

    def test_rows_arrive_exactly(self):
        lines = [("Zeile %d " % i + "abcdefghijklmnopqrstuvwxyz")[: self.cols] for i in range(self.rows)]
        for index, line in enumerate(lines):
            self.assertEqual(self.send(protocol.row(index, screen.to_codes(line))), b"K")
        self.assertEqual(self.settled().text, lines)

    def test_special_characters(self):
        line = screen.fit("21° äöüßÄÜ*" + screen.BAR, self.cols)
        self.send(protocol.row(0, screen.to_codes(line)))
        self.assertEqual(self.settled().text[0], line)

    def test_short_row_is_padded(self):
        self.send(protocol.row(1, b"x" * self.cols))
        self.send(protocol.row(1, b"kurz"))
        self.assertEqual(self.settled().text[1], "kurz".ljust(self.cols))

    def test_burst_without_waiting_for_the_display(self):
        for number in range(30):
            for index in range(self.rows):
                self.assertEqual(self.send(protocol.row(index, b"%020d" % number)[: 2 + self.cols]), b"K")
        self.assertEqual(self.settled().text[0], ("%020d" % 29)[: self.cols])

    def test_glyphs(self):
        before = self.arduino.show().cgram
        for index, char in enumerate(screen.GLYPH_LIST):
            self.assertEqual(self.send(protocol.glyph(index, screen.GLYPHS[char])), b"K")
        shown = self.settled()
        expected = 0
        for char in screen.GLYPH_LIST:
            for value in screen.GLYPHS[char]:
                expected = (expected * 31 + value) & 0xFFFFFFFF
        self.assertNotEqual(shown.cgram, before)
        self.assertEqual(shown.cgram, expected)

    def test_backlight_and_clear(self):
        self.send(protocol.row(0, b"weg"))
        self.assertEqual(self.send(protocol.backlight(False)), b"K")
        self.assertFalse(self.settled().light)
        # Schreiben darf die Beleuchtung nicht wieder einschalten
        self.send(protocol.row(1, b"dunkel"))
        self.assertFalse(self.settled().light)
        self.send(protocol.CLEAR)
        self.send(protocol.backlight(True))
        shown = self.settled()
        self.assertTrue(shown.light)
        self.assertEqual(shown.text, [" " * self.cols] * self.rows)

    def test_bad_messages_are_rejected(self):
        for raw, reply in (
            (b"L0hallo*00\n", b"NC"), (b"hallo\n", b"NF"), (b"L0" + b"x" * 45 + b"*00\n", b"NF"),
            (protocol.encode(b"L9falsch"), b"NU"), (protocol.encode(b"Qx"), b"NU"),
            (protocol.encode(b"G8" + b"00" * 8), b"NU"), (protocol.encode(b"G0zz" + b"00" * 7), b"NU"),
        ):
            os.write(self.fd, raw)
            self.assertEqual(self.receive(), reply, raw)
        # danach geht es normal weiter
        self.assertEqual(self.send(protocol.PING), b"K")

    def test_rotation(self):
        self.arduino.command("CW")
        self.assertEqual(protocol.parse_rotation(self.receive()), 1)
        self.arduino.command("CCW")
        self.assertEqual(protocol.parse_rotation(self.receive()), -1)

    def test_fast_rotation_loses_nothing(self):
        for _ in range(25):
            self.arduino.command("CW")
        total = 0
        while True:
            message = self.receive(0.5)
            if message is None:
                break
            total += protocol.parse_rotation(message)
        self.assertEqual(total, 25)

    def rotations(self, timeout=0.8):
        found = []
        while True:
            message = self.receive(timeout)
            if message is None:
                return found
            found.append(protocol.parse_rotation(message))

    def test_two_steps_per_detent_are_detected(self):
        # erste Rastung endet in der Mittelstellung, zaehlt nach der Erkennung
        self.arduino.command("HCW")
        self.assertEqual(protocol.parse_rotation(self.receive()), 1)
        for command, expected in (("HCW", 1), ("HCW", 1), ("HCCW", -1), ("HCCW", -1), ("HCCW", -1)):
            self.arduino.command(command)
            self.assertEqual(protocol.parse_rotation(self.receive(0.3)), expected, command)
        for _ in range(12):
            self.arduino.command("HCW")
        self.assertEqual(sum(self.rotations()), 12)

    def test_four_steps_per_detent_stay_four(self):
        for _ in range(3):
            self.arduino.command("CW")
            self.assertEqual(self.rotations(), [1])  # auch nach einer Pause keine Umstellung

    def test_button(self):
        self.arduino.command("CLICK")
        self.assertEqual(self.receive(), b"S")
        self.arduino.command("LONG")
        self.assertEqual(self.receive(), b"H")
        # langes Druecken loest keinen zusaetzlichen Klick aus, Prellen auch nicht
        self.arduino.command("BOUNCE")
        self.assertIsNone(self.receive(0.5))

    def test_goes_dark_without_host_and_wakes_up(self):
        self.send(protocol.row(0, b"da"))
        self.arduino.command("SILENCE 31000")
        shown = self.settled()
        self.assertFalse(shown.light or shown.on)
        self.send(protocol.PING)
        shown = self.settled()
        self.assertTrue(shown.light and shown.on)
        self.assertTrue(shown.text[0].startswith("da"))

    def test_wrong_messages_do_not_keep_the_display_awake(self):
        self.arduino.command("SILENCE 31000")
        self.settled()
        os.write(self.fd, b"Muell\n")
        self.receive()
        self.assertFalse(self.settled().light)

    def test_backlight_off_survives_sleep(self):
        self.send(protocol.backlight(False))
        self.arduino.command("SILENCE 31000")
        self.settled()
        self.send(protocol.PING)
        shown = self.settled()
        self.assertTrue(shown.on)
        self.assertFalse(shown.light)

    def test_reinit_repairs_a_garbled_display(self):
        line = screen.fit("Inhalt Ä", self.cols)
        for index, char in enumerate(screen.GLYPH_LIST):
            self.send(protocol.glyph(index, screen.GLYPHS[char]))
        self.send(protocol.row(0, screen.to_codes(line)))
        good = self.settled()
        self.arduino.command("GARBLE")
        self.assertNotEqual(self.arduino.show().text, good.text)
        self.assertEqual(self.send(protocol.REINIT), b"K")
        repaired = self.settled()
        self.assertEqual(repaired.text, good.text)
        self.assertEqual(repaired.cgram, good.cgram)

    def test_replugged_display_recovers_alone(self):
        self.send(protocol.row(0, b"bleibt"))
        self.settled()
        self.arduino.command("UNPLUG")
        self.send(protocol.row(1, b"neu"))
        time.sleep(0.3)
        self.assertEqual(protocol.parse_ident(self.send(protocol.QUERY)).address, 0)
        self.arduino.command("PLUG")
        shown = self.settled(2.6)
        self.assertTrue(shown.text[0].startswith("bleibt"))
        self.assertTrue(shown.text[1].startswith("neu"))
        self.assertTrue(shown.on and shown.light)


class SmallSketchTest(SketchTest):
    cols, rows = 16, 2


if __name__ == "__main__":
    unittest.main()
