"""Kommandozeile."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time

from . import config as config_module
from . import describe
from .serial_link import LcdLink, LinkError, SerialUnavailable, list_ports, stable_names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moonraker_lcd", description="Klipper-Status auf einem Text-LCD am Arduino"
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + describe())
    parser.add_argument("--config", default="", help="Konfigurationsdatei")
    parser.add_argument("--verbose", "-v", action="store_true", help="ausfuehrliches Log")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Dienst starten")
    sub.add_parser("config", help="Konfiguration pruefen und anzeigen")
    sub.add_parser("ports", help="serielle Schnittstellen auflisten (oeffnet nichts)")
    sub.add_parser("identify", help="am konfigurierten Port nach dem Display-Arduino fragen")
    pages = sub.add_parser("pages", help="alle Seiten einmal im Terminal zeigen")
    pages.add_argument("--size", default="20x4", help="Displaygroesse (Standard 20x4)")
    sim = sub.add_parser("simulate", help="Scheindrucker auf dem Display oder im Terminal")
    sim.add_argument("--preview", action="store_true", help="im Terminal statt auf dem LCD")
    sim.add_argument("--size", default="20x4", help="Displaygroesse fuer --preview")
    sim.add_argument("--seconds", type=float, default=0.0, help="nach dieser Zeit beenden")
    return parser


def parse_size(text: str) -> tuple:
    try:
        cols, rows = (int(part) for part in text.lower().split("x"))
    except ValueError:
        raise config_module.ConfigError("ungueltige Groesse %r (z. B. 20x4)" % text) from None
    if not (8 <= cols <= 20 and 1 <= rows <= 4):
        raise config_module.ConfigError("Groesse %s nicht moeglich" % text)
    return cols, rows


def frame(lines) -> str:
    border = "+" + "-" * len(lines[0]) + "+"
    return "\n".join([border] + ["|%s|" % line for line in lines] + [border])


async def _until_signal(coroutine) -> None:
    """Laufen lassen, bis SIGTERM/SIGINT kommt - dann sauber beenden."""
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(coroutine)
    for number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(number, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


def cmd_run(args, config) -> int:
    from .service import Service

    async def main():
        await Service(config).run()

    asyncio.run(_until_signal(main()))
    return 0


def cmd_config(args, config) -> int:
    print(config.describe())
    return 0


def cmd_ports(args, config) -> int:
    ports = list_ports()
    print("Schnittstellen:")
    for device, description, hwid in ports or [("(keine)", "", "")]:
        print("  %-24s %s  %s" % (device, description, hwid))
    by_id = stable_names("/dev/serial/by-id")
    by_path = stable_names("/dev/serial/by-path")
    for title, entries in (("by-id", by_id), ("by-path", by_path)):
        if entries:
            print("\n/dev/serial/%s:" % title)
            for name, target in entries:
                print("  %s -> %s" % (name, target))
    adapters = [p for p in ports if "1A86" in p[2].upper()]
    if len(adapters) > 1:
        print(
            "\nACHTUNG: %d CH340-Adapter. Sie haben keine Seriennummer und teilen sich einen\n"
            "by-id-Namen - fuer jeden davon /dev/serial/by-path/ eintragen." % len(adapters)
        )
    return 0


def cmd_identify(args, config) -> int:
    async def main():
        link = LcdLink(config.serial)
        try:
            return await link.connect()
        finally:
            await link.close()

    try:
        ident = asyncio.run(main())
    except LinkError as exc:
        print("Fehler: %s" % exc, file=sys.stderr)
        return 1
    print("Display-Arduino an %s" % config.serial.port)
    print("  Sketch    : %s (Protokoll %d)" % (ident.sketch, ident.protocol))
    print("  Display   : %d x %d" % (ident.cols, ident.rows))
    print("  I2C       : %s" % ("0x%02X" % ident.address if ident.lcd_found else "kein LCD gefunden"))
    return 0 if ident.lcd_found else 1


def cmd_pages(args, config) -> int:
    from . import pages
    from .service import Service

    cols, rows = parse_size(args.size)

    async def main():
        service = Service(config)
        client = asyncio.ensure_future(service.client.run())
        for _ in range(100):
            await asyncio.sleep(0.1)
            if service.printer.online:
                await asyncio.sleep(1.5)
                break
        ctx = pages.PageContext(
            service.printer, config, service.translate, cols, rows, 0.0, time.time()
        )
        for page in pages.page_list(ctx):
            print(frame(page()))
        client.cancel()
        await asyncio.gather(client, return_exceptions=True)
        return 0 if service.printer.online or service.printer.hostname else 1

    return asyncio.run(main())


def cmd_simulate(args, config) -> int:
    from . import simulator

    if not args.preview:
        async def main():
            service = simulator.simulated_service(config)
            if args.seconds > 0:
                try:
                    await asyncio.wait_for(service.run(), args.seconds)
                except asyncio.TimeoutError:
                    pass
            else:
                await service.run()

        asyncio.run(_until_signal(main()))
        return 0

    cols, rows = parse_size(args.size)
    last = []

    def show(lines):
        if lines != last:
            last[:] = lines
            prefix = "\x1b[H\x1b[2J" if sys.stdout.isatty() else ""
            print(prefix + frame(lines), flush=True)

    asyncio.run(_until_signal(simulator.preview(config, cols, rows, show, args.seconds)))
    return 0


COMMANDS = {
    "run": cmd_run, "config": cmd_config, "ports": cmd_ports, "identify": cmd_identify,
    "pages": cmd_pages, "simulate": cmd_simulate,
}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = config_module.load(args.config)
    except config_module.ConfigError as exc:
        print("Konfigurationsfehler: %s" % exc, file=sys.stderr)
        return 2
    level = "debug" if args.verbose else config.log_level
    if args.command in ("pages", "identify") and not args.verbose:
        level = "warning"
    logging.basicConfig(level=level.upper(), format="%(levelname)s %(message)s")
    logging.getLogger("websockets").setLevel(logging.WARNING)
    try:
        return COMMANDS[args.command](args, config)
    except (config_module.ConfigError, SerialUnavailable) as exc:
        print("Fehler: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
