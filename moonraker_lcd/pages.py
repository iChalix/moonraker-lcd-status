"""Seiten der Anzeige. Jede liefert genau ``rows`` Zeilen mit ``cols`` Zeichen."""

from __future__ import annotations

import datetime
import math

from . import screen
from .printer import Phase


#: Sekunden, nach denen Dateiname und Meldung in der Titelzeile wechseln
TITLE_TIME = 8.0


class PageContext:
    """Was eine Seite zum Zeichnen braucht."""

    def __init__(self, printer, config, translate, cols, rows, now, wall) -> None:
        self.printer = printer
        self.config = config
        self.t = translate
        self.cols = cols
        self.rows = rows
        #: monotone Zeit fuer Laufschrift und Wechsel
        self.now = now
        #: Unixzeit fuer Uhr und Druckende
        self.wall = wall

    def clock(self, timestamp: float) -> str:
        when = datetime.datetime.fromtimestamp(timestamp)
        if not self.config.display.clock_12h:
            return "%02d:%02d" % (when.hour, when.minute)
        return "%d:%02d%s" % (when.hour % 12 or 12, when.minute, "a" if when.hour < 12 else "p")

    def date(self) -> str:
        return self.t.date(datetime.datetime.fromtimestamp(self.wall))

    def line(self, left: str, right: str = "") -> str:
        return screen.spread(left, right, self.cols)

    def finish(self, lines) -> list:
        lines = [screen.fit(line, self.cols) for line in lines[: self.rows]]
        return lines + [" " * self.cols] * (self.rows - len(lines))


def _temp_pair(heater) -> str:
    return "%d/%d°" % (round(heater.temperature), round(heater.target))


def _temp_value(heater, width: int) -> str:
    if heater.heating and width >= 18:
        return "%.1f/%d°" % (heater.temperature, round(heater.target))
    if heater.heating:
        return _temp_pair(heater)
    return "%.1f°" % heater.temperature


def status_page(ctx: PageContext) -> list:
    phase = ctx.printer.phase
    if phase.fault:
        return _fault(ctx)
    if not phase.ready:
        return ctx.finish([
            ctx.line(ctx.printer.display_name), ctx.t(phase.value), "",
            ctx.line(ctx.date(), ctx.clock(ctx.wall)),
        ][: ctx.rows])
    if phase.active or phase in (Phase.COMPLETE, Phase.CANCELLED, Phase.PRINT_ERROR):
        return _job(ctx)
    return _idle(ctx)


