"""Ende zu Ende: Fake-Moonraker <-> Dienst <-> echter Sketch mit LCD-Modell.

    ~/moonraker-lcd-env/bin/python tests/integration_moonraker.py

Braucht ``websockets``, ``pyserial`` und einen C++-Compiler. Wird von
``unittest discover`` absichtlich nicht gefunden (kein ``test_`` im Namen).
"""

import asyncio
import copy
import json
import os
import signal
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import arduino_host
import websockets

from moonraker_lcd import simulator
from moonraker_lcd.config import Config, MenuItemConfig
from moonraker_lcd.serial_link import LcdLink, WrongDevice, LinkError
from moonraker_lcd.service import Service

FAILURES = []


def check(name, condition, detail=""):
    print("  [%s] %s%s" % ("ok" if condition else "FEHLER", name, "" if condition else " - %s" % (detail,)))
    if not condition:
        FAILURES.append(name)


class FakeMoonraker:
    def __init__(self):
        self.objects = copy.deepcopy(simulator.base_objects())
        self.klippy = "ready"
        self.message = ""
        self.calls = []
        self.sockets = set()
        self.fail = {}
        self.subscriptions = 0
        self.port = 0

    async def handler(self, socket):
        self.sockets.add(socket)
        try:
            async for raw in socket:
                request = json.loads(raw)
                method = request["method"]
                self.calls.append((method, request.get("params")))
                reply = {"jsonrpc": "2.0", "id": request["id"]}
                if method in self.fail:
                    reply["error"] = {"code": 400, "message": self.fail[method]}
                else:
                    reply["result"] = self.answer(method, request.get("params"))
                await socket.send(json.dumps(reply))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.sockets.discard(socket)

    def answer(self, method, params):
        if method == "server.info":
            return {"klippy_state": self.klippy, "klippy_connected": self.klippy != "disconnected"}
        if method == "printer.info":
            return {"hostname": "testdrucker", "state_message": self.message}
        if method == "printer.objects.list":
            return {"objects": list(self.objects) + ["gcode_macro X"]}
        if method == "printer.objects.subscribe":
            self.subscriptions += 1
            return {"status": {name: self.objects[name] for name in params["objects"]}}
        if method == "server.files.metadata":
            return simulator.METADATA
        if method == "machine.system_info":
            return {"system_info": {"network": {"eth0": {"ip_addresses": [
                {"family": "ipv4", "address": "192.0.2.33", "is_link_local": False}]}}}}
        return "ok"

    async def notify(self, method, *params):
        for socket in list(self.sockets):
            await socket.send(json.dumps({"jsonrpc": "2.0", "method": method, "params": list(params)}))

    async def update(self, objects):
        for name, values in objects.items():
            self.objects.setdefault(name, {}).update(values)
        await self.notify("notify_status_update", objects, 1.0)

    def called(self, method):
        return [params for name, params in self.calls if name == method]


async def wait_for(arduino, predicate, timeout=6.0):
    end = time.monotonic() + timeout
    while True:
        shown = arduino.show()
        if predicate(shown) or time.monotonic() > end:
            await asyncio.sleep(0.4)  # das Display wird Zeichen fuer Zeichen geschrieben
            return arduino.show()
        await asyncio.sleep(0.1)


def make_config(arduino, moonraker):
    config = Config()
    config.serial.port = arduino.port
    config.serial.handshake_timeout = 4
    config.moonraker.url = "ws://127.0.0.1:%d/websocket" % moonraker.port
    config.moonraker.reconnect_min = 0.3
    config.moonraker.reconnect_max = 0.5
    config.menu.items = [MenuItemConfig("Vorheizen", gcode="M140 S60\nM104 S200")]
    return config


async def pick(arduino, label):
    """Ueber den Drehgeber einen Menuepunkt waehlen."""
    arduino.command("CLICK")
    for _ in range(12):
        await asyncio.sleep(0.6)
        rows = arduino.show().text
        if any(row.startswith(">" + label) for row in rows):
            arduino.command("CLICK")
            await asyncio.sleep(0.5)
            return True
        arduino.command("CW")
    print("    Menue:", rows)
    return False


