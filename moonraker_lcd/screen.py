"""Zeichensatz des Displays, eigene Zeichen und Textbausteine.

Intern ist eine Displayzeile immer ein normaler Python-String mit genau so
vielen Zeichen wie das Display Spalten hat. Erst :func:`to_codes` uebersetzt
in die Codes des HD44780.
"""

from __future__ import annotations

import unicodedata

#: Fortschrittsbalken: 1 bis 5 gefuellte Pixelspalten je Zeichen
BAR = "▏▍▋▉█"
BAR_EMPTY = "░"

#: Eigene Zeichen (Platz 0-7) - die Reihenfolge ist die Platznummer
GLYPHS = {
    BAR[0]: [0x10] * 8,
    BAR[1]: [0x18] * 8,
    BAR[2]: [0x1C] * 8,
    BAR[3]: [0x1E] * 8,
    BAR[4]: [0x1F] * 8,
    BAR_EMPTY: [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F],
    "Ä": [0x0A, 0x00, 0x0E, 0x11, 0x1F, 0x11, 0x11, 0x00],  # AE
    "Ü": [0x0A, 0x00, 0x11, 0x11, 0x11, 0x11, 0x0E, 0x00],  # UE
}
GLYPH_LIST = list(GLYPHS)

#: Im Protokoll stehen die eigenen Zeichen auf 0x80-0x87
GLYPH_BASE = 0x80

_A00 = {
    "°": 0xDF, "ä": 0xE1, "ö": 0xEF, "ü": 0xF5, "ß": 0xE2,
    "µ": 0xE4, "→": 0x7E, "←": 0x7F, "ñ": 0xEE,
    "\\": 0x2F, "~": 0x2D,  # dort liegen im ROM Yen und Pfeil
}
_A02 = {chr(code): code for code in range(0xC0, 0x100)}
_A02.update({"°": 0xB0, "µ": 0xB5})

#: A00 = ueblich (japanischer Zeichensatz), A02 = europaeisch, ascii = sicher
CHARSETS = {"a00": _A00, "a02": _A02, "ascii": {"\\": 0x2F, "~": 0x2D}}

_FALLBACK = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ö": "Oe",
    "°": "'", "→": ">", "←": "<", "–": "-", "—": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"', "„": '"',
    "…": ".", "×": "x",
}


def _code(char: str, table: dict) -> int:
    if char in GLYPHS:
        return GLYPH_BASE + GLYPH_LIST.index(char)
    if char in table:
        return table[char]
    if " " <= char <= "}":
        return ord(char)
    # ein Zeichen muss ein Zeichen bleiben, sonst verrutscht das Layout
    replacement = _FALLBACK.get(char)
    if replacement is None:
        decomposed = unicodedata.normalize("NFKD", char)
        replacement = decomposed if decomposed[:1].isascii() else "?"
    first = replacement[0]
    return ord(first) if " " <= first <= "}" else ord("?")


def to_codes(text: str, charset: str = "a00") -> bytes:
    """Zeile in HD44780-Codes uebersetzen; die Laenge bleibt gleich."""
    table = CHARSETS[charset]
    return bytes(_code(char, table) for char in unicodedata.normalize("NFC", text))


# ------------------------------------------------------------------- Bausteine


def clean(text: str) -> str:
    """Zeilenumbrueche und Mehrfach-Leerzeichen entfernen."""
    return " ".join(unicodedata.normalize("NFC", str(text or "")).split())


def fit(text: str, width: int) -> str:
    return text[:width].ljust(width)


def center(text: str, width: int) -> str:
    return fit(text[:width].center(width), width)


def spread(left: str, right: str, width: int) -> str:
    """Links- und rechtsbuendig; bei Platzmangel wird links gekuerzt."""
    right = right[:width]
    room = width - len(right)
    if room <= 0:
        return right
    if len(left) >= room and right:
        left = left[: room - 1]
    return left.ljust(room) + right


def progress_bar(fraction: float, width: int) -> str:
    """Balken mit 5 Stufen je Zeichen."""
    fraction = min(max(fraction, 0.0), 1.0)
    pixels = int(fraction * width * 5 + 1e-6)
    full, rest = divmod(pixels, 5)
    bar = BAR[4] * full
    if rest:
        bar += BAR[rest - 1]
    return bar + BAR_EMPTY * (width - len(bar))


def ticker(text: str, width: int, now: float, step: float = 0.4, hold: float = 2.0) -> str:
    """Laufschrift fuer zu lange Texte; kurze bleiben stehen."""
    if len(text) <= width:
        return fit(text, width)
    loop = text + "   "
    period = hold + len(loop) * step
    position = now % period
    offset = 0 if position < hold else int((position - hold) / step)
    return (loop * 2)[offset : offset + width]


def wrap(text: str, width: int) -> list:
    """Wortweise umbrechen; zu lange Woerter werden hart getrennt."""
    lines = []
    current = ""
    for word in clean(text).split():
        while len(word) > width:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:width])
            word = word[width:]
        if not word:
            continue
        candidate = (current + " " + word) if current else word
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def duration(seconds: float) -> str:
    """``0:07``, ``1:12``, ``26:40`` (Stunden:Minuten), ab 100 h in Tagen."""
    minutes = int(max(seconds, 0) // 60)
    hours, minutes = divmod(minutes, 60)
    if hours >= 100:
        return "%dd%02dh" % divmod(hours, 24)
    return "%d:%02d" % (hours, minutes)