def _fault(ctx: PageContext) -> list:
    lines = screen.wrap(ctx.printer.fault_message, ctx.cols)
    room = ctx.rows - 1
    if len(lines) > room:
        # lange Meldungen seitenweise zeigen, jede Seite 4 s
        count = math.ceil(len(lines) / room)
        page = int(ctx.now // 4) % count
        lines = lines[page * room : (page + 1) * room]
    return ctx.finish([screen.center(ctx.t(ctx.printer.phase.value), ctx.cols)] + lines)


def _idle(ctx: PageContext) -> list:
    printer = ctx.printer
    message = printer.message
    state = ctx.t(printer.phase.value)
    clock = ctx.clock(ctx.wall)
    heaters = [h for h in printer.heaters if h.kind in ("extruder", "bed")]
    if ctx.rows < 4:
        temps = " ".join(
            "%s%d" % ("T" if h.kind == "extruder" else "B", round(h.temperature)) for h in heaters[:2]
        )
        top = message if message else printer.display_name
        if message and len(message) > ctx.cols:
            return ctx.finish([screen.ticker(message, ctx.cols, ctx.now), ctx.line(temps, clock)])
        return ctx.finish([ctx.line(top, "" if message else state), ctx.line(temps, clock)])
    lines = [ctx.line(printer.display_name, state)]
    room = ctx.rows - 2
    if message:
        room -= 1
    for heater in heaters[:room]:
        lines.append(ctx.line(heater.name, _temp_value(heater, ctx.cols)))
    while len(lines) < 1 + room:
        lines.append("")
    if message:
        lines.append(screen.ticker(message, ctx.cols, ctx.now))
    lines.append(ctx.line(ctx.date(), clock))
    return ctx.finish(lines)


def _job_title(ctx: PageContext) -> str:
    printer = ctx.printer
    name = printer.job_name or ctx.t("print")
    message = printer.message
    if printer.phase is not Phase.PRINTING:
        state = ctx.t(printer.phase.value)
        # Zustand und Name im Wechsel, damit beides ganz lesbar bleibt
        choices = [state, message or name]
    else:
        choices = [name, message] if message else [name]
    if len(choices) == 1:
        return screen.ticker(choices[0], ctx.cols, ctx.now)
    index = int(ctx.now // TITLE_TIME) % len(choices)
    return screen.ticker(choices[index], ctx.cols, ctx.now % TITLE_TIME, step=0.25, hold=1.0)


def _job_time(ctx: PageContext) -> str:
    """Rechte untere Ecke: Druckende, sonst Restzeit oder Dauer."""
    printer = ctx.printer
    if printer.phase is Phase.PRINTING:
        eta = printer.eta(ctx.wall)
        if eta is not None:
            return "%s %s" % (ctx.t("eta"), ctx.clock(eta))
    if printer.phase is Phase.PAUSED and printer.remaining is not None:
        return "%s %s" % (ctx.t("remaining"), screen.duration(printer.remaining))
    return "%s %s" % (ctx.t("elapsed"), screen.duration(printer.total_elapsed))


def _temps(ctx: PageContext) -> str:
    parts = []
    extruder, bed = ctx.printer.extruder, ctx.printer.bed
    if extruder is not None:
        parts.append("T" + _temp_pair(extruder))
    if bed is not None:
        parts.append("B" + _temp_pair(bed))
    if not parts:
        return ""
    return ctx.line(parts[0], parts[1] if len(parts) > 1 else "")


def _job(ctx: PageContext) -> list:
    printer = ctx.printer
    percent = "%3d%%" % int(printer.progress * 100 + 1e-6)
    bar = screen.progress_bar(printer.progress, ctx.cols - 5) + " " + percent
    if ctx.rows < 4:
        extruder = printer.extruder
        temp = "T%d" % round(extruder.temperature) if extruder else ""
        time_text = _job_time(ctx).split(" ", 1)[-1]
        state = "" if printer.phase is Phase.PRINTING else ctx.t(printer.phase.value)
        return ctx.finish([bar, ctx.line(state or temp, time_text)])
    layers = printer.layers
    layer = "%s %d/%d" % (ctx.t("layer"), layers[0], layers[1]) if layers else ""
    if len(layer) > 9:  # vierstellige Schichtzahlen
        layer = "%d/%d" % layers
    return ctx.finish([_job_title(ctx), bar, _temps(ctx), ctx.line(layer, _job_time(ctx))])


def temperature_pages(ctx: PageContext) -> int:
    return max(1, math.ceil(len(ctx.printer.heaters) / ctx.rows))


def temperatures_page(ctx: PageContext, part: int = 0) -> list:
    heaters = ctx.printer.heaters[part * ctx.rows : (part + 1) * ctx.rows]
    if not heaters:
        return ctx.finish([ctx.t("temperatures"), "-"])
    return ctx.finish([ctx.line(h.name, _temp_value(h, ctx.cols)) for h in heaters])


def print_page(ctx: PageContext) -> list:
    printer = ctx.printer
    if not printer.phase.ready:
        return status_page(ctx)
    z = "Z %.2f" % printer.z if printer.z is not None else ""
    fan = "%s %d%%" % (ctx.t("fan"), round(printer.fan * 100)) if printer.fan is not None else ""
    factors = ctx.line(
        "%s %d%%" % (ctx.t("speed"), round(printer.speed_factor * 100)),
        "%s %d%%" % (ctx.t("flow"), round(printer.flow_factor * 100)),
    )
    if not printer.phase.active and printer.phase is not Phase.COMPLETE:
        return ctx.finish([ctx.t("no_job"), ctx.line(z, fan), factors])
    remaining = printer.remaining if printer.phase.active else 0
    rest = screen.duration(remaining) if remaining is not None else "-"
    lines = [
        ctx.line(
            "%s %s" % (ctx.t("elapsed"), screen.duration(printer.total_elapsed)),
            "%s %s" % (ctx.t("remaining"), rest),
        ),
        ctx.line(z, fan),
        factors,
        ctx.line(ctx.t("filament"), "%.2f m" % printer.filament_used),
    ]
    return ctx.finish(lines)


def system_page(ctx: PageContext) -> list:
    printer = ctx.printer
    address = printer.addresses[0] if printer.addresses else "-"
    if len(printer.addresses) > 1:
        address = printer.addresses[int(ctx.now // 4) % len(printer.addresses)]
    load = "" if printer.cpu_load is None else "%s %d%%" % (ctx.t("load"), round(printer.cpu_load))
    temp = "" if printer.cpu_temp is None else "CPU %.0f°" % printer.cpu_temp
    memory = "" if printer.memory_load is None else "%s %d%%" % (ctx.t("memory"), round(printer.memory_load))
    lines = [
        ctx.line(printer.hostname or ctx.t("system"), ctx.clock(ctx.wall)),
        address,
        ctx.line(temp, load),
        ctx.line(memory, ctx.t(printer.phase.value)),
    ]
    if ctx.rows < 4:
        lines = [address, ctx.line(temp, load)]
    return ctx.finish(lines)


def page_list(ctx: PageContext) -> list:
    """Alle Seiten in Reihenfolge als aufrufbare Objekte ``() -> Zeilen``."""
    pages = []
    for name in ctx.config.display.pages:
        if name == "status":
            pages.append(lambda: status_page(ctx))
        elif name == "temperatures":
            for part in range(temperature_pages(ctx)):
                pages.append(lambda part=part: temperatures_page(ctx, part))
        elif name == "print":
            pages.append(lambda: print_page(ctx))
        elif name == "system":
            pages.append(lambda: system_page(ctx))
    return pages
