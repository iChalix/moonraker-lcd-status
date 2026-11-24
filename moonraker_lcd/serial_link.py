"""Serielle Verbindung zum Display-Arduino mit Kennung und Quittungen."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from . import protocol
from .config import SerialConfig

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover
    import serial as pyserial
except ImportError:  # pragma: no cover
    pyserial = None

ACK_TIMEOUT = 0.5
ATTEMPTS = 3


class SerialUnavailable(RuntimeError):
    """Das Paket ``pyserial`` fehlt."""


class LinkError(RuntimeError):
    """Port nicht zu oeffnen oder Verbindung verloren."""


class WrongDevice(LinkError):
    """Am Port meldet sich kein Display-Arduino."""


class LcdLink:
    """Ein Befehl, eine Quittung. Meldungen des Drehgebers gehen an ``on_event``.

    Der Dienst schreibt ausser der Frage nach der Kennung nichts, bevor sich der
    Arduino als Display gemeldet hat. Auf einem falschen Port (z. B. einem
    anderen CH340-Adapter) landet so nie Displayinhalt.
    """

    def __init__(self, config: SerialConfig, on_event=None) -> None:
        self._config = config
        self._on_event = on_event or (lambda payload: None)
        self._serial = None
        self._buffer = b""
        self._ident_future = None
        self._ack_future = None
        self._broken = ""
        #: Arduino hat sich waehrend der Verbindung neu gemeldet (Reset)
        self.was_reset = False
        self._rejected: set = set()

    @property
    def connected(self) -> bool:
        return self._serial is not None and not self._broken

    # ------------------------------------------------------------------ Verbindung

    def _open_blocking(self):
        if not os.path.exists(self._config.port):
            raise LinkError("%s ist nicht vorhanden" % self._config.port)
        try:
            # exclusive: nie einen Port mitbenutzen, den z. B. Klipper offen hat
            return pyserial.Serial(
                self._config.port, self._config.baudrate, timeout=0, write_timeout=2.0, exclusive=True
            )
        except (OSError, ValueError, pyserial.SerialException) as exc:
            raise LinkError("%s: %s" % (self._config.port, exc)) from exc

    async def connect(self) -> protocol.Ident:
        if pyserial is None:  # pragma: no cover
            raise SerialUnavailable("Python-Paket 'pyserial' fehlt - bitte 'pip install pyserial'")
        if not self._config.port:
            raise LinkError("keine serielle Schnittstelle konfiguriert ([serial] port)")
        loop = asyncio.get_running_loop()
        self._serial = await loop.run_in_executor(None, self._open_blocking)
        self._buffer = b""
        self._broken = ""
        self.was_reset = False
        self._ident_future = loop.create_future()
        loop.add_reader(self._serial.fileno(), self._on_readable)
        try:
            return await self._handshake()
        except BaseException:
            await self.close()
            raise

    async def _handshake(self) -> protocol.Ident:
        # Das Oeffnen startet den Arduino neu; er meldet sich danach von selbst.
        deadline = time.monotonic() + self._config.handshake_timeout
        wait = min(2.0, self._config.handshake_timeout / 2)
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(self._ident_future), wait)
            except asyncio.TimeoutError:
                pass
            if self._broken:
                raise LinkError(self._broken)
            if time.monotonic() >= deadline:
                raise WrongDevice(
                    "%s: keine Kennung vom Display-Arduino - falscher Port oder anderer Sketch"
                    % self._config.port
                )
            await self._write(protocol.encode(protocol.QUERY))
            wait = 1.0

    async def close(self) -> None:
        port, self._serial = self._serial, None
        if port is None:
            return
        loop = asyncio.get_running_loop()
        try:
            loop.remove_reader(port.fileno())
        except (OSError, ValueError, pyserial.SerialException):
            pass
        try:
            await loop.run_in_executor(None, port.close)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ senden

    async def _write(self, data: bytes) -> None:
        if self._serial is None or self._broken:
            raise LinkError(self._broken or "nicht verbunden")
        try:
            # Nachrichten sind kuerzer als jeder Sendepuffer, das blockiert nicht
            self._serial.write(data)
        except (OSError, pyserial.SerialException) as exc:
            raise LinkError("Schreibfehler: %s" % exc) from exc

    async def send(self, payload: bytes) -> bool:
        """Befehl senden und quittieren lassen.

        ``False``: Der Sketch kennt den Befehl nicht. :class:`LinkError`:
        Verbindung verloren.
        """
        data = protocol.encode(payload)
        reply = b""
        for _ in range(ATTEMPTS):
            self._ack_future = asyncio.get_running_loop().create_future()
            await self._write(data)
            try:
                reply = await asyncio.wait_for(self._ack_future, ACK_TIMEOUT)
            except asyncio.TimeoutError:
                reply = b""
                if self._broken:
                    break
                continue
            finally:
                self._ack_future = None
            if reply == b"K":
                return True
            if reply == b"NU":
                command = payload[:1]
                if command not in self._rejected:
                    self._rejected.add(command)
                    LOGGER.warning("Sketch lehnt Befehl %r ab", payload)
                return False
        raise LinkError(self._broken or "keine Quittung vom Arduino (%s)" % (reply.decode() or "Zeitlimit"))

    # ------------------------------------------------------------------ empfangen

    def _on_readable(self) -> None:
        port = self._serial
        if port is None:
            return
        try:
            chunk = port.read(256)
            if not chunk:
                raise OSError("Geraet getrennt")
        except (OSError, TypeError, pyserial.SerialException) as exc:
            self._fail("Lesefehler: %s" % exc)
            return
        self._buffer += chunk
        if b"\n" not in self._buffer:
            # ein fremdes Geraet kann endlos ohne Zeilenende senden
            self._buffer = self._buffer[-256:]
            return
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            try:
                self._handle(protocol.decode(line))
            except protocol.ProtocolError as exc:
                LOGGER.debug("verworfen: %s", exc)

    def _fail(self, reason: str) -> None:
        self._broken = reason
        try:
            asyncio.get_running_loop().remove_reader(self._serial.fileno())
        except (OSError, ValueError, pyserial.SerialException):
            pass
        self._on_event(b"")

    def _handle(self, payload: bytes) -> None:
        kind = payload[:1]
        if kind == b"I":
            ident = protocol.parse_ident(payload)
            if self._ident_future is not None and not self._ident_future.done():
                self._ident_future.set_result(ident)
            else:
                self.was_reset = True
                self._on_event(b"")
        elif kind in (b"K", b"N"):
            if self._ack_future is not None and not self._ack_future.done():
                self._ack_future.set_result(payload)
        elif self._ident_future is not None and self._ident_future.done():
            self._on_event(payload)


def list_ports() -> list:
    """Verfuegbare serielle Schnittstellen (fuer die CLI)."""
    if pyserial is None:  # pragma: no cover
        raise SerialUnavailable("Python-Paket 'pyserial' fehlt")
    from serial.tools import list_ports as tools  # noqa: PLC0415

    return [(p.device, p.description or "", p.hwid or "") for p in tools.comports()]


def stable_names(directory: str) -> list:
    """``(Name, Ziel)`` aller Eintraege unter ``/dev/serial/by-id`` bzw. ``by-path``."""
    if not os.path.isdir(directory):
        return []
    return [
        (os.path.join(directory, name), os.path.realpath(os.path.join(directory, name)))
        for name in sorted(os.listdir(directory))
    ]