async def scenario(binary):
    moonraker = FakeMoonraker()
    arduino = arduino_host.Arduino(binary)
    server = await websockets.serve(moonraker.handler, "127.0.0.1", 0)
    moonraker.port = server.sockets[0].getsockname()[1]
    service = Service(make_config(arduino, moonraker))
    task = asyncio.ensure_future(service.run())

    print("Leerlauf")
    shown = await wait_for(arduino, lambda s: "bereit" in s.text[0])
    check("Leerlaufseite", shown.text[0] == "testdrucker   bereit", shown.text)
    check("Temperaturen", shown.text[1:3] == ["Hotend         24.1°", "Bett           22.4°"], shown.text)

    print("Druck")
    await moonraker.update(simulator.printing(0.42))
    shown = await wait_for(arduino, lambda s: "84/200" in s.text[3] and "Ende" in s.text[3])
    check("Schicht und Druckende", shown.text[3].startswith("S 84/200  Ende "), shown.text)
    check("Balken und Prozent", shown.text[1].startswith("█" * 6 + "▏") and shown.text[1].endswith("42%"), shown.text)
    check("Metadaten angefragt", moonraker.called("server.files.metadata") == [{"filename": simulator.FILENAME}])

    print("Drehgeber")
    for _ in range(3):
        arduino.command("CW")
    shown = await wait_for(arduino, lambda s: "192.0.2.33" in "".join(s.text))
    check("Systemseite mit IP-Adresse", "192.0.2.33" in "".join(shown.text), shown.text)
    arduino.command("LONG")
    shown = await wait_for(arduino, lambda s: "42%" in s.text[1])
    check("langes Druecken fuehrt zur Statusseite", "42%" in shown.text[1], shown.text)
    check("Pause ausgewaehlt", await pick(arduino, "Pause"))
    check("Pause an Moonraker geschickt", len(moonraker.called("printer.print.pause")) == 1)
    await moonraker.update({"print_stats": {"state": "paused"}, "pause_resume": {"is_paused": True}})
    await asyncio.sleep(2.5)
    check("Abbrechen ausgewaehlt", await pick(arduino, "Abbrechen"))
    shown = await wait_for(arduino, lambda s: ">Nein" in s.text[3])
    check("Rueckfrage mit Nein vorausgewaehlt", ">Nein" in shown.text[3], shown.text)
    arduino.command("CLICK")
    await asyncio.sleep(0.5)
    check("Nein bricht nichts ab", not moonraker.called("printer.print.cancel"))
    moonraker.fail["printer.print.cancel"] = "Cancel nicht erlaubt"
    check("Abbrechen nochmals", await pick(arduino, "Abbrechen"))
    arduino.command("CW")
    await asyncio.sleep(0.4)
    arduino.command("CLICK")
    shown = await wait_for(arduino, lambda s: "Fehlgeschlagen" in "".join(s.text))
    check("Fehler von Moonraker wird angezeigt", "Fehlgeschlagen" in "".join(shown.text), shown.text)
    check("Abbruch genau einmal geschickt", len(moonraker.called("printer.print.cancel")) == 1)

    print("Klipper-Stopp und Neustart")
    moonraker.klippy, moonraker.message = "shutdown", "Lost communication with MCU"
    await moonraker.notify("notify_klippy_shutdown")
    shown = await wait_for(arduino, lambda s: "Klipper-Stopp" in s.text[0])
    check("Stopp mit Meldung", "Lost communication" in "".join(shown.text), shown.text)
    moonraker.klippy = "disconnected"
    await moonraker.notify("notify_klippy_disconnected")
    shown = await wait_for(arduino, lambda s: "Klipper fehlt" in s.text[1])
    check("Klipper weg", "Klipper fehlt" in shown.text[1], shown.text)
    moonraker.klippy, moonraker.message = "ready", ""
    moonraker.objects = copy.deepcopy(simulator.base_objects())
    started = time.monotonic()
    await moonraker.notify("notify_klippy_ready")
    shown = await wait_for(arduino, lambda s: "bereit" in s.text[0])
    check("wieder bereit ohne Verzoegerung", "bereit" in shown.text[0] and time.monotonic() - started < 3, shown.text)

    print("Makro")
    check("Vorheizen ausgewaehlt", await pick(arduino, "Vorheizen"))
    check("G-Code geschickt", moonraker.called("printer.gcode.script") == [{"script": "M140 S60\nM104 S200"}])

    print("Stoerungen")
    await asyncio.sleep(2.5)
    arduino.command("RESET")
    shown = await wait_for(arduino, lambda s: "bereit" in s.text[0])
    await asyncio.sleep(1.0)
    check("Arduino-Reset: Anzeige kommt wieder", "bereit" in arduino.show().text[0], arduino.show().text)
    server.close()
    await server.wait_closed()
    shown = await wait_for(arduino, lambda s: "kein Moonraker" in s.text[1])
    check("Moonraker weg", "kein Moonraker" in shown.text[1], shown.text)
    server = await websockets.serve(moonraker.handler, "127.0.0.1", moonraker.port)
    shown = await wait_for(arduino, lambda s: "bereit" in s.text[0])
    check("Moonraker wieder da", "bereit" in shown.text[0], shown.text)

    print("Beenden")
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    shown = await wait_for(arduino, lambda s: not s.light)
    check("Display dunkel und leer", not shown.light and not "".join(shown.text).strip(), shown.text)
    check("kein Pufferueberlauf, LCD-Zeitverhalten sauber", shown.errors == 0 and shown.overflow == 0)
    server.close()
    await server.wait_closed()
    arduino.close()


