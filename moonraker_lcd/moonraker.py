"""Moonraker-Anbindung ueber die JSON-RPC-Websocket-API."""

from __future__ import annotations

import asyncio
import json
import logging
import socket as socket_module
import time
from urllib.parse import urlparse

from .config import MoonrakerConfig

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - Abhaengigkeit ist zur Laufzeit erforderlich
    import websockets
except ImportError:  # pragma: no cover
    websockets = None

POLL_NOT_READY = 5.0
SYSTEM_INFO_INTERVAL = 60.0


class MoonrakerUnavailable(RuntimeError):
    """Das Paket ``websockets`` fehlt."""


class RpcError(RuntimeError):
    """Moonraker hat einen Aufruf abgelehnt."""


class NotConnected(RuntimeError):
    """Es besteht gerade keine Verbindung zu Moonraker."""


class MoonrakerClient:
    """Haelt die Websocket-Verbindung, fuettert den :class:`Printer` und
    fuehrt Aufrufe aus dem Menue aus."""

    def __init__(self, config: MoonrakerConfig, printer, on_change=None) -> None:
        if websockets is None:  # pragma: no cover
            raise MoonrakerUnavailable(
                "Python-Paket 'websockets' fehlt - bitte 'pip install websockets'"
            )
        self._config = config
        self._printer = printer
        self._on_change = on_change or (lambda: None)
        self._next_id = 0
        self._pending: dict = {}
        self._socket = None
        self._tasks: set = set()

    # ------------------------------------------------------------------ oeffentlich

    async def run(self) -> None:
        """Endlosschleife mit exponentiellem Backoff."""
        delay = self._config.reconnect_min
        last_error = ""
        while True:
            started = time.monotonic()
            try:
                await self._session()
                error = "Verbindung beendet"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - jede Stoerung fuehrt zum Retry
                error = str(exc) or type(exc).__name__
            finally:
                self._socket = None
                self._fail_pending()
                self._printer.set_online(False)
                self._on_change()
            if error != last_error:
                LOGGER.warning("Moonraker nicht verbunden: %s", error)
            last_error = error
            if time.monotonic() - started > 30:
                delay = self._config.reconnect_min
                last_error = ""
            await asyncio.sleep(delay)
            delay = min(delay * 2.0, self._config.reconnect_max)

    async def call(self, method: str, params=None, timeout: float = None):
        """Einen Moonraker-Aufruf ausfuehren und das Ergebnis abwarten."""
        if self._socket is None:
            raise NotConnected("keine Verbindung zu Moonraker")
        self._next_id += 1
        request_id = self._next_id
        payload = {"jsonrpc": "2.0", "method": method, "id": request_id}
        if params is not None:
            payload["params"] = params
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._socket.send(json.dumps(payload))
            return await asyncio.wait_for(future, timeout or self._config.connect_timeout)
        finally:
            self._pending.pop(request_id, None)

    # ------------------------------------------------------------------ intern

    def _connect(self):
        headers = {"X-Api-Key": self._config.api_key} if self._config.api_key else {}
        kwargs = {
            "open_timeout": self._config.connect_timeout,
            "ping_interval": 20,
            "ping_timeout": 20,
            "close_timeout": 2,
            "max_size": 16 * 1024 * 1024,
        }
        if not headers:
            return websockets.connect(self._config.url, **kwargs)
        # websockets >= 14 nennt den Parameter anders und prueft ihn erst spaet
        major = int(websockets.__version__.split(".")[0])
        key = "additional_headers" if major >= 14 else "extra_headers"
        kwargs[key] = headers
        return websockets.connect(self._config.url, **kwargs)

    async def _session(self) -> None:
        LOGGER.debug("verbinde mit Moonraker: %s", self._config.url)
        async with self._connect() as socket:
            self._socket = socket
            reader = asyncio.ensure_future(self._read_loop(socket))
            poller = asyncio.ensure_future(self._poll_loop())
            try:
                await self._refresh_klippy()
                self._printer.set_online(True)
                LOGGER.info("mit Moonraker verbunden: %s", self._config.url)
                self._on_change()
                done, _ = await asyncio.wait([reader, poller], return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                tasks = [reader, poller] + list(self._tasks)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self._tasks.clear()

    async def _poll_loop(self) -> None:
        """Klipper-Zustand nachfragen, solange er nicht bereit ist; IP-Adressen."""
        next_info = 0.0
        while True:
            if time.monotonic() >= next_info:
                next_info = time.monotonic() + SYSTEM_INFO_INTERVAL
                await self._optional(self._update_system_info())
            await asyncio.sleep(POLL_NOT_READY)
            if self._printer.klippy_state != "ready":
                await self._refresh_klippy()

    def _spawn(self, coroutine) -> None:
        # Aufrufe aus der Leseschleife heraus brauchen eine eigene Aufgabe: Ihre
        # Antwort kommt ueber genau diese Leseschleife.
        task = asyncio.ensure_future(self._optional(coroutine))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _optional(coroutine) -> None:
        try:
            await coroutine
        except (RpcError, NotConnected, asyncio.TimeoutError) as exc:
            LOGGER.debug("uebergangen: %s", exc or type(exc).__name__)

    async def _refresh_klippy(self) -> None:
        info = await self.call("server.info")
        state = str(info.get("klippy_state", "")).lower()
        message = ""
        if info.get("klippy_connected", state not in ("", "disconnected")):
            try:
                details = await self.call("printer.info")
                message = details.get("state_message", "") if state != "ready" else ""
                self._printer.hostname = details.get("hostname", "") or self._printer.hostname
            except (RpcError, asyncio.TimeoutError):
                pass
        if not self._printer.hostname and urlparse(self._config.url).hostname in ("127.0.0.1", "localhost"):
            self._printer.hostname = socket_module.gethostname().split(".")[0]
        if state == "ready":
            await self._subscribe()
        self._printer.set_klippy(state, message)
        self._on_change()

    async def _subscribe(self) -> None:
        available = (await self.call("printer.objects.list")).get("objects", [])
        wanted = self._printer.subscription(available)
        result = await self.call("printer.objects.subscribe", {"objects": wanted})
        self._printer.reset_objects()
        self._printer.update_objects(result.get("status", {}))
        LOGGER.info("Abonnement: %s", ", ".join(sorted(wanted)))
        self._check_metadata()

    def _check_metadata(self) -> None:
        filename = self._printer.filename
        if filename and filename != self._printer.metadata_for:
            self._printer.set_metadata(filename, {})
            self._spawn(self._update_metadata(filename))

    async def _update_metadata(self, filename: str) -> None:
        metadata = await self.call("server.files.metadata", {"filename": filename})
        if self._printer.filename == filename:
            self._printer.set_metadata(filename, metadata)
            self._on_change()

    async def _update_system_info(self) -> None:
        self._printer.update_system_info(await self.call("machine.system_info"))
        self._on_change()

    async def _read_loop(self, socket) -> None:
        async for raw in socket:
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                LOGGER.debug("ungueltige Nachricht verworfen")
                continue
            if isinstance(message, dict):
                self._dispatch(message)

    def _dispatch(self, message: dict) -> None:
        if "id" in message and message.get("method") is None:
            future = self._pending.pop(message["id"], None)
            if future is None or future.done():
                return
            if "error" in message:
                error = message["error"]
                text = error.get("message") if isinstance(error, dict) else error
                future.set_exception(RpcError(str(text)))
            else:
                future.set_result(message.get("result"))
            return

        method = message.get("method", "")
        params = message.get("params") or []

        if method == "notify_status_update":
            if params and isinstance(params[0], dict):
                self._printer.update_objects(params[0])
                self._check_metadata()
                self._on_change()
        elif method == "notify_proc_stat_update":
            if params and isinstance(params[0], dict):
                self._printer.update_proc_stats(params[0])
        elif method in ("notify_klippy_ready", "notify_klippy_shutdown"):
            self._spawn(self._refresh_klippy())
        elif method == "notify_klippy_disconnected":
            self._printer.set_klippy("disconnected")
            self._on_change()

    def _fail_pending(self) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(NotConnected("Verbindung zu Moonraker verloren"))
                future.exception()  # gilt als abgeholt, auch wenn niemand wartet
        self._pending.clear()
