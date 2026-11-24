import unittest

from moonraker_lcd import screen


class CharsetTest(unittest.TestCase):
    def test_length_is_kept_for_any_text(self):
        for text in ("Größe ÄÖÜ ß °", "日本語", "école", "a​b", "½ × … –", "\\~{}|", "\t"):
            for charset in screen.CHARSETS:
                codes = screen.to_codes(text, charset)
                self.assertEqual(len(codes), len(__import__("unicodedata").normalize("NFC", text)))
                self.assertTrue(all(code >= 0x20 for code in codes), (text, charset, codes))

    def test_a00(self):
        self.assertEqual(screen.to_codes("°äöüß"), bytes([0xDF, 0xE1, 0xEF, 0xF5, 0xE2]))

    def test_a02(self):
        self.assertEqual(screen.to_codes("äÖ°", "a02"), bytes([0xE4, 0xD6, 0xB0]))

    def test_ascii(self):
        self.assertEqual(screen.to_codes("öß°", "ascii"), b"os'")

    def test_glyph_codes(self):
        self.assertEqual(len(screen.GLYPHS), 8)
        self.assertEqual(screen.to_codes(screen.BAR), bytes([0x80, 0x81, 0x82, 0x83, 0x84]))


class LayoutTest(unittest.TestCase):
    def test_spread(self):
        self.assertEqual(screen.spread("ab", "cd", 8), "ab    cd")
        self.assertEqual(screen.spread("abcdefghij", "cd", 8), "abcde cd")
        self.assertEqual(screen.spread("", "abcdefghij", 8), "abcdefgh")
        self.assertEqual(screen.spread("abcdefgh", "", 8), "abcdefgh")

    def test_bar_is_monotonic_and_fills(self):
        self.assertEqual(screen.progress_bar(0, 15), screen.BAR_EMPTY * 15)
        self.assertEqual(screen.progress_bar(1, 15), screen.BAR[4] * 15)
        self.assertEqual(screen.progress_bar(7, 15), screen.BAR[4] * 15)
        seen = []
        for step in range(1001):
            bar = screen.progress_bar(step / 1000, 15)
            self.assertEqual(len(bar), 15)
            if not seen or seen[-1] != bar:
                seen.append(bar)
        self.assertEqual(len(seen), 76)

    def test_ticker(self):
        self.assertEqual(screen.ticker("kurz", 8, 99), "kurz    ")
        text = "abcdefghijklmnop"
        self.assertEqual(screen.ticker(text, 8, 0), "abcdefgh")
        shown = {screen.ticker(text, 8, t / 10) for t in range(200)}
        self.assertTrue(any(line.endswith("nop") for line in shown))
        self.assertTrue(all(len(line) == 8 for line in shown))

    def test_wrap(self):
        self.assertEqual(screen.wrap("ein kurzer Satz", 8), ["ein", "kurzer", "Satz"])
        self.assertEqual(screen.wrap("abcdefghijkl x", 5), ["abcde", "fghij", "kl x"])
        self.assertEqual(screen.wrap("  \n ", 5), [])

    def test_duration(self):
        self.assertEqual(screen.duration(59), "0:00")
        self.assertEqual(screen.duration(4320), "1:12")
        self.assertEqual(screen.duration(-5), "0:00")
        self.assertEqual(screen.duration(101 * 3600), "4d05h")


if __name__ == "__main__":
    unittest.main()
