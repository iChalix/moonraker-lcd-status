import unittest

from moonraker_lcd import protocol


class ProtocolTest(unittest.TestCase):
    def test_roundtrip(self):
        for payload in (b"?", b"L0Hallo * Welt*", bytes(range(0x20, 0x100))):
            self.assertEqual(protocol.decode(protocol.encode(payload)), payload)

    def test_known_checksum(self):
        self.assertEqual(protocol.encode(b"K"), b"K*4B\n")

    def test_control_characters_are_refused(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.encode(b"L0a\nb")

    def test_every_single_bit_error_is_detected(self):
        good = protocol.encode(b"L1T235/235")[:-1]
        for index in range(len(good)):
            for bit in range(7):
                bad = bytearray(good)
                bad[index] ^= 1 << bit
                try:
                    decoded = protocol.decode(bytes(bad))
                except protocol.ProtocolError:
                    continue
                self.assertEqual(decoded, b"L1T235/235")  # nur Gross/Klein der Hexziffer

    def test_garbage(self):
        for bad in (b"", b"K", b"*4B", b"K*ZZ", b"K*00", b"{\"status\":\"I\"}"):
            with self.assertRaises(protocol.ProtocolError, msg=bad):
                protocol.decode(bad)

    def test_ident(self):
        ident = protocol.parse_ident(b"IMLS 1 1.0.0 20 4 27")
        self.assertEqual((ident.cols, ident.rows, ident.address), (20, 4, 0x27))
        self.assertTrue(ident.lcd_found)
        self.assertFalse(protocol.parse_ident(b"IMLS 1 1.0.0 16 2 00").lcd_found)
        for bad in (b"I", b"IXYZ 1 1 20 4 27", b"IMLS a 1 20 4 27", b"IMLS 1 1 99 4 27"):
            with self.assertRaises(protocol.ProtocolError, msg=bad):
                protocol.parse_ident(bad)

    def test_longest_row_fits_the_sketch_buffer(self):
        self.assertLess(len(protocol.encode(protocol.row(3, b"x" * 20))), 40)
        self.assertLess(len(protocol.encode(protocol.glyph(7, [31] * 8))), 40)


if __name__ == "__main__":
    unittest.main()