async def sigterm(binary):
    """Dienst als Prozess: systemctl stop muss das Display dunkel schalten."""
    print("Dienst als Prozess (SIGTERM)")
    moonraker = FakeMoonraker()
    arduino = arduino_host.Arduino(binary)
    server = await websockets.serve(moonraker.handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    with tempfile.NamedTemporaryFile("w", suffix=".conf") as handle:
        handle.write("[moonraker]\nurl = 127.0.0.1:%d\n[serial]\nport = %s\n" % (port, arduino.port))
        handle.flush()
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "moonraker_lcd", "--config", handle.name, "run", cwd=ROOT,
            stderr=asyncio.subprocess.PIPE)
        shown = await wait_for(arduino, lambda s: "bereit" in s.text[0], 10)
        check("Dienst zeigt etwas an", "bereit" in shown.text[0], shown.text)
        process.send_signal(signal.SIGTERM)
        _, log = await asyncio.wait_for(process.communicate(), 8)
    check("sauber beendet", process.returncode == 0 and b"Traceback" not in log, log.decode())
    check("Display dunkel", not arduino.show().light)
    server.close()
    await server.wait_closed()
    arduino.close()


async def wrong_device():
    print("Falscher Port")
    master, slave = os.openpty()
    os.set_blocking(master, False)
    config = Config()
    config.serial.port = os.ttyname(slave)
    config.serial.handshake_timeout = 3
    link = LcdLink(config.serial)
    try:
        await link.connect()
        check("fremdes Geraet wird abgelehnt", False)
    except WrongDevice:
        check("fremdes Geraet wird abgelehnt", True)
    written = os.read(master, 4096)
    check("nur die Frage nach der Kennung geschickt", set(written.split(b"\n")) <= {b"?*3F", b""}, written)
    config.serial.port = "/dev/gibt-es-nicht"
    try:
        await link.connect()
        check("fehlender Port", False)
    except LinkError as exc:
        check("fehlender Port", "nicht vorhanden" in str(exc))


async def main():
    with arduino_host.temporary_directory() as directory:
        binary = arduino_host.build(directory)
        await scenario(binary)
        await sigterm(binary)
    await wrong_device()


if __name__ == "__main__":
    asyncio.run(main())
    print("\n%s" % ("Integrationstest bestanden" if not FAILURES else "FEHLGESCHLAGEN: %s" % ", ".join(FAILURES)))
    sys.exit(1 if FAILURES else 0)
