"""Zusammenspiel von Moonraker, Bedienlogik und Display."""

from __future__ import annotations

import asyncio
import logging
import time

from . import describe, protocol, screen
from .config import Config
from .i18n import Translator
from .moonraker import MoonrakerClient, NotConnected, RpcError
from .printer import Printer
from .serial_link import LcdLink, LinkError, WrongDevice
from .ui import UI

LOGGER = logging.getLogger(__name__)

PING_INTERVAL = 8.0
RECONNECT_DELAY = 3.0
#: Makros duerfen dauern (Homing, Mesh) - das ist kein Fehler
ACTION_TIMEOUT = 1800.0


class Display:
    """Zeichnet die Bedienoberflaeche auf den Arduino und nimmt Eingaben an."""

    def __init__(self, config: Config, ui: UI, translate) -> None:
        self._config = config
        self._ui = ui
        self._t = translate
        self.link = LcdLink(config.serial, on_event=self._on_event)
        self._wake = None
        self._last_error = ""
        self._reinit = False
        self.ident = None

    def wake(self) -> None:
        if self._wake is not None:
            self._wake.set()

    def _on_event(self, payload: bytes) -> None:
        encoder = self._config.encoder
        kind, now = payload[:1], time.monotonic()
        if encoder.enabled:
            if kind == b"R":
                steps = protocol.parse_rotation(payload)
                self._ui.rotate(-steps if encoder.reverse else steps, now)
            elif kind == b"S":
                self._ui.click(now)
            elif kind == b"H":
                self._ui.long_press(now)
        self.wake()

    async def run(self) -> None:
        self._wake = asyncio.Event()
        while True:
            delay = RECONNECT_DELAY
            try:
                self.ident = await self.link.connect()
                self._last_error = ""
                await self._session()
            except WrongDevice as exc:
                self._note(str(exc))
                delay = self._config.serial.wrong_device_delay
            except LinkError as exc:
                self._note(str(exc))
            finally:
                await self._shutdown_session()
            await asyncio.sleep(delay)

    def _note(self, message: str) -> None:
        if message != self._last_error:
            LOGGER.warning("Display: %s", message)
        self._last_error = message

    async def _shutdown_session(self) -> None:
        """Beim Beenden das Display dunkel schalten, dann schliessen."""
        try:
            if self.link.connected:
                await asyncio.wait_for(self._darken(), 2.0)
        except (LinkError, asyncio.TimeoutError):
            pass
        finally:
            await self.link.close()

    async def _darken(self) -> None:
        await self.link.send(protocol.CLEAR)
        await self.link.send(protocol.backlight(False))

    def _lines(self) -> list:
        ident = self.ident
        if ident.protocol != protocol.VERSION:
            old = ident.protocol < protocol.VERSION
            lines = [self._t("sketch_old" if old else "service_old")]
            lines.append("Sketch %s" % ident.sketch if not old else self._t("sketch_flash"))
            lines = [screen.fit(line, ident.cols) for line in lines]
            return (lines + [" " * ident.cols] * ident.rows)[: ident.rows]
        return self._ui.render(time.monotonic(), time.time())

    async def _session(self) -> None:
        ident = self.ident
        LOGGER.info(
            "Display verbunden: %dx%d, Sketch %s (Protokoll %d), LCD %s",
            ident.cols, ident.rows, ident.sketch, ident.protocol,
            "auf 0x%02X" % ident.address if ident.lcd_found else "NICHT GEFUNDEN",
        )
        if not ident.lcd_found:
            LOGGER.warning("Arduino findet kein LCD am I2C-Bus - Verdrahtung SDA/SCL pruefen")
        self._ui.resize(ident.cols, ident.rows)
        display = self._config.display
        shown, light = [None] * ident.rows, None
        await self._upload_glyphs()
        last_sent = last_init = time.monotonic()
        while True:
            if self.link.was_reset:
                LOGGER.info("Arduino wurde neu gestartet - Display wird neu aufgebaut")
                self.link.was_reset = False
                shown, light = [None] * ident.rows, None
                await self._upload_glyphs()
            now = time.monotonic()
            due = display.reinit_interval > 0 and now - last_init >= display.reinit_interval
            if due or self._reinit:
                self._reinit = False
                await self.link.send(protocol.REINIT)
                last_init = now
            # erst zeichnen, dann Licht: das Display geht nie mit altem Inhalt an
            for index, line in enumerate(self._lines()):
                codes = screen.to_codes(line, display.charset)
                if codes != shown[index]:
                    await self.link.send(protocol.row(index, codes))
                    shown[index], last_sent = codes, time.monotonic()
            wanted = self._ui.backlight(time.monotonic())
            if wanted != light:
                await self.link.send(protocol.backlight(wanted))
                light, last_sent = wanted, time.monotonic()
            if time.monotonic() - last_sent >= PING_INTERVAL:
                await self.link.send(protocol.PING)
                last_sent = time.monotonic()
            if not self.link.connected:
                raise LinkError("Verbindung verloren")
            try:
                await asyncio.wait_for(self._wake.wait(), display.refresh_interval)
            except asyncio.TimeoutError:
                pass
            else:
                self._wake.clear()
                # Moonraker meldet viele kleine Aenderungen kurz nacheinander
                await asyncio.sleep(0.05)

    async def _upload_glyphs(self) -> None:
        for index, char in enumerate(screen.GLYPH_LIST):
            await self.link.send(protocol.glyph(index, screen.GLYPHS[char]))

    def refresh(self) -> None:
        """LCD neu initialisieren (Menuepunkt)."""
        self._reinit = True
        self.wake()


