"""Serielles Protokoll zwischen Dienst und Arduino (siehe docs/protokoll.md).

Jede Nachricht ist eine Zeile ``<Nutzlast>*<XOR der Nutzlast, 2 Hex>\\n``. Der
Arduino quittiert jeden Befehl, erst danach kommt der naechste - so laeuft sein
64 Byte kleiner Empfangspuffer nie ueber.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Protokollversion dieses Dienstes
VERSION = 1
IDENT = "MLS"


class ProtocolError(ValueError):
    """Zeile ist keine gueltige Protokollnachricht."""


def checksum(payload: bytes) -> int:
    value = 0
    for byte in payload:
        value ^= byte
    return value


def encode(payload: bytes) -> bytes:
    if any(byte < 0x20 for byte in payload):
        raise ProtocolError("Steuerzeichen in der Nutzlast: %r" % payload)
    return payload + b"*%02X\n" % checksum(payload)


def decode(line: bytes) -> bytes:
    line = line.rstrip(b"\r\n")
    if len(line) < 4 or line[-3:-2] != b"*":
        raise ProtocolError("kein Protokoll: %r" % line)
    try:
        expected = int(line[-2:], 16)
    except ValueError as exc:
        raise ProtocolError("Pruefsumme unlesbar: %r" % line) from exc
    payload = line[:-3]
    if checksum(payload) != expected:
        raise ProtocolError("Pruefsumme falsch: %r" % line)
    return payload


# -------------------------------------------------------------------- Befehle

QUERY = b"?"
CLEAR = b"C"
REINIT = b"Z"
PING = b"P"


def row(index: int, codes: bytes) -> bytes:
    return b"L%d" % index + codes


def glyph(index: int, pattern) -> bytes:
    return b"G%d" % index + b"".join(b"%02X" % (line & 0x1F) for line in pattern)


def backlight(on: bool) -> bytes:
    return b"B1" if on else b"B0"


# ------------------------------------------------------------------ Meldungen


@dataclass(frozen=True)
class Ident:
    """Kennung des Arduino: ``IMLS <Protokoll> <Sketch> <Spalten> <Zeilen> <Adresse>``."""

    protocol: int
    sketch: str
    cols: int
    rows: int
    address: int

    @property
    def lcd_found(self) -> bool:
        return self.address != 0


def parse_ident(payload: bytes) -> Ident:
    parts = payload.decode("ascii", "replace").split()
    if len(parts) != 6 or parts[0] != "I" + IDENT:
        raise ProtocolError("keine Kennung: %r" % payload)
    try:
        ident = Ident(int(parts[1]), parts[2], int(parts[3]), int(parts[4]), int(parts[5], 16))
    except ValueError as exc:
        raise ProtocolError("Kennung unlesbar: %r" % payload) from exc
    if not (8 <= ident.cols <= 20 and 1 <= ident.rows <= 4):
        raise ProtocolError("unmoegliche Displaygroesse: %r" % payload)
    return ident


def parse_rotation(payload: bytes) -> int:
    try:
        return int(payload[1:])
    except ValueError as exc:
        raise ProtocolError("Drehung unlesbar: %r" % payload) from exc