async def run_tasks(coroutines) -> None:
    tasks = [asyncio.ensure_future(coroutine) for coroutine in coroutines]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class Service:
    """Der Dienst: Moonraker lesen, Seiten zeichnen, Menuebefehle ausfuehren."""

    def __init__(self, config: Config) -> None:
        self._setup(config)
        self.client = MoonrakerClient(config.moonraker, self.printer, on_change=self.display.wake)

    def _setup(self, config: Config) -> None:
        """Alles ausser der Moonraker-Verbindung (die ersetzt der Simulator)."""
        self.config = config
        self.translate = Translator(config.display.language)
        self.printer = Printer(config, self.translate)
        self.ui = UI(config, self.printer, self.translate, on_action=self._on_action)
        self.display = Display(config, self.ui, self.translate)
        self._actions: set = set()

    async def run(self) -> None:
        LOGGER.info("Moonraker-LCD-Status %s startet", describe())
        LOGGER.info("%s", self.config.describe())
        try:
            await run_tasks([self.client.run(), self.display.run()])
        finally:
            for task in list(self._actions):
                task.cancel()
            LOGGER.info("Dienst beendet")

    def _on_action(self, action) -> None:
        task = asyncio.ensure_future(self._perform(action))
        self._actions.add(task)
        task.add_done_callback(self._actions.discard)

    async def _perform(self, action) -> None:
        LOGGER.info("Menue: %s", action.label)
        if action.kind == "refresh":
            self.display.refresh()
            return
        if action.kind == "gcode":
            method, params = "printer.gcode.script", {"script": action.payload}
        elif action.kind == "power":
            method = "machine.device_power.post_device"
            params = {"device": action.payload, "action": "toggle"}
        else:
            method, params = action.method, None
        self.ui.notice("%s: %s" % (action.label, self.translate("sent")), time.monotonic(), 2.0)
        try:
            await self.client.call(method, params, timeout=ACTION_TIMEOUT)
        except NotConnected as exc:
            # beim Herunterfahren bricht die Verbindung erwartungsgemaess ab
            LOGGER.info("Menue %s: %s", action.label, exc)
            if not method.startswith("machine."):
                self.ui.notice(self.translate("failed"), time.monotonic())
        except (RpcError, asyncio.TimeoutError) as exc:
            LOGGER.warning("Menue %s fehlgeschlagen: %s", action.label, exc)
            text = screen.clean("%s: %s" % (self.translate("failed"), exc))
            self.ui.notice(text, time.monotonic(), 6.0)
        except Exception as exc:  # noqa: BLE001 - ein Menuebefehl darf den Dienst nie beenden
            LOGGER.warning("Menue %s fehlgeschlagen: %r", action.label, exc)
            self.ui.notice(self.translate("failed"), time.monotonic())
        self.display.wake()
